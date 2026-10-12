"""Experiment run lifecycle: create -> validate-gated start -> pause/resume/step -> cancel/complete."""

from __future__ import annotations

import hashlib
import json
import shutil
import statistics
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.ml.metrics import DEFINITIONS
from app.schemas.experiments import BatchCreate, ControlResponse, ExperimentConfig, ExperimentRun, RunProgress
from app.services import datasets as ds_service
from app.services.errors import ServiceError
from app.storage.db import loads
from app.storage.repository import Repository, utcnow
from app.workers import manager

ACTIVE = ("running", "paused")
_dispatch_lock = threading.Lock()
# Config keys that must match for a fair comparison (method-specific keys are allowed to differ).
FAIRNESS_KEYS = ("dataset_id", "profile", "custom_profile", "seed", "model", "split", "openworld", "drift", "labels")


def config_hash(cfg: ExperimentConfig) -> str:
    body = cfg.model_dump(mode="json", exclude={"name", "notes"})
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def to_model(row: dict) -> ExperimentRun:
    return ExperimentRun(
        run_id=row["run_id"], seq=row["seq"], name=row["name"], status=row["status"], method=row["method"],
        dataset_id=row["dataset_id"], profile=row["profile"], data_origin=row["data_origin"],
        dataset_sha256=row["dataset_sha256"], config_hash=row["config_hash"], group_id=row.get("group_id"),
        config=ExperimentConfig.model_validate_json(row["config_json"]),
        progress=RunProgress(**(loads(row["progress_json"]) or {})),
        created_at=row["created_at"], started_at=row["started_at"], finished_at=row["finished_at"],
        error=row["error"], summary=loads(row["summary_json"]),
    )


