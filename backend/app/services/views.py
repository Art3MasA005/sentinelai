"""DB row -> API schema conversion."""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.events import (AdaptationEvent, DriftEvent, FlowDetail, FlowRecord, ModelVersion,
                                WindowMetrics)
from app.storage.db import loads


def ts(x: float | None) -> datetime | None:
    return None if x is None else datetime.fromtimestamp(x, tz=timezone.utc)


def flow(r: dict) -> FlowRecord:
    return FlowRecord(
        flow_id=r["flow_id"], window=r["window"], row_index=r["row_index"], timestamp=ts(r["ts"]),
        true_label=r["true_label"], predicted_label=r["predicted_label"], decision=r["decision"],
        confidence=r["confidence"], attack_score=r["attack_score"], novelty_score=r["novelty_score"],
        is_unknown=bool(r["is_unknown"]), unknown_reason=r["unknown_reason"],
        is_novel_class=bool(r["is_novel_class"]), model_version=r["model_version"],
        src=r.get("src"), dst=r.get("dst"), protocol=r.get("protocol"),
    )


def flow_detail(r: dict) -> FlowDetail:
    return FlowDetail(**flow(r).model_dump(), probabilities=loads(r["probabilities_json"]) or {},
                      features=loads(r["features_json"]))


def drift(r: dict) -> DriftEvent:
    return DriftEvent(event_id=r["event_id"], window=r["window"], method=r["method"], score=r["score"],
                      threshold=r["threshold"], window_start=ts(r["start_ts"]), window_end=ts(r["end_ts"]),
                      detected_at=r["detected_at"], details=r["details"])


def adaptation(r: dict) -> AdaptationEvent:
    return AdaptationEvent(event_id=r["event_id"], window=r["window"], decision=r["decision"], reason=r["reason"],
                           trigger=r["trigger"], from_version=r["from_version"], to_version=r["to_version"],
                           validation=r["validation"], cost=r["cost"], created_at=r["created_at"])


def model_version(r: dict) -> ModelVersion:
    return ModelVersion(version=r["version"], parent_version=r["parent_version"], created_window=r["created_window"],
                        status=r["status"], classes=r["classes"], train_rows=r["train_rows"],
                        train_seconds=r["train_seconds"], model_bytes=r["model_bytes"], created_at=r["created_at"])


def window(r: dict) -> WindowMetrics:
    return WindowMetrics(window=r["window"], start=ts(r["start_ts"]), end=ts(r["end_ts"]), n_flows=r["n_flows"],
                         model_version=r["model_version"], metrics=r["metrics"], drift_scores=r["drift"])
