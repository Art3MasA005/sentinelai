"""Reading IDS CSVs: schema validation (chunked, before any run) and chronological loading."""

from __future__ import annotations

import csv
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from app.schemas.datasets import ColumnIssue, DatasetProfile, ValidationReport

_MISSING_TOKENS = {"", "nan", "na", "n/a", "null", "none", "-"}
_NON_ASCII = re.compile(r"[^\x20-\x7E]+")
_SPACES = re.compile(r"\s+")
CHUNK_ROWS = 100_000
INVALID_FRACTION = 0.01


def read_first_line(path: Path) -> list[str]:
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        return next(csv.reader(fh), [])


def _read_csv(path: Path, profile: DatasetProfile, **kw) -> pd.DataFrame | pd.io.parsers.TextFileReader:
    return pd.read_csv(
        path,
        header=0 if profile.has_header else None,
        names=None if profile.has_header else profile.column_names,
        encoding="utf-8",
        encoding_errors="replace",
        **kw,
    )


def _strip_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip() for c in df.columns]
    return df


def normalize_labels(series: pd.Series, profile: DatasetProfile) -> pd.Series:
    s = series.astype("string").str.strip()
    if profile.label_fill is not None:
        s = s.mask(s.isna() | (s == ""), profile.label_fill)
    s = s.str.replace(_NON_ASCII, "-", regex=True).str.replace(_SPACES, " ", regex=True).str.strip()
    if profile.label_map:
        s = s.replace(profile.label_map)
    return s.mask(s == "")


def parse_timestamps(series: pd.Series, profile: DatasetProfile) -> np.ndarray:
    """Return float64 epoch seconds; NaN where unparseable."""
    if profile.timestamp_unit:
        out = pd.to_numeric(series, errors="coerce").astype("float64").to_numpy()
        return out / 1000.0 if profile.timestamp_unit == "ms" else out
    raw = series.astype("string").str.strip()
    dt = pd.to_datetime(raw, dayfirst=profile.timestamp_dayfirst, errors="coerce")
    failed = dt.isna() & raw.notna() & (raw != "")
    if failed.any():
        dt[failed] = pd.to_datetime(raw[failed], dayfirst=profile.timestamp_dayfirst, errors="coerce", format="mixed")
    if getattr(dt.dt, "tz", None) is not None:
        dt = dt.dt.tz_convert(None)
    if profile.timestamp_pm_before_hour:
        dt = dt.mask(dt.dt.hour < profile.timestamp_pm_before_hour, dt + pd.Timedelta(hours=12))
    return ((dt - pd.Timestamp("1970-01-01")) / pd.Timedelta(seconds=1)).astype("float64").to_numpy()


def feature_columns(columns: list[str], profile: DatasetProfile) -> tuple[list[str], list[str]]:
    """Split usable columns into (numeric, categorical) model features."""
    excluded = set(profile.drop_columns) | {profile.timestamp_column, profile.label_column}
    cats = [c for c in columns if c in set(profile.categorical_columns) and c not in excluded]
    nums = [c for c in columns if c not in excluded and c not in set(cats)]
    return nums, cats


