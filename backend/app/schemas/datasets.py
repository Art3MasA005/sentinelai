from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import DataOrigin


class DatasetProfile(BaseModel):
    """Describes how to read one IDS CSV schema. Built-ins live in app/ml/profiles.py."""

    name: str
    description: str = ""
    timestamp_column: str
    label_column: str
    benign_labels: list[str] = Field(default_factory=lambda: ["BENIGN"])
    # Columns that are never model features (identifiers, IPs, time, labels).
    drop_columns: list[str] = Field(default_factory=list)
    categorical_columns: list[str] = Field(default_factory=list)
    # Columns that must exist for the dataset to be usable with this profile.
    required_columns: list[str] = Field(default_factory=list)
    has_header: bool = True
    # Used when has_header is False.
    column_names: list[str] | None = None
    # None -> parse as datetime string; "s"/"ms" -> numeric epoch.
    timestamp_unit: Literal["s", "ms"] | None = None
    timestamp_dayfirst: bool = False
    # Clock times written without AM/PM (CIC-IDS2017): hours below this value are afternoon, +12 h.
    timestamp_pm_before_hour: int | None = Field(None, ge=1, le=12)
    # Value used when the label cell is empty (e.g. UNSW-NB15 attack_cat).
    label_fill: str | None = None
    label_map: dict[str, str] = Field(default_factory=dict)
    # Display-only context (never features): shown in the flow explorer.
    source_column: str | None = None
    destination_column: str | None = None
    protocol_column: str | None = None
    # "timestamp": stable sort by timestamp. "file_order": trust row order in the files.
    order_by: Literal["timestamp", "file_order"] = "timestamp"


class ValidationSummary(BaseModel):
    profile: str
    valid: bool
    rows: int
    validated_at: datetime


class DatasetInfo(BaseModel):
    id: str
    name: str
    path: str
    files: list[str]
    size_bytes: int
    data_origin: DataOrigin
    is_demo: bool
    detected_profile: str | None
    last_validation: ValidationSummary | None = None


class ValidateRequest(BaseModel):
    dataset_id: str
    profile: str | None = Field(None, description="Built-in profile name; auto-detected when omitted.")
    custom_profile: DatasetProfile | None = Field(None, description="Overrides `profile` when given.")


class ColumnIssue(BaseModel):
    column: str
    issue: Literal["non_numeric", "high_missing", "constant", "infinite"]
    count: int
    fraction: float
    examples: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    dataset_id: str
    profile: str
    valid: bool
    data_origin: DataOrigin
    is_demo: bool
    rows: int
    columns: list[str]
    feature_columns: list[str]
    missing_columns: list[str]
    invalid_columns: list[ColumnIssue]
    column_warnings: list[ColumnIssue]
    timestamp_parse_failures: int
    timestamp_min: datetime | None
    timestamp_max: datetime | None
    # Fraction of consecutive row pairs whose timestamp goes backwards in file order.
    out_of_order_fraction: float
    label_distribution: dict[str, int]
    nan_cells: int
    inf_cells: int
    blank_rows: int = 0  # rows whose every cell is empty (ignored)
    sha256: str
    fingerprint: str
    errors: list[str]
    warnings: list[str]
    validated_at: datetime
