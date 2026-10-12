"""Spawns and supervises worker processes (one per running experiment)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from app.config import Settings
from app.storage.repository import Repository, utcnow

BACKEND_DIR = Path(__file__).resolve().parents[2]
CANCEL_GRACE_SECONDS = 20
_procs: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def spawn(run_id: str, settings: Settings, repo: Repository) -> int:
    log_dir = settings.results_dir / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    with open(log_dir / "worker.stdout.log", "ab") as out:
        proc = subprocess.Popen([sys.executable, "-m", "app.workers.runner", run_id], cwd=BACKEND_DIR,
                                stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
    with _lock:
        _procs[run_id] = proc
    repo.update_run(run_id, pid=proc.pid)
    threading.Thread(target=_reap, args=(run_id, proc, repo, settings), daemon=True).start()
    return proc.pid


def _reap(run_id: str, proc: subprocess.Popen, repo: Repository, settings: Settings) -> None:
    code = proc.wait()
    with _lock:
        _procs.pop(run_id, None)
    row = repo.get_run(run_id)
    if row and row["status"] in ("running", "paused"):
        repo.update_run(run_id, status="failed", finished_at=utcnow(),
                        error=f"Worker process exited unexpectedly (exit code {code}).")
    from app.services.experiments import ExperimentService  # local: the service imports this module

    ExperimentService(settings, repo).dispatch()


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def ensure_stopped(run_id: str, repo: Repository) -> None:
    """Cancellation is cooperative (checked between windows); kill the worker if it ignores it."""

    def watchdog():
        deadline = time.monotonic() + CANCEL_GRACE_SECONDS
        while time.monotonic() < deadline:
            row = repo.get_run(run_id)
            if not row or row["status"] not in ("running", "paused"):
                return
            time.sleep(0.5)
        row = repo.get_run(run_id)
        if row and row["status"] in ("running", "paused") and _alive(row["pid"]):
            psutil.Process(row["pid"]).kill()
            repo.update_run(run_id, status="cancelled", finished_at=utcnow(),
                            error=f"Worker killed after not stopping within {CANCEL_GRACE_SECONDS}s.")

    threading.Thread(target=watchdog, daemon=True).start()


def reconcile(repo: Repository) -> int:
    """On API start: runs left 'running' by a dead worker are marked failed."""
    fixed = 0
    for status in ("running", "paused"):
        rows, _ = repo.list_runs(status, None, 0, 10_000)
        for r in rows:
            if r["run_id"] not in _procs and not _alive(r["pid"]):
                repo.update_run(r["run_id"], status="failed", finished_at=utcnow(),
                                error="Worker process was not running when the API started.")
                fixed += 1
    return fixed


def active_workers() -> int:
    with _lock:
        return sum(p.poll() is None for p in _procs.values())