def file_fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        st = f.stat()
        h.update(f"{f.name}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()


def files_sha256(files: list[Path]) -> str:
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
    return h.hexdigest()


def _epoch_to_dt(x: float | None) -> datetime | None:
    if x is None or not np.isfinite(x):
        return None
    return datetime.fromtimestamp(float(x), tz=timezone.utc)


@dataclass
class _ColStats:
    non_numeric: int = 0
    missing: int = 0
    inf: int = 0
    lo: float = np.inf
    hi: float = -np.inf
    examples: list[str] = field(default_factory=list)


def validate_files(
    dataset_id: str, files: list[Path], profile: DatasetProfile, is_demo: bool
) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    rows = 0
    columns: list[str] = []
    missing: list[str] = []
    numeric: list[str] = []
    cats: list[str] = []
    stats: dict[str, _ColStats] = {}
    labels: Counter[str] = Counter()
    ts_fail = 0
    ts_min, ts_max = np.inf, -np.inf
    backwards = pairs = 0
    blank_rows = 0

    for path in files:
        first_chunk = True
        prev_ts = np.nan
        for chunk in _read_csv(path, profile, dtype=str, chunksize=CHUNK_ROWS, keep_default_na=False):
            chunk = _strip_columns(chunk)
            if first_chunk and not columns:
                columns = list(chunk.columns)
                needed = dict.fromkeys([profile.timestamp_column, profile.label_column, *profile.required_columns])
                missing = [c for c in needed if c not in columns]
                numeric, cats = feature_columns(columns, profile)
                stats = {c: _ColStats() for c in numeric}
            elif first_chunk and list(chunk.columns) != columns:
                # Files may differ in identifier columns the profile drops anyway (CSE-CIC-IDS2018's Tuesday
                # file adds Flow ID / Src IP / Src Port / Dst IP); only the columns a run uses must match.
                n2, c2 = feature_columns(list(chunk.columns), profile)
                core = {profile.timestamp_column, profile.label_column}
                if set(n2) | set(c2) | (core & set(chunk.columns)) == set(numeric) | set(cats) | (core & set(columns)):
                    extra = sorted(set(chunk.columns) ^ set(columns))
                    warnings.append(f"{path.name}: differs from {files[0].name} only in ignored columns {extra}.")
                else:
                    errors.append(f"{path.name}: columns differ from {files[0].name}.")
            first_chunk = False
            blank = chunk.apply(lambda s: s.str.strip() == "").all(axis=1)
            if blank.any():
                blank_rows += int(blank.sum())
                chunk = chunk[~blank]
            rows += len(chunk)

            for c in numeric:
                if c not in chunk.columns:
                    continue
                raw = chunk[c].str.strip()
                is_missing = raw.str.lower().isin(_MISSING_TOKENS)
                num = pd.to_numeric(raw.mask(is_missing), errors="coerce")
                bad = num.isna() & ~is_missing
                st = stats[c]
                st.missing += int(is_missing.sum())
                st.non_numeric += int(bad.sum())
                if bad.any() and len(st.examples) < 3:
                    st.examples = list(dict.fromkeys(st.examples + raw[bad].head(3).tolist()))[:3]
                vals = num.to_numpy(dtype="float64")
                inf = np.isinf(vals)
                st.inf += int(inf.sum())
                finite = vals[np.isfinite(vals)]
                if finite.size:
                    st.lo, st.hi = min(st.lo, finite.min()), max(st.hi, finite.max())

            if profile.timestamp_column in chunk.columns:
                raw_ts = chunk[profile.timestamp_column]
                ts = parse_timestamps(raw_ts, profile)
                ts_fail += int(np.isnan(ts).sum())
                ok = ts[~np.isnan(ts)]
                if ok.size:
                    ts_min, ts_max = min(ts_min, ok.min()), max(ts_max, ok.max())
                    seq = np.concatenate([[prev_ts], ok]) if np.isfinite(prev_ts) else ok
                    if seq.size > 1:
                        backwards += int((np.diff(seq) < 0).sum())
                        pairs += seq.size - 1
                    prev_ts = ok[-1]

            if profile.label_column in chunk.columns:
                labels.update(normalize_labels(chunk[profile.label_column], profile).fillna("<missing>").tolist())

    invalid: list[ColumnIssue] = []
    col_warn: list[ColumnIssue] = []
    for c, st in stats.items():
        n = max(rows, 1)
        if st.non_numeric:
            issue = ColumnIssue(column=c, issue="non_numeric", count=st.non_numeric,
                                fraction=st.non_numeric / n, examples=st.examples)
            (invalid if st.non_numeric / n > INVALID_FRACTION else col_warn).append(issue)
        if st.missing / n > 0.5:
            col_warn.append(ColumnIssue(column=c, issue="high_missing", count=st.missing, fraction=st.missing / n))
        if st.inf:
            col_warn.append(ColumnIssue(column=c, issue="infinite", count=st.inf, fraction=st.inf / n))
        if not np.isfinite(st.lo) or st.lo == st.hi:
            col_warn.append(ColumnIssue(column=c, issue="constant", count=rows, fraction=1.0))

    if rows == 0:
        errors.append("Dataset has no rows.")
    if missing:
        errors.append(f"Missing required columns: {', '.join(missing)}.")
        if profile.name == "cicids2017" and profile.timestamp_column in missing:
            errors.append("Looks like the MachineLearningCVE variant; use the TrafficLabelling CSVs (they include Timestamp).")
    if invalid:
        errors.append(
            f"{len(invalid)} feature column(s) contain non-numeric values: {', '.join(i.column for i in invalid)}. "
            "Declare them as categorical or drop them in a custom profile."
        )
    if rows and ts_fail / rows > INVALID_FRACTION:
        errors.append(f"{ts_fail} rows ({ts_fail / rows:.1%}) have an unparseable timestamp.")
    elif ts_fail:
        warnings.append(f"{ts_fail} rows have an unparseable timestamp and will be skipped.")
    known_labels = [k for k in labels if k != "<missing>"]
    if profile.label_column not in missing and len(known_labels) < 2:
        errors.append("Need at least two distinct labels.")
    if labels.get("<missing>"):
        warnings.append(f"{labels['<missing>']} rows have no label and will be skipped.")
    if not any(b in labels for b in profile.benign_labels) and labels:
        warnings.append(f"No benign label found (expected one of {profile.benign_labels}); FPR will be undefined.")
    out_of_order = backwards / pairs if pairs else 0.0
    if out_of_order > 0.001:
        hint = " Rows will be stably sorted by timestamp." if profile.order_by == "timestamp" else ""
        warnings.append(f"{out_of_order:.2%} of consecutive rows go backwards in time within files.{hint}")
    if blank_rows:
        warnings.append(f"{blank_rows} completely empty rows were found and will be ignored.")
    if is_demo:
        warnings.append("DEMO dataset: synthetic flows, results must not be reported as real-traffic results.")

    return ValidationReport(
        dataset_id=dataset_id,
        profile=profile.name,
        valid=not errors,
        data_origin="demo" if is_demo else "replayed",
        is_demo=is_demo,
        rows=rows,
        columns=columns,
        feature_columns=numeric + cats,
        missing_columns=missing,
        invalid_columns=invalid,
        column_warnings=col_warn,
        timestamp_parse_failures=ts_fail,
        timestamp_min=_epoch_to_dt(ts_min if np.isfinite(ts_min) else None),
        timestamp_max=_epoch_to_dt(ts_max if np.isfinite(ts_max) else None),
        out_of_order_fraction=out_of_order,
        label_distribution=dict(labels.most_common()),
        nan_cells=sum(s.missing for s in stats.values()),
        inf_cells=sum(s.inf for s in stats.values()),
        blank_rows=blank_rows,
        sha256=files_sha256(files),
        fingerprint=file_fingerprint(files),
        errors=errors,
        warnings=warnings,
        validated_at=datetime.now(timezone.utc),
    )


@dataclass
class LoadedDataset:
    frame: pd.DataFrame          # feature columns only, chronological order
    timestamps: np.ndarray       # float64 epoch seconds
    labels: np.ndarray           # str
    row_index: np.ndarray        # global row number in the source files (provenance)
    numeric_columns: list[str]
    categorical_columns: list[str]
    skipped_rows: int
    context: pd.DataFrame | None = None  # src / dst / protocol strings for display


_IANA_PROTOCOLS = {"6": "TCP", "17": "UDP", "1": "ICMP", "0": "HOPOPT"}


def _context(df: pd.DataFrame, profile: DatasetProfile) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(df)))
    for key, col in (("src", profile.source_column), ("dst", profile.destination_column),
                     ("protocol", profile.protocol_column)):
        if col and col in df.columns:
            vals = df[col].astype("string").str.strip().fillna("").to_numpy()
            if key == "protocol":
                vals = [_IANA_PROTOCOLS.get(str(v).split(".")[0], str(v).upper()) for v in vals]
            out[key] = vals
        else:
            out[key] = ""
    return out


