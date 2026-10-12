"""Schemas for alert triage, versioned policies, system status and report stats."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.events import FlowDetail
from app.schemas.experiments import AdaptationConfig, DriftConfig, LabelPolicy, OpenWorldConfig

AlertState = Literal["open", "investigating", "resolved"]
# "review" = UNKNOWN decision (uncertain, not confirmed malicious); others come from attack_score.
Severity = Literal["review", "critical", "high", "medium", "low"]


class Alert(BaseModel):
    alert_id: str
    flow_id: int
    window: int
    timestamp: datetime | None
    decision: str
    predicted_label: str
    true_label: str
    confidence: float
    attack_score: float | None
    novelty_score: float | None
    unknown_reason: str | None
    is_novel_class: bool
    model_version: int
    src: str | None = None
    dst: str | None = None
    protocol: str | None = None
    severity: Severity
    state: AlertState
    note: str | None
    updated_at: datetime | None
    updated_by: str | None


class AlertSummary(BaseModel):
    total: int
    open: int
    investigating: int
    resolved: int
    critical: int
    under_review: int
    resolved_today: int


class AlertUpdate(BaseModel):
    state: AlertState
    note: str | None = Field(None, max_length=2000)
    updated_by: str = Field("Researcher", max_length=80)


class AlertHistoryItem(BaseModel):
    from_state: str
    to_state: str
    note: str | None
    updated_by: str
    at: datetime


class AlertDetail(BaseModel):
    alert: Alert
    flow: FlowDetail
    history: list[AlertHistoryItem]


class PolicyBody(BaseModel):
    """Experiment rules that a policy fixes. `adaptation.method` is ignored (chosen per experiment)."""

    window_size: int = Field(2000, ge=10)
    openworld: OpenWorldConfig = Field(default_factory=OpenWorldConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    labels: LabelPolicy = Field(default_factory=LabelPolicy)
    adaptation: AdaptationConfig = Field(default_factory=AdaptationConfig)


class Policy(BaseModel):
    version: int
    policy_id: str
    status: Literal["active", "superseded"]
    note: str
    updated_by: str
    created_at: datetime
    body: PolicyBody


class PolicyCreate(BaseModel):
    body: PolicyBody
    note: str = Field(..., min_length=1, max_length=300)
    updated_by: str = Field("Researcher", max_length=80)


class ServiceStatus(BaseModel):
    name: str
    version: str | None
    status: str
    ok: bool


class DiagnosticEvent(BaseModel):
    time: datetime | None
    component: str
    event: str
    level: Literal["info", "warning", "error"]
    run_id: str | None


class SystemStatus(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_used_gb: float
    memory_total_gb: float
    disk_percent: float
    disk_free_gb: float
    gpu: dict[str, Any] | None
    services: list[ServiceStatus]
    worker: dict[str, Any]
    diagnostics: list[DiagnosticEvent]


class ReportStats(BaseModel):
    completed_runs: int
    exports_this_week: int
    last_export: dict[str, Any] | None
