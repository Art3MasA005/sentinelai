from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import actor, get_repo
from app.config import Settings, get_settings
from app.schemas.common import Page
from app.schemas.ops import (Alert, AlertDetail, AlertState, AlertSummary, AlertUpdate, Policy, PolicyCreate,
                             ReportStats, Severity, SystemStatus)
from app.services import ops, views
from app.services.errors import ServiceError
from app.storage.repository import Repository

router = APIRouter(tags=["operations"])


def _run(repo: Repository, run_id: str) -> dict:
    row = repo.get_run(run_id)
    if row is None:
        raise ServiceError(f"Run '{run_id}' not found.", 404)
    return row


# ---------- alerts ----------


@router.get("/experiments/{run_id}/alerts", response_model=Page[Alert])
def list_alerts(run_id: str, severity: Severity | None = None, state: AlertState | None = None,
                window: int | None = None, decision: str | None = None,
                sort: Literal["flow_id", "timestamp", "confidence", "attack_score"] = "flow_id", desc: bool = True,
                page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                repo: Repository = Depends(get_repo)):
    """Alerts = flows whose decision is not benign. UNKNOWN decisions have severity 'review'."""
    row = _run(repo, run_id)
    items, total = repo.alerts(run_id, ops.benign_labels(row),
                               {"severity": severity, "state": state, "window": window, "decision": decision},
                               sort, desc, (page - 1) * page_size, page_size)
    return Page(items=[ops.to_alert(r) for r in items], total=total, page=page, page_size=page_size,
                data_origin=row["data_origin"])


@router.get("/experiments/{run_id}/alerts/summary", response_model=AlertSummary)
def alert_summary(run_id: str, repo: Repository = Depends(get_repo)):
    row = _run(repo, run_id)
    return repo.alert_summary(run_id, ops.benign_labels(row), ops.today_prefix())


def _alert_or_404(repo: Repository, row: dict, flow_id: int) -> dict:
    items, _ = repo.alerts(row["run_id"], ops.benign_labels(row), {"flow_id": flow_id}, "flow_id", True, 0, 1)
    if not items:
        raise ServiceError(f"Flow {flow_id} is not an alert in run '{row['run_id']}'.", 404)
    return items[0]


@router.get("/experiments/{run_id}/alerts/{flow_id}", response_model=AlertDetail)
def alert_detail(run_id: str, flow_id: int, repo: Repository = Depends(get_repo)):
    row = _run(repo, run_id)
    alert = _alert_or_404(repo, row, flow_id)
    return {"alert": ops.to_alert(alert), "flow": views.flow_detail(repo.flow(run_id, flow_id)),
            "history": repo.alert_history(run_id, flow_id)}


@router.patch("/experiments/{run_id}/alerts/{flow_id}", response_model=AlertDetail)
def update_alert(run_id: str, flow_id: int, body: AlertUpdate, repo: Repository = Depends(get_repo),
                 who: str | None = Depends(actor)):
    row = _run(repo, run_id)
    _alert_or_404(repo, row, flow_id)
    repo.set_alert_state(run_id, flow_id, body.state, body.note, who or body.updated_by)
    return alert_detail(run_id, flow_id, repo)


# ---------- policies ----------


def _policy(p: dict) -> Policy:
    return Policy(version=p["version"], policy_id=ops.policy_id(p["version"]), status=p["status"], note=p["note"],
                  updated_by=p["updated_by"], created_at=p["created_at"], body=p["body"])


@router.get("/policies", response_model=list[Policy])
def list_policies(repo: Repository = Depends(get_repo)):
    return [_policy(p) for p in repo.policies()]


@router.get("/policies/active", response_model=Policy)
def active_policy(repo: Repository = Depends(get_repo)):
    ops.ensure_default_policy(repo)
    return _policy(repo.policy())


@router.post("/policies", response_model=Policy, status_code=201)
def create_policy(req: PolicyCreate, repo: Repository = Depends(get_repo), who: str | None = Depends(actor)):
    """Saves a new policy version and makes it active; earlier versions become 'superseded'."""
    version = repo.add_policy(req.body.model_dump(mode="json"), req.note, who or req.updated_by)
    return _policy(repo.policy(version))


# ---------- system & reports ----------


@router.get("/system", response_model=SystemStatus)
def system(settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    return ops.system_status(settings, repo)


@router.get("/reports/stats", response_model=ReportStats)
def report_stats(repo: Repository = Depends(get_repo)):
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    s = repo.export_stats(since)
    return ReportStats(completed_runs=s["completed_runs"], exports_this_week=s["exports_since"],
                       last_export=s["last_export"])