def count_rows(files: list[Path], profile: DatasetProfile) -> int:
    """Fast line count (minus headers); an upper bound when files contain blank lines."""
    total = 0
    for path in files:
        with open(path, "rb") as fh:
            total += sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 22), b""))
        total -= 1 if profile.has_header else 0
    return max(total, 0)


def load_dataset(files: list[Path], profile: DatasetProfile, max_rows: int | None = None) -> LoadedDataset:
    """Read in chunks, keep only the columns the run needs, and store numbers as float32.

    With `max_rows`, every k-th row is kept while reading (k = rows // max_rows) so multi-GB datasets fit
    in memory; the exact evenly spaced thinning to `max_rows` happens after the chronological sort.
    """
    stride = max(1, count_rows(files, profile) // max_rows) if max_rows else 1
    context_cols = {c for c in (profile.source_column, profile.destination_column, profile.protocol_column) if c}
    frames = []
    offset = 0
    keep_cols: list[str] | None = None
    numeric: list[str] = []
    for path in files:
        for chunk in _read_csv(path, profile, low_memory=False, chunksize=CHUNK_ROWS):
            chunk = _strip_columns(chunk)
            chunk.index = pd.RangeIndex(offset, offset + len(chunk))
            offset += len(chunk)
            if keep_cols is None:
                numeric, cats = feature_columns(list(chunk.columns), profile)
                wanted = {*numeric, *cats, profile.timestamp_column, profile.label_column, *context_cols}
                keep_cols = [c for c in chunk.columns if c in wanted]
            if stride > 1:
                chunk = chunk[chunk.index % stride == 0]
            chunk = chunk[[c for c in keep_cols if c in chunk.columns]]
            for c in numeric:
                if c in chunk.columns:
                    chunk[c] = pd.to_numeric(chunk[c], errors="coerce").astype("float32")
            frames.append(chunk)
    df = pd.concat(frames) if len(frames) > 1 else frames[0]

    ts = parse_timestamps(df[profile.timestamp_column], profile)
    labels = normalize_labels(df[profile.label_column], profile)
    # Blank rows give NA labels; fill before comparing so the mask stays a plain boolean array.
    keep = ~np.isnan(ts) & (labels.fillna("") != "").to_numpy(dtype=bool)
    skipped = int((~keep).sum())
    df, ts, labels = df[keep], ts[keep], labels[keep].to_numpy(dtype=str)
    rows = df.index.to_numpy()

    if profile.order_by == "timestamp":
        order = np.lexsort((rows, ts))  # stable: ties keep file order
        df, ts, labels, rows = df.iloc[order], ts[order], labels[order], rows[order]

    if max_rows and len(df) > max_rows:
        pick = np.unique(np.linspace(0, len(df) - 1, max_rows).astype(np.int64))
        df, ts, labels, rows = df.iloc[pick], ts[pick], labels[pick], rows[pick]

    numeric, cats = feature_columns(list(df.columns), profile)
    feats = df[numeric + cats].copy()
    for c in numeric:
        feats[c] = pd.to_numeric(feats[c], errors="coerce").astype("float32")
    for c in cats:
        feats[c] = feats[c].astype("string").str.strip().fillna("<missing>")
    feats = feats.reset_index(drop=True)
    return LoadedDataset(feats, ts, labels, rows, numeric, cats, skipped, _context(df, profile))
