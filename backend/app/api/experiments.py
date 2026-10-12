from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse

from app.api.deps import get_experiments, get_repo
from app.config import Settings, get_settings
from app.ml.metrics import DEFINITIONS
from app.schemas.common import Page
from app.schemas.events import (AdaptationEvent, DriftEvent, FlowDetail, FlowRecord, ModelVersion, RunMetrics)
from app.schemas.common import Message
from app.schemas.experiments import (BatchCreate, BatchResult, Comparison, ControlResponse, ExperimentConfig,
                                     ExperimentRun, RunStatus)
from app.services import exports, views
from app.services.errors import ServiceError
from app.services.experiments import ExperimentService
from app.storage.db import loads
from app.storage.repository import Repository

router = APIRouter(prefix="/experiments", tags=["experiments"])


def _run_row(repo: Repository, run_id: str) -> dict:
    row = repo.get_run(run_id)
    if row is None:
        raise ServiceError(f"Run '{run_id}' not found.", 404)
    return row


@router.post("", response_model=ExperimentRun, status_code=201)
def create_experiment(cfg: ExperimentConfig, svc: ExperimentService = Depends(get_experiments)):
    return svc.create(cfg)


@router.post("/batch", response_model=BatchResult, status_code=201)
def create_batch(req: BatchCreate, svc: ExperimentService = Depends(get_experiments)):
    """Multi-seed / multi-method batch. Runs beyond SENTINEL_MAX_WORKERS wait with status 'queued'."""
    return svc.batch(req)


@router.get("", response_model=Page[ExperimentRun])
def list_experiments(status: RunStatus | None = None, method: str | None = None,
                     page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
                     svc: ExperimentService = Depends(get_experiments)):
    items, total = svc.list(status, method, page, page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/compare", response_model=Comparison)
def compare(run_ids: str = Query(..., description="Comma-separated run IDs"),
            svc: ExperimentService = Depends(get_experiments)):
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    if len(ids) < 2:
        raise ServiceError("Give at least two run IDs.", 422)
    return svc.compare(ids)


@router.get("/compare/figures")
def compare_figures(run_ids: str = Query(..., description="Comma-separated run IDs"),
                    svc: ExperimentService = Depends(get_experiments), repo: Repository = Depends(get_repo)):
    """ZIP of comparison figures (PNG + PDF): macro-F1 over windows and per-method mean ± std."""
    from app.services import figures

    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    if len(ids) < 2:
        raise ServiceError("Give at least two run IDs.", 422)
    cmp = svc.compare(ids)
    rows = [_run_row(repo, i) for i in ids]
    files = figures.comparison_figures(repo, rows, cmp["aggregates"])
    demo = any(r["data_origin"] == "demo" for r in rows)
    name = f"{'DEMO_' if demo else ''}comparison_{len(ids)}_runs"
    data = figures.zip_figures(files, {"runs": ids, "fair": cmp["fair"], "differences": cmp["differences"],
                                       "aggregates": cmp["aggregates"]}, name)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}_figures.zip"'})


