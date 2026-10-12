from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class FlowRecord(BaseModel):
    flow_id: int
    window: int
    row_index: int
    timestamp: datetime | None
    # Ground truth is shown for evaluation only; adaptation never reads it directly.
    true_label: str
    # Model's top class before open-world rejection.
    predicted_label: str
    # What SentinelAI reports: predicted_label, or "UNKNOWN" (= unfamiliar/uncertain, needs review,
    # NOT confirmed malicious).
    decision: str
    confidence: float
    attack_score: float | None
    novelty_score: float | None
    is_unknown: bool
    unknown_reason: str | None
    # True label was not among the classes known to the model that produced this prediction.
    is_novel_class: bool
    model_version: int
    src: str | None = None
    dst: str | None = None
    protocol: str | None = None


class FlowDetail(FlowRecord):
    probabilities: dict[str, float]
    features: dict[str, Any] | None


class DriftEvent(BaseModel):
    event_id: str
    window: int
    method: str
    score: float
    threshold: float
    window_start: datetime | None
    window_end: datetime | None
    detected_at: datetime
    details: dict[str, Any]


AdaptationDecision = Literal["proposed", "accepted", "rejected", "rollback"]


class AdaptationEvent(BaseModel):
    event_id: str
    window: int
    decision: AdaptationDecision
    reason: str
    trigger: str
    from_version: int
    to_version: int | None
    validation: dict[str, Any]
    cost: dict[str, Any]
    created_at: datetime


class ModelVersion(BaseModel):
    version: int
    parent_version: int | None
    created_window: int
    status: Literal["active", "candidate", "retired", "rejected", "rolled_back"]
    classes: list[str]
    train_rows: int
    train_seconds: float
    model_bytes: int
    created_at: datetime


class WindowMetrics(BaseModel):
    window: int
    start: datetime | None
    end: datetime | None
    n_flows: int
    model_version: int
    metrics: dict[str, Any]
    drift_scores: dict[str, dict[str, Any]]


class RunMetrics(BaseModel):
    run_id: str
    status: str
    data_origin: str | None
    overall: dict[str, Any] | None
    confusion_matrix: dict[str, Any] | None
    windows: list[WindowMetrics] | None
    definitions: dict[str, str]
    provenance: dict[str, Any]
