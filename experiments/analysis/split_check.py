"""Random vs chronological split with the same classifier and data (the protocol gap behind 99% NIDS results).

For each dataset we take the same 400k-flow sample the replay uses and train the same gradient-boosting
classifier on 30% of it:
  random        - a stratified random 30% (flows of one attack session land on both sides), test on the rest
  chronological - the first 30% in time, test on the rest; classes unseen in training cannot be predicted
Closed-world metrics only (no UNKNOWN), as in the papers that report 99%.

usage (from backend/): .venv\\Scripts\\python.exe ..\\experiments\\analysis\\split_check.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.ml.data import load_dataset  # noqa: E402
from app.ml.models import make_classifier  # noqa: E402
from app.ml.preprocessing import Preprocessor  # noqa: E402
from app.schemas.experiments import ModelConfig  # noqa: E402
from app.services import datasets as ds_service  # noqa: E402

DATASETS = [("CIC17", "CIC-IDS2017", "cicids2017"), ("IDS18", "CSE-CIC-IDS2018-k8", "cicids2018"),
            ("UNSW", "UNSW-NB15", "unswnb15")]
SEEDS = (1, 2, 3)


def fit_eval(frame, labels, tr, te, seed, numeric, categorical):
    pre = Preprocessor(numeric, categorical).fit(frame.iloc[tr])
    clf = make_classifier(ModelConfig(kind="hist_gb"), seed)
    clf.fit(pre.transform(frame.iloc[tr]), labels[tr])
    pred = clf.predict_proba(pre.transform(frame.iloc[te])).argmax(1)
    pred = np.asarray(clf.classes_)[pred]
    y = labels[te]
    return {"macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
            "weighted_f1": float(f1_score(y, pred, average="weighted", zero_division=0)),
            "accuracy": float(accuracy_score(y, pred)),
            "test_classes_unseen_in_training": int(len(set(y) - set(labels[tr])))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "experiments" / "paper"))
    a = ap.parse_args()
    settings = get_settings()
    results = {}
    for tag, dataset_id, profile_name in DATASETS:
        ds = ds_service.resolve(settings.datasets_dir, dataset_id)
        data = load_dataset(ds.files, ds_service.pick_profile(ds, profile_name, None), 400_000)
        labels = data.labels.astype(str)
        n = len(labels)
        n_train = int(n * 0.3)
        args = (data.frame, labels)
        cols = (data.numeric_columns, data.categorical_columns)
        chrono = fit_eval(*args, np.arange(n_train), np.arange(n_train, n), 1, *cols)
        rand = []
        for seed in SEEDS:
            # classes with a single flow cannot be stratified; they go to the test side
            cls, cnt = np.unique(labels, return_counts=True)
            ok = np.isin(labels, cls[cnt >= 2])
            idx = np.flatnonzero(ok)
            tr, te = train_test_split(idx, train_size=0.3, random_state=seed, stratify=labels[idx])
            te = np.concatenate([te, np.flatnonzero(~ok)])
            rand.append(fit_eval(*args, tr, te, seed, *cols))
        results[tag] = {"chronological": chrono,
                        "random": {k: float(np.mean([r[k] for r in rand])) for k in rand[0]},
                        "random_std": {k: float(np.std([r[k] for r in rand])) for k in rand[0]}}
        print(tag, json.dumps(results[tag]), flush=True)
    out = Path(a.out)
    (out / "split_check.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    rows = []
    for tag, r in results.items():
        name = {"CIC17": "CIC-IDS2017", "IDS18": "CSE-CIC-IDS2018", "UNSW": "UNSW-NB15"}[tag]
        rows.append(f"{name} & {r['random']['accuracy']:.3f} & {r['random']['macro_f1']:.3f} & "
                    f"{r['chronological']['accuracy']:.3f} & {r['chronological']['macro_f1']:.3f} & "
                    f"{r['chronological']['test_classes_unseen_in_training']} \\\\")
    (out / "split_check_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("written to", out)


if __name__ == "__main__":
    main()