@router.get("/{run_id}", response_model=ExperimentRun)
def get_experiment(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.get(run_id)


@router.delete("/{run_id}", response_model=Message)
def delete_experiment(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    svc.delete(run_id)
    return Message(message=f"Run {run_id} deleted.")


@router.post("/{run_id}/start", response_model=ExperimentRun, status_code=202)
def start(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.start(run_id)


@router.post("/{run_id}/cancel", response_model=ControlResponse)
def cancel(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.cancel(run_id)


@router.post("/{run_id}/pause", response_model=ControlResponse)
def pause(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.pause(run_id)


@router.post("/{run_id}/resume", response_model=ControlResponse)
def resume(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.resume(run_id)


@router.post("/{run_id}/step", response_model=ControlResponse)
def step(run_id: str, svc: ExperimentService = Depends(get_experiments)):
    return svc.step(run_id)


@router.get("/{run_id}/metrics", response_model=RunMetrics)
def metrics(run_id: str, include_windows: bool = True, repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    summary = loads(row["summary_json"]) or {}
    return RunMetrics(
        run_id=run_id, status=row["status"], data_origin=row["data_origin"],
        overall=summary.get("overall"), confusion_matrix=summary.get("confusion_matrix"),
        windows=[views.window(w) for w in repo.windows(run_id)] if include_windows else None,
        definitions=DEFINITIONS,
        provenance={**exports.provenance(row), "split": summary.get("split"), "integrity": summary.get("integrity"),
                    "openworld": summary.get("openworld"), "initial_classes": summary.get("initial_classes"),
                    "final_classes": summary.get("final_classes")},
    )


@router.get("/{run_id}/overview")
def overview(run_id: str, repo: Repository = Depends(get_repo)):
    """Everything the Overview screen needs in one call."""
    row = _run_row(repo, run_id)
    summary = loads(row["summary_json"]) or {}
    wins = repo.windows(run_id)
    n_drift = repo.drift_events(run_id, None, 0, 1)[1]
    n_adapt = repo.adaptation_events(run_id, None, 0, 1)[1]
    drift = repo.drift_events(run_id, None, max(n_drift - 10, 0), 10)[0]
    adapt = repo.adaptation_events(run_id, None, max(n_adapt - 10, 0), 10)[0]
    unknown_total = repo.flows(run_id, {"is_unknown": True}, "flow_id", False, 0, 1)[1]
    trend_keys = ("macro_f1", "fpr", "unknown_rate", "ref_macro_f1", "pr_auc")
    return {
        "run_id": run_id, "name": row["name"], "status": row["status"], "method": row["method"],
        "data_origin": row["data_origin"], "is_demo": row["data_origin"] == "demo",
        "dataset_id": row["dataset_id"], "progress": loads(row["progress_json"]),
        "kpis": {"flows": sum(w["n_flows"] for w in wins), "windows": len(wins),
                 "unknown_flows": unknown_total, "drift_events": n_drift, "adaptation_events": n_adapt,
                 **{k: (summary.get("overall") or {}).get(k) for k in ("macro_f1", "fpr", "pr_auc", "unknown_recall",
                                                                      "labels_used", "rollbacks")}},
        "trends": [{"window": w["window"], "start_ts": w["start_ts"], "model_version": w["model_version"],
                    **{k: w["metrics"].get(k) for k in trend_keys},
                    "drift_triggered": any(d["triggered"] for d in (w["drift"] or {}).values())} for w in wins],
        "recent_drift_events": [views.drift(d) for d in drift],
        "recent_adaptation_events": [views.adaptation(a) for a in adapt],
    }


@router.get("/{run_id}/flows", response_model=Page[FlowRecord])
def flows(run_id: str,
          window: int | None = None,
          decision: str | None = None,
          true_label: str | None = None,
          predicted_label: str | None = None,
          is_unknown: bool | None = None,
          is_novel_class: bool | None = None,
          misclassified: bool = False,
          min_attack_score: float | None = Query(None, ge=0, le=1),
          max_confidence: float | None = Query(None, ge=0, le=1),
          model_version: int | None = None,
          sort: Literal["flow_id", "timestamp", "confidence", "attack_score", "novelty_score"] = "flow_id",
          desc: bool = False,
          page: int = Query(1, ge=1),
          page_size: int = Query(50, ge=1, le=500),
          repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    filters = dict(window=window, decision=decision, true_label=true_label, predicted_label=predicted_label,
                   is_unknown=is_unknown, is_novel_class=is_novel_class, misclassified=misclassified,
                   min_attack_score=min_attack_score, max_confidence=max_confidence, model_version=model_version)
    items, total = repo.flows(run_id, filters, sort, desc, (page - 1) * page_size, page_size)
    return Page(items=[views.flow(r) for r in items], total=total, page=page, page_size=page_size,
                data_origin=row["data_origin"])


@router.get("/{run_id}/flows/{flow_id}", response_model=FlowDetail)
def flow_detail(run_id: str, flow_id: int, repo: Repository = Depends(get_repo)):
    _run_row(repo, run_id)
    r = repo.flow(run_id, flow_id)
    if r is None:
        raise ServiceError(f"Flow {flow_id} not found in run '{run_id}'.", 404)
    return views.flow_detail(r)


@router.get("/{run_id}/class-distribution")
def class_distribution(run_id: str, repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    return {"run_id": run_id, "data_origin": row["data_origin"], **repo.label_counts(run_id)}


@router.get("/{run_id}/drift-events", response_model=Page[DriftEvent])
def drift_events(run_id: str, method: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(100, ge=1, le=500), repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    items, total = repo.drift_events(run_id, method, (page - 1) * page_size, page_size)
    return Page(items=[views.drift(r) for r in items], total=total, page=page, page_size=page_size,
                data_origin=row["data_origin"])


@router.get("/{run_id}/adaptation-events", response_model=Page[AdaptationEvent])
def adaptation_events(run_id: str, decision: str | None = None, page: int = Query(1, ge=1),
                      page_size: int = Query(100, ge=1, le=500), repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    items, total = repo.adaptation_events(run_id, decision, (page - 1) * page_size, page_size)
    return Page(items=[views.adaptation(r) for r in items], total=total, page=page, page_size=page_size,
                data_origin=row["data_origin"])


@router.get("/{run_id}/models", response_model=list[ModelVersion])
def model_versions(run_id: str, repo: Repository = Depends(get_repo)):
    _run_row(repo, run_id)
    return [views.model_version(m) for m in repo.model_versions(run_id)]


@router.get("/{run_id}/logs")
def logs(run_id: str, tail: int = Query(200, ge=1, le=5000), settings: Settings = Depends(get_settings),
         repo: Repository = Depends(get_repo)):
    _run_row(repo, run_id)
    path = settings.results_dir / run_id / "run.log"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:] if path.exists() else []
    return {"run_id": run_id, "lines": lines}


@router.get("/{run_id}/export")
def export(run_id: str, format: Literal["csv", "json", "zip", "figures"] = "csv",
           kind: Literal["predictions", "windows", "drift", "adaptation", "models"] = "predictions",
           settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    row = _run_row(repo, run_id)
    repo.log_export(run_id, format, kind if format == "csv" else None)
    prefix = exports.file_prefix(row)
    headers = {"X-Run-Id": run_id, "X-Data-Origin": row["data_origin"] or "", "X-Config-Hash": row["config_hash"]}
    if format == "csv":
        headers["Content-Disposition"] = f'attachment; filename="{prefix}_{kind}.csv"'
        return StreamingResponse(exports.csv_chunks(repo, row, kind), media_type="text/csv", headers=headers)
    if format == "figures":
        from app.services import figures

        files = figures.run_figures(repo, row)
        if not files:
            raise ServiceError("This run has no windows to plot yet.", 409)
        headers["Content-Disposition"] = f'attachment; filename="{prefix}_figures.zip"'
        manifest = {"provenance": exports.provenance(row), "figures": sorted(files)}
        return Response(figures.zip_figures(files, manifest, f"{prefix}_figures"), media_type="application/zip",
                        headers=headers)
    if format == "json":
        headers["Content-Disposition"] = f'attachment; filename="{prefix}.json"'
        body = json.dumps(exports.json_bundle(repo, row), default=str)
        return Response(body, media_type="application/json", headers=headers)
    headers["Content-Disposition"] = f'attachment; filename="{prefix}.zip"'
    data = exports.zip_bytes(repo, row, settings.results_dir / run_id / "run.log")
    return Response(data, media_type="application/zip", headers=headers)
