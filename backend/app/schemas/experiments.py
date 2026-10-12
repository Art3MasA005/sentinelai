from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import DataOrigin
from app.schemas.datasets import DatasetProfile

ModelKind = Literal["hist_gb", "random_forest", "lightgbm", "xgboost", "logreg", "mlp"]
AdaptationMethod = Literal[
    "static", "periodic_retrain", "continual_replay", "guarded_selective",
    # Re-implementations of published approaches under this protocol (see docs/LITERATURE.md).
    "uncertainty_al", "insomnia", "netguard_ps", "cbrs_replay",
    # Proposed method.
    "nova",
]
DriftMethod = Literal["ks", "psi", "confidence"]
RunStatus = Literal["created", "queued", "running", "paused", "completed", "failed", "cancelled"]


class ModelConfig(BaseModel):
    kind: ModelKind = "hist_gb"
    params: dict[str, Any] = Field(default_factory=dict)
    class_weight: Literal["balanced"] | None = None
    # Classes with fewer labelled samples than this are left out of training (they stay UNKNOWN).
    min_class_samples: int = Field(5, ge=1)


class SplitConfig(BaseModel):
    """Chronological split. The first `train_fraction` of the timeline is the training period;
    its last `val_fraction` is held out as the reference validation set. The rest is the stream."""

    train_fraction: float = Field(0.3, gt=0, lt=1)
    val_fraction: float = Field(0.2, gt=0, lt=1)
    window_size: int = Field(2000, ge=10)
    # Deterministic, order-preserving thinning of the whole timeline (None = use every row).
    max_rows: int | None = Field(None, ge=100)
    # Classes removed from the training period to simulate unseen (zero-day-like) traffic.
    holdout_classes: list[str] = Field(default_factory=list)


class OpenWorldConfig(BaseModel):
    method: Literal["none", "msp", "centroid", "msp+centroid", "knn", "msp+knn"] = "msp+centroid"
    # Flag as unknown when max class probability is below this quantile of validation confidence.
    msp_quantile: float = Field(0.02, ge=0, le=0.5)
    # Flag as unknown when the distance score exceeds this quantile of held-out known-class scores.
    distance_quantile: float = Field(0.99, ge=0.5, le=1)
    # knn: distance to the k-th nearest training flow of the predicted class (class-conditional).
    knn_k: int = Field(10, ge=1, le=200)
    knn_bank_per_class: int = Field(3000, ge=50, le=50000)


class DriftConfig(BaseModel):
    detectors: list[DriftMethod] = Field(default_factory=lambda: ["ks", "confidence"])
    ks_alpha: float = Field(0.01, gt=0, lt=1)
    ks_threshold: float = Field(0.3, gt=0, le=1)
    psi_threshold: float = Field(0.2, gt=0)
    confidence_threshold: float = Field(0.1, gt=0)
    cooldown_windows: int = Field(2, ge=0)
    reference_update: Literal["fixed", "on_adaptation"] = "on_adaptation"
    max_reference_rows: int = Field(5000, ge=100)


class LabelPolicy(BaseModel):
    """What ground truth adaptation is allowed to see. Evaluation labels are kept separately."""

    delay_windows: int = Field(1, ge=0)
    budget: float = Field(1.0, gt=0, le=1, description="Fraction of each revealed window that is labelled.")