class ExperimentService:
    def __init__(self, settings: Settings, repo: Repository):
        self.settings = settings
        self.repo = repo

    def _get(self, run_id: str) -> dict:
        row = self.repo.get_run(run_id)
        if row is None:
            raise ServiceError(f"Run '{run_id}' not found.", 404)
        return row

    def create(self, cfg: ExperimentConfig, group_id: str | None = None) -> ExperimentRun:
        from app.services.ops import apply_policy

        cfg = apply_policy(cfg, self.repo)
        ds = ds_service.resolve(self.settings.datasets_dir, cfg.dataset_id)
        profile = ds_service.pick_profile(ds, cfg.profile, cfg.custom_profile)
        if not cfg.custom_profile:
            cfg = cfg.model_copy(update={"profile": profile.name})
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_id = f"run-{stamp}-{uuid.uuid4().hex[:6]}"
        self.repo.create_run({
            "run_id": run_id, "name": cfg.name, "method": cfg.adaptation.method, "dataset_id": cfg.dataset_id,
            "profile": profile.name, "data_origin": ds.data_origin, "dataset_sha256": None,
            "config_json": cfg.model_dump_json(), "config_hash": config_hash(cfg),
            "progress_json": RunProgress().model_dump_json(), "created_at": utcnow(), "group_id": group_id,
        })
        return self.get(run_id)

    def batch(self, req: BatchCreate) -> dict:
        """One run per (method, seed) sharing a group id; started runs beyond the worker cap are queued."""
        group_id = f"grp-{uuid.uuid4().hex[:8]}"
        methods = req.methods or [req.base.adaptation.method]
        runs = []
        for method in dict.fromkeys(methods):
            for seed in dict.fromkeys(req.seeds):
                cfg = req.base.model_copy(update={
                    "seed": seed,
                    "name": f"{req.base.name} · {method} · seed {seed}",
                    "adaptation": req.base.adaptation.model_copy(update={"method": method}),
                })
                runs.append(self.create(cfg, group_id))
        if req.start:
            runs = [self.start(r.run_id) for r in runs]
        return {"group_id": group_id, "runs": runs}

    def get(self, run_id: str) -> ExperimentRun:
        return to_model(self._get(run_id))

    def list(self, status: str | None, method: str | None, page: int, page_size: int) -> tuple[list[ExperimentRun], int]:
        rows, total = self.repo.list_runs(status, method, (page - 1) * page_size, page_size)
        return [to_model(r) for r in rows], total

    def start(self, run_id: str, inline: bool = False) -> ExperimentRun:
        row = self._get(run_id)
        if row["status"] in (*ACTIVE, "queued"):
            raise ServiceError(f"Run '{run_id}' is already {row['status']}.", 409)
        if row["status"] == "completed":
            raise ServiceError("Run already completed; create a new run to repeat it (keeps results immutable).", 409)
        cfg = ExperimentConfig.model_validate_json(row["config_json"])
        ds = ds_service.resolve(self.settings.datasets_dir, cfg.dataset_id)
        profile = ds_service.pick_profile(ds, cfg.profile, cfg.custom_profile)
        report = ds_service.require_valid(self.settings.datasets_dir, self.repo, cfg.dataset_id, profile)
        self.repo.delete_run_results(run_id)
        self.repo.update_run(run_id, status="queued", control="run", error=None, started_at=utcnow(),
                             finished_at=None, summary=None, data_origin=report["data_origin"],
                             dataset_sha256=report["sha256"],
                             progress=RunProgress(phase="queued").model_dump())
        if inline:
            from app.workers.runner import execute

            self.repo.update_run(run_id, status="running")
            execute(run_id, self.settings)
        else:
            self.dispatch()
        return self.get(run_id)

    def dispatch(self) -> int:
        """Start queued runs (oldest first) while fewer than `max_workers` are running or paused."""
        started = 0
        with _dispatch_lock:
            while self.repo.count_status(*ACTIVE) < max(1, self.settings.max_workers):
                run_id = self.repo.oldest_queued()
                if run_id is None:
                    break
                self.repo.update_run(run_id, status="running")
                try:
                    manager.spawn(run_id, self.settings, self.repo)
                    started += 1
                except OSError as e:
                    self.repo.update_run(run_id, status="failed", error=f"Could not start worker: {e}",
                                         finished_at=utcnow())
        return started

    def _control(self, run_id: str, allowed: tuple[str, ...], control: str, message: str,
                 status: str | None = None) -> ControlResponse:
        row = self._get(run_id)
        if row["status"] not in allowed:
            raise ServiceError(f"Cannot {control} a run that is {row['status']}.", 409)
        fields: dict[str, Any] = {"control": control}
        if status:
            fields["status"] = status
        self.repo.update_run(run_id, **fields)
        return ControlResponse(run_id=run_id, status=status or row["status"], control=control, message=message)

    def pause(self, run_id: str) -> ControlResponse:
        return self._control(run_id, ("running",), "pause", "Pausing after the current window.")

    def resume(self, run_id: str) -> ControlResponse:
        return self._control(run_id, ("paused", "running"), "run", "Resuming replay.")

    def step(self, run_id: str) -> ControlResponse:
        return self._control(run_id, ("paused", "running"), "step", "Processing exactly one more window, then pausing.")

    def cancel(self, run_id: str) -> ControlResponse:
        row = self._get(run_id)
        if row["status"] in ("created", "queued"):
            self.repo.update_run(run_id, status="cancelled", control="cancel", finished_at=utcnow())
            return ControlResponse(run_id=run_id, status="cancelled", control="cancel", message="Run cancelled.")
        resp = self._control(run_id, ACTIVE, "cancel", "Cancelling after the current window.")
        manager.ensure_stopped(run_id, self.repo)
        return resp

    def delete(self, run_id: str) -> None:
        """Remove a finished run, its stored results and its files under the results directory."""
        row = self._get(run_id)
        if row["status"] in (*ACTIVE, "queued"):
            raise ServiceError(f"Run is {row['status']}; cancel it before deleting.", 409)
        self.repo.delete_run(run_id)
        folder = (self.settings.results_dir / run_id).resolve()
        if folder.parent == self.settings.results_dir.resolve() and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)

    @staticmethod
    def _aggregate(runs: list[ExperimentRun]) -> list[dict]:
        """Mean / sample std per method over runs that differ only by seed."""
        groups: dict[tuple, list[ExperimentRun]] = {}
        for r in runs:
            body = r.config.model_dump(mode="json", exclude={"name", "notes", "seed"})
            groups.setdefault((r.method, json.dumps(body, sort_keys=True)), []).append(r)
        out = []
        for (method, _), members in groups.items():
            done = [m for m in members if m.summary]
            keys = sorted({k for m in done for k, v in m.summary["overall"].items()
                           if isinstance(v, (int, float)) and not isinstance(v, bool)})
            metrics = {}
            for k in keys:
                vals = [m.summary["overall"][k] for m in done if isinstance(m.summary["overall"].get(k), (int, float))]
                if vals:
                    metrics[k] = {"mean": statistics.fmean(vals),
                                  "std": statistics.stdev(vals) if len(vals) > 1 else 0.0}
            out.append({"method": method, "n": len(done), "seeds": sorted(m.config.seed for m in done),
                        "run_ids": [m.run_id for m in done], "metrics": metrics})
        return out

    def compare(self, run_ids: list[str]) -> dict:
        runs = [self.get(r) for r in run_ids]
        differences: dict[str, list] = {}
        for key in FAIRNESS_KEYS:
            values = [r.config.model_dump(mode="json").get(key) for r in runs]
            if any(v != values[0] for v in values[1:]):
                differences[key] = values
        aggregates = self._aggregate(runs)
        # Multi-seed design: differing seeds are fine when every method was run on the same seed set.
        seed_sets = {tuple(a["seeds"]) for a in aggregates}
        if "seed" in differences and len(seed_sets) == 1 and len(next(iter(seed_sets))) > 1:
            differences.pop("seed")
        hashes = {r.dataset_sha256 for r in runs}
        if len(hashes) > 1:
            differences["dataset_sha256"] = [r.dataset_sha256 for r in runs]
        origins = {r.data_origin for r in runs}
        return {
            "runs": [{"run_id": r.run_id, "name": r.name, "method": r.method, "status": r.status,
                      "data_origin": r.data_origin, "metrics": (r.summary or {}).get("overall")} for r in runs],
            "aggregates": aggregates,
            "fair": not differences,
            "differences": differences,
            "mixed_data_origin": len(origins) > 1,
            "definitions": DEFINITIONS,
        }
