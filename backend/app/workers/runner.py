"""Worker entry point: `python -m app.workers.runner <run_id>`. Runs one experiment in its own process
so the API (and the Flutter UI) stays responsive during long jobs."""

from __future__ import annotations

import csv
import gzip
import json
import logging
import os
import sys
import traceback
from pathlib import Path

from app.config import Settings, get_settings
from app.ml.models import DeployedModel
from app.ml.pipeline import Cancelled, ExperimentEngine
from app.schemas.experiments import ExperimentConfig, RunProgress
from app.services import datasets as ds_service
from app.services import exports
from app.storage.db import init_db
from app.storage.repository import Repository, utcnow


FLOW_FILE_COLUMNS = ["flow_id", "window", "row_index", "ts", "true_label", "predicted_label", "decision",
                     "confidence", "attack_score", "novelty_score", "is_unknown", "unknown_reason", "is_novel_class",
                     "model_version", "src", "dst", "protocol", "probabilities_json"]


class DbSink:
    def __init__(self, run_id: str, repo: Repository, log_path: Path, flow_file: Path | None = None):
        self.run_id = run_id
        self.repo = repo
        # With flow_file set, per-flow rows are streamed to a gzip CSV instead of the database.
        self.flow_file = flow_file
        self._flow_fh = None
        self._flow_writer = None
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger(f"sentinel.run.{run_id}")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self.logger.handlers = [handler]

    def log(self, message: str) -> None:
        self.logger.info(message)

    def progress(self, phase: str, window: int, total_windows: int, flows: int) -> None:
        self.repo.update_run(self.run_id, progress=RunProgress(phase=phase, window=window, total_windows=total_windows,
                                                               flows_processed=flows).model_dump())

    def control(self) -> str:
        return self.repo.get_control(self.run_id)

    def ack_step(self) -> None:
        if self.repo.get_control(self.run_id) == "step":
            self.repo.update_run(self.run_id, control="pause")

    def set_paused(self, paused: bool) -> None:
        self.repo.update_run(self.run_id, status="paused" if paused else "running")
        self.log("paused" if paused else "resumed")

    def write_model(self, model: DeployedModel, status: str) -> None:
        self.repo.write_model(self.run_id, {
            "version": model.version, "parent_version": model.parent_version, "created_window": model.created_window,
            "status": status, "classes": model.classes, "train_rows": model.train_rows,
            "train_seconds": model.train_seconds, "model_bytes": model.model_bytes, "created_at": utcnow(),
        })

    def set_model_status(self, version: int, status: str) -> None:
        self.repo.set_model_status(self.run_id, version, status)

    def write_window(self, window, flows, drift_events, adaptation_events) -> None:
        if self.flow_file is not None:
            if self._flow_writer is None:
                self.flow_file.parent.mkdir(parents=True, exist_ok=True)
                self._flow_fh = gzip.open(self.flow_file, "wt", encoding="utf-8", newline="")
                self._flow_writer = csv.DictWriter(self._flow_fh, FLOW_FILE_COLUMNS, extrasaction="ignore")
                self._flow_writer.writeheader()
            for f in flows:
                self._flow_writer.writerow({**f, "is_unknown": int(f["is_unknown"]),
                                            "is_novel_class": int(f["is_novel_class"]),
                                            "probabilities_json": json.dumps(f["probabilities"])})
            flows = []
        self.repo.write_window(self.run_id, window, flows, drift_events, adaptation_events)

    def close(self) -> None:
        if self._flow_fh is not None:
            self._flow_fh.close()
            self._flow_fh = self._flow_writer = None

    def finish(self, summary: dict) -> None:
        self.close()
        self.repo.update_run(self.run_id, summary=summary)


def execute(run_id: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    repo = Repository(settings.db_path)
    row = repo.get_run(run_id)
    if row is None:
        raise SystemExit(f"unknown run {run_id}")
    out_dir = settings.results_dir / run_id
    cfg = ExperimentConfig.model_validate_json(row["config_json"])
    sink = DbSink(run_id, repo, out_dir / "run.log",
                  out_dir / "predictions.csv.gz" if cfg.flow_storage == "file" else None)
    repo.update_run(run_id, pid=os.getpid())
    try:
        ds = ds_service.resolve(settings.datasets_dir, cfg.dataset_id)
        profile = ds_service.pick_profile(ds, cfg.profile, cfg.custom_profile)
        sink.log(f"run {run_id} started: method={cfg.adaptation.method} dataset={cfg.dataset_id} "
                 f"profile={profile.name} origin={ds.data_origin} seed={cfg.seed}")
        ExperimentEngine(cfg, ds.files, profile, ds.data_origin, sink).run()
        repo.update_run(run_id, status="completed", control="run", finished_at=utcnow())
        sink.log("completed")
    except Cancelled:
        repo.update_run(run_id, status="cancelled", finished_at=utcnow())
        sink.log("cancelled by user")
    except Exception as e:  # noqa: BLE001 - record any failure on the run
        repo.update_run(run_id, status="failed", error=f"{type(e).__name__}: {e}", finished_at=utcnow())
        sink.log("failed:\n" + traceback.format_exc())
    finally:
        sink.close()
        try:
            exports.write_artifacts(repo, run_id, out_dir)
        except Exception:  # noqa: BLE001
            sink.log("could not write result artifacts:\n" + traceback.format_exc())
        for h in sink.logger.handlers:
            h.close()


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.workers.runner <run_id>")
    settings = get_settings()
    init_db(settings.db_path)
    execute(sys.argv[1], settings)


if __name__ == "__main__":
    main()
