"""Dataset audit for the paper: per-class counts in the source CSVs and in the replay sample, where each class first
appears, and duplicate rows.

For each dataset:
  source flows    - rows with a valid label in the published CSVs (label column only, same label normalisation)
  sample flows    - rows in the 400k evenly spaced replay sample
  training flows  - rows of the class in the fit part of the training period (after any hold-out)
  first window    - first stream window (0-69) containing the class; "train" if it occurs in the training period
  duplicates      - exact duplicate feature rows inside the sample, and stream rows identical to a training row

usage (from backend/): .venv\\Scripts\\python.exe ..\\experiments\\analysis\\dataset_audit.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.ml.data import _strip_columns, load_dataset, normalize_labels  # noqa: E402
from app.services import datasets as ds_service  # noqa: E402

DATASETS = [("CIC17", "CIC-IDS2017", "cicids2017", []), ("IDS18", "CSE-CIC-IDS2018-k8", "cicids2018", []),
            ("UNSW", "UNSW-NB15", "unswnb15", ["DoS", "Reconnaissance", "Shellcode", "Worms"])]
WINDOW, TRAIN_FRACTION, VAL_FRACTION, MAX_ROWS = 4000, 0.3, 0.2, 400_000


def source_counts(files, profile) -> pd.Series:
    counts = pd.Series(dtype="int64")
    for f in files:
        for enc in ("utf-8", "latin-1"):
            try:
                reader = pd.read_csv(f, chunksize=500_000, low_memory=False, encoding=enc, dtype=str)
                for chunk in reader:
                    chunk = _strip_columns(chunk)
                    if profile.label_column not in chunk:
                        continue
                    lab = normalize_labels(chunk[profile.label_column], profile).fillna("")
                    lab = lab[lab.str.strip() != ""]
                    counts = counts.add(lab.value_counts(), fill_value=0)
                break
            except UnicodeDecodeError:
                counts = pd.Series(dtype="int64") if enc == "utf-8" else counts
                continue
    return counts.astype(int)


def audit(tag, dataset_id, profile_name, holdout):
    settings = get_settings()
    ds = ds_service.resolve(settings.datasets_dir, dataset_id)
    profile = ds_service.pick_profile(ds, profile_name, None)
    src = source_counts(ds.files, profile)
    data = load_dataset(ds.files, profile, MAX_ROWS)
    labels = data.labels.astype(str)
    n = len(labels)
    n_train = int(n * TRAIN_FRACTION)
    fit_end = n_train - max(int(n_train * VAL_FRACTION), 1)
    fit = labels[:fit_end]
    if holdout:
        fit = fit[~np.isin(fit, holdout)]
    stream = labels[n_train:]
    rows = []
    for c in sorted(set(src.index) | set(labels), key=lambda c: -src.get(c, 0)):
        in_stream = np.flatnonzero(stream == c)
        rows.append({"class": c, "source": int(src.get(c, 0)), "sample": int((labels == c).sum()),
                     "training": int((fit == c).sum()),
                     "first_window": "train" if (fit == c).any() else
                     (int(in_stream[0] // WINDOW) if len(in_stream) else "--"),
                     "stream": int(len(in_stream))})
    feats = data.frame.reset_index(drop=True)
    dup_sample = int(feats.duplicated().sum())
    train_keys = set(pd.util.hash_pandas_object(feats.iloc[:n_train], index=False))
    stream_hash = pd.util.hash_pandas_object(feats.iloc[n_train:], index=False)
    dup_cross = int(stream_hash.isin(train_keys).sum())
    return {"classes": rows, "rows_sample": n, "skipped_rows": int(data.skipped_rows),
            "duplicate_rows_in_sample": dup_sample, "stream_rows_identical_to_a_training_row": dup_cross,
            "train_end_ts": float(data.timestamps[n_train - 1]), "stream_start_ts": float(data.timestamps[n_train])}


def tex_escape(s: str) -> str:
    return s.replace("&", r"\&").replace("_", r"\_").replace("%", r"\%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "experiments" / "paper"))
    out = Path(ap.parse_args().out)
    report = {}
    for tag, dataset_id, profile_name, holdout in DATASETS:
        r = audit(tag, dataset_id, profile_name, holdout)
        report[tag] = r
        lines = [f"{tex_escape(c['class'])} & {c['source']:,} & {c['sample']:,} & {c['training']:,} & "
                 f"{c['first_window']} & {c['stream']:,} \\\\" for c in r["classes"]]
        (out / f"audit_{tag}_paper.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(tag, {k: v for k, v in r.items() if k != "classes"}, flush=True)
    (out / "dataset_audit.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
