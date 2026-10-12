"""Alert triage, policy versions and local system status."""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

from app.config import Settings
from app.ml.profiles import get_profile
from app.schemas.experiments import ExperimentConfig
from app.schemas.ops import Alert, DiagnosticEvent, PolicyBody, ServiceStatus
from app.services import views
from app.services.errors import ServiceError
from app.services.exports import package_version
from app.storage.repository import Repository
from app.workers import manager

# ---------- alerts ----------


def benign_labels(run_row: dict) -> list[str]:
    cfg = ExperimentConfig.model_validate_json(run_row["config_json"])
    profile = cfg.custom_profile or get_profile(cfg.profile or run_row["profile"])
    return list(profile.benign_labels)


def to_alert(r: dict) -> Alert:
    return Alert(
        alert_id=f"ALT-{r['flow_id']:06d}", flow_id=r["flow_id"], window=r["window"], timestamp=views.ts(r["ts"]),
        decision=r["decision"], predicted_label=r["predicted_label"], true_label=r["true_label"],
        confidence=r["confidence"], attack_score=r["attack_score"], novelty_score=r["novelty_score"],
        unknown_reason=r["unknown_reason"], is_novel_class=bool(r["is_novel_class"]),
        model_version=r["model_version"], src=r["src"], dst=r["dst"], protocol=r["protocol"],
        severity=r["severity"], state=r["state"], note=r["note"],
        updated_at=r["updated_at"], updated_by=r["updated_by"],
    )


def today_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------- policies ----------


def policy_id(version: int) -> str:
    return f"POL-{version:03d}"


def ensure_default_policy(repo: Repository) -> None:
    if repo.policy() is None:
        repo.add_policy(PolicyBody().model_dump(mode="json"), "Initial default policy", "system")


def apply_policy(cfg: ExperimentConfig, repo: Repository) -> ExperimentConfig:
    if cfg.policy_version is None:
        return cfg
    p = repo.policy(cfg.policy_version)
    if p is None:
        raise ServiceError(f"Policy version {cfg.policy_version} not found.", 404)
    body = PolicyBody.model_validate(p["body"])
    adaptation = body.adaptation.model_copy(update={"method": cfg.adaptation.method})
    return cfg.model_copy(update={
        "split": cfg.split.model_copy(update={"window_size": body.window_size}),
        "openworld": body.openworld, "drift": body.drift, "labels": body.labels, "adaptation": adaptation,
    })


# ---------- system ----------

_gpu_cache: tuple[float, dict | None] = (0.0, None)
_LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ (\w+) (.*)$")


def gpu_status() -> dict | None:
    global _gpu_cache
    if time.monotonic() - _gpu_cache[0] < 10:
        return _gpu_cache[1]
    info = None
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip().splitlines()
            if out:
                name, used, total, util = [x.strip() for x in out[0].split(",")]
                info = {"name": name, "memory_percent": 100 * float(used) / max(float(total), 1),
                        "utilization_percent": float(util)}
        except (OSError, ValueError, subprocess.SubprocessError):
            info = None
    _gpu_cache = (time.monotonic(), info)
    return info


def services(settings: Settings) -> list[ServiceStatus]:
    out = [
        ServiceStatus(name="FastAPI", version=package_version("fastapi"), status="Healthy", ok=True),
        ServiceStatus(name="Python", version=".".join(map(str, __import__("sys").version_info[:3])),
                      status="Ready", ok=True),
    ]
    try:
        with sqlite3.connect(settings.db_path, timeout=5) as c:
            c.execute("SELECT 1").fetchone()
        out.append(ServiceStatus(name="SQLite", version=sqlite3.sqlite_version, status="Connected", ok=True))
    except sqlite3.Error as e:
        out.append(ServiceStatus(name="SQLite", version=sqlite3.sqlite_version, status=f"Error: {e}", ok=False))
    for name, pkg in (("scikit-learn", "scikit-learn"), ("LightGBM", "lightgbm"), ("PyTorch", "torch")):
        v = package_version(pkg)
        out.append(ServiceStatus(name=name, version=v, status="Ready" if v else "Not installed", ok=v is not None))
    return out


def _component(msg: str) -> tuple[str, str]:
    m = msg.lower()
    if "drift detected" in m:
        return "Drift module", "warning"
    if "adaptation" in m:
        return "Adaptation", "info"
    if "trained model" in m:
        return "Trainer", "info"
    if "failed" in m or "error" in m or "traceback" in m:
        return "Replay worker", "error"
    return "Replay worker", "info"


def diagnostics(settings: Settings, repo: Repository, limit: int = 40) -> list[DiagnosticEvent]:
    rows, _ = repo.list_runs(None, None, 0, 3)
    events: list[DiagnosticEvent] = []
    for r in rows:
        path: Path = settings.results_dir / r["run_id"] / "run.log"
        if not path.exists():
            continue
        # Newest first, so lines logged within the same second keep their real order after the sort.
        for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]):
            m = _LOG_LINE.match(line)
            if not m:
                continue
            component, level = _component(m.group(3))
            if m.group(2) == "ERROR":
                level = "error"
            events.append(DiagnosticEvent(
                time=datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), component=component,
                event=m.group(3)[:300], level=level, run_id=r["run_id"]))
    events.sort(key=lambda e: e.time or datetime.min, reverse=True)
    return events[:limit]


def system_status(settings: Settings, repo: Repository) -> dict:
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(settings.results_dir))
    running, _ = repo.list_runs("running", None, 0, 50)
    paused, _ = repo.list_runs("paused", None, 0, 50)
    active = running + paused
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / 2**30, 2),
        "memory_total_gb": round(mem.total / 2**30, 2),
        "disk_percent": disk.percent,
        "disk_free_gb": round(disk.free / 2**30, 1),
        "gpu": gpu_status(),
        "services": services(settings),
        "worker": {
            "state": "busy" if active else "idle",
            "active_workers": manager.active_workers(),
            "runs": [{"run_id": r["run_id"], "name": r["name"], "status": r["status"]} for r in active],
        },
        "diagnostics": diagnostics(settings, repo),
    }