class AdaptationConfig(BaseModel):
    method: AdaptationMethod = "static"
    retrain_every: int = Field(5, ge=1, description="periodic_retrain: windows between retrains.")
    memory_windows: int = Field(10, ge=1, description="Recent labelled windows kept for retraining.")
    buffer_size: int = Field(20000, ge=100, description="continual_replay / guarded_selective replay buffer.")
    # guarded_selective (reference placeholder for the proposed method) + ablation switches.
    trigger: Literal["drift", "drift_or_novelty"] = "drift_or_novelty"
    novelty_trigger_rate: float = Field(0.15, gt=0, le=1)
    # validation_guard=False is the "auto-accept" ablation; reference_guard toggles the forgetting check.
    validation_guard: bool = True
    reference_guard: bool = True
    min_gain: float = 0.0
    max_forgetting: float = Field(0.05, ge=0)
    rollback: bool = True
    rollback_margin: float = Field(0.05, ge=0)
    rollback_watch_windows: int = Field(2, ge=1)
    # Query-strategy baselines (uncertainty_al, netguard_ps) and nova choose WHICH flows of a window get
    # labelled; the number is still fixed by labels.budget, so label cost is identical across methods.
    # insomnia: share of each window pseudo-labelled by its nearest-centroid estimator (no oracle labels).
    insomnia_selection_rate: float = Field(0.5, gt=0, le=1)
    netguard_components: int = Field(8, ge=1, le=64)
    # nova (proposed) and its ablation switches.
    active_selection: bool = True
    random_fraction: float = Field(0.2, ge=0, le=1, description="Share of the label budget drawn uniformly.")
    select_clusters: int = Field(24, ge=1, le=256)
    propagate: bool = True
    propagate_k: int = Field(5, ge=1, le=50)
    propagate_max_ratio: float = Field(5.0, ge=0, description="Pseudo labels per true label, per class.")
    class_balanced_memory: bool = True
    benign_weight: float = Field(4.0, gt=0, description="Benign share of the class-balanced memory vs one class.")
    holdout_fraction: float = Field(0.25, ge=0, lt=1, description="Newest true labels held out for the guard.")
    calib_per_class: int = Field(200, ge=0, description="Held-out analyst labels kept per class (never trained "
                                                         "on) to calibrate open-world thresholds; 0 disables.")
    calib_min_train: int = Field(50, ge=0, description="A class feeds the calibration store only once the "
                                                       "training memory holds this many of its flows.")
    min_support: int = Field(5, ge=1, description="Guard/rollback compare models only on classes with at "
                                                  "least this many labels in the compared slice.")
    recent_weight: float = Field(2.0, ge=1, description="Training weight of the newest labels (1 = off).")


class ExperimentConfig(BaseModel):
    name: str = Field("untitled", max_length=120)
    dataset_id: str
    profile: str | None = None
    custom_profile: DatasetProfile | None = None
    seed: int = 42
    model: ModelConfig = Field(default_factory=ModelConfig)
    split: SplitConfig = Field(default_factory=SplitConfig)
    openworld: OpenWorldConfig = Field(default_factory=OpenWorldConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    labels: LabelPolicy = Field(default_factory=LabelPolicy)
    adaptation: AdaptationConfig = Field(default_factory=AdaptationConfig)
    store_features: bool = True
    # "db": every flow goes to the database (Alerts / Traffic pages can browse it; ~400 MB per 280k-flow run).
    # "file": flows go only to experiments/results/<run_id>/predictions.csv.gz; use for large experiment grids.
    flow_storage: Literal["db", "file"] = "db"
    notes: str = ""
    # When set, the policy's window size, open-world, drift, label and adaptation rules override this config.
    policy_version: int | None = None

    @model_validator(mode="after")
    def _check(self) -> "ExperimentConfig":
        if self.profile and self.custom_profile:
            raise ValueError("Give either `profile` or `custom_profile`, not both.")
        return self


class RunProgress(BaseModel):
    phase: str = "created"
    window: int = 0
    total_windows: int = 0
    flows_processed: int = 0


class ExperimentRun(BaseModel):
    run_id: str
    seq: int  # short sequential number for display (RUN-024)
    group_id: str | None = None  # runs created together by a multi-seed / multi-method batch
    name: str
    status: RunStatus
    method: AdaptationMethod
    dataset_id: str
    profile: str | None
    data_origin: DataOrigin | None
    dataset_sha256: str | None
    config_hash: str
    config: ExperimentConfig
    progress: RunProgress
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: dict[str, Any] | None = None


class ControlResponse(BaseModel):
    run_id: str
    status: RunStatus
    control: str
    message: str


class BatchCreate(BaseModel):
    """Create one run per (method, seed): the standard multi-seed baseline comparison."""

    base: ExperimentConfig
    methods: list[AdaptationMethod] | None = Field(None, description="Default: just base.adaptation.method")
    seeds: list[int] = Field(..., min_length=1, max_length=20)
    start: bool = True


class BatchResult(BaseModel):
    group_id: str
    runs: list["ExperimentRun"]


class ComparisonEntry(BaseModel):
    run_id: str
    name: str
    method: str
    status: RunStatus
    data_origin: DataOrigin | None
    metrics: dict[str, Any] | None


class AggregateEntry(BaseModel):
    method: str
    n: int
    seeds: list[int]
    run_ids: list[str]
    # metric -> {"mean", "std"} over seeds (sample std; 0 when n == 1)
    metrics: dict[str, dict[str, float]]


class Comparison(BaseModel):
    runs: list[ComparisonEntry]
    aggregates: list[AggregateEntry]
    fair: bool
    # Config keys that differ between runs and therefore make the comparison unfair.
    differences: dict[str, list[Any]]
    mixed_data_origin: bool
    definitions: dict[str, str]
