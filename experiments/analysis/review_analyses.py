"""Analyses added after an internal review of the draft (no new runs needed):

1. Guard statistics for NOVA: proposals, deployments, rejections by reason, rollbacks, hold-out size, and how
   many rejected candidates had learned classes the deployed model did not know.
2. Open-world metric decomposition from the per-flow predictions: known-class macro-F1, false rejection of
   known flows, unknown recall / precision, and identification of known attack flows.
3. Moving-block bootstrap confidence intervals for the per-window OW-F1 difference between NOVA and each method
   (windows are autocorrelated, so a plain paired test overstates certainty), and the same for each one-component
   ablation against full NOVA on the same seeds.

usage (from backend/): .venv\\Scripts\\python.exe ..\\experiments\\analysis\\review_analyses.py [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_results import DATASET_NAMES, DISPLAY, ROOT  # noqa: E402

TAGS = ("CIC17", "IDS18", "UNSW")
BENIGN = {"BENIGN", "Benign", "Normal"}
METHODS = ["nova", "cbrs_replay", "continual_replay", "guarded_selective", "uncertainty_al", "netguard_ps",
           "insomnia", "periodic_retrain", "static"]


def runs_like(db, pattern: str) -> list[tuple[str, str]]:
    return db.execute("select run_id, name from runs where status='completed' and name like ? order by name",
                      (pattern,)).fetchall()


# ---------------------------------------------------------------- 1. guard statistics
def guard_stats(db, group: str) -> dict:
    out = defaultdict(list)
    for run_id, _ in runs_like(db, f"{group} · nova · seed %"):
        classes = {v: set(json.loads(c)) for v, c in
                   db.execute("select version, classes_json from model_versions where run_id=?", (run_id,))}
        ev = db.execute("select decision, reason, from_version, to_version, validation_json from adaptation_events "
                        "where run_id=?", (run_id,)).fetchall()
        prop = sum(d == "proposed" for d, *_ in ev)
        acc = [e for e in ev if e[0] == "accepted"]
        rej = [e for e in ev if e[0] == "rejected"]
        rb = [e for e in ev if e[0] == "rollback"]
        val = [json.loads(e[4]) for e in acc + rej]
        by_gain = sum(1 for v in (json.loads(e[4]) for e in rej) if v.get("gain", 0) < 0)
        by_forget = sum(1 for v in (json.loads(e[4]) for e in rej) if v.get("forgetting", 0) > 0.05)
        new_cls = sum(1 for e in rej if classes.get(e[3], set()) - classes.get(e[2], set()))
        out["proposed"].append(prop)
        out["accepted"].append(len(acc))
        out["rejected"].append(len(rej))
        out["rejected_gain"].append(by_gain)
        out["rejected_forgetting"].append(by_forget)
        out["rejected_with_new_class"].append(new_cls)
        out["rollbacks"].append(len(rb))
        hold = [v["holdout_rows"] for v in val if "holdout_rows" in v]
        out["holdout_median"].append(float(np.median(hold)) if hold else np.nan)
        out["holdout_min"].append(float(np.min(hold)) if hold else np.nan)
    return {k: float(np.mean(v)) for k, v in out.items()} | {"n": len(out["proposed"])}


# ---------------------------------------------------------------- 2. metric decomposition
def _macro_f1(t: np.ndarray, p: np.ndarray) -> float:
    f = []
    for c in np.unique(t):
        tp = np.sum((t == c) & (p == c))
        fp = np.sum((t != c) & (p == c))
        fn = np.sum((t == c) & (p != c))
        f.append(2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 0.0)
    return float(np.mean(f)) if f else float("nan")


def decompose(run_id: str) -> dict:
    df = pd.read_csv(ROOT / "experiments" / "results" / run_id / "predictions.csv.gz",
                     usecols=["true_label", "decision", "is_novel_class"])
    t, p = df.true_label.to_numpy(str), df.decision.to_numpy(str)
    novel = df.is_novel_class.to_numpy(int) == 1
    unk = p == "UNKNOWN"
    known = ~novel
    known_attack = known & ~np.isin(t, list(BENIGN))
    return {
        "known_macro_f1": _macro_f1(t[known], p[known]),
        "known_false_reject": float(unk[known].mean()) if known.any() else np.nan,
        "unknown_recall": float(unk[novel].mean()) if novel.any() else np.nan,
        "unknown_precision": float(novel[unk].mean()) if unk.any() else np.nan,
        "known_attack_identified": float((p[known_attack] == t[known_attack]).mean()) if known_attack.any() else np.nan,
        "novel_share": float(novel.mean()),
    }


def decomposition(db, group: str) -> dict[str, dict]:
    res = {}
    for m in METHODS:
        rows = [decompose(rid) for rid, _ in runs_like(db, f"{group} · {m} · seed %")]
        if rows:
            res[m] = {k: float(np.nanmean([r[k] for r in rows])) for k in rows[0]}
    return res


# ---------------------------------------------------------------- 3. block bootstrap
def block_bootstrap(d: np.ndarray, block: int = 5, n_boot: int = 10000, seed: int = 0) -> tuple[float, float, float]:
    d = d[np.isfinite(d)]
    n = len(d)
    rng = np.random.default_rng(seed)
    starts = np.arange(n - block + 1)
    k = int(np.ceil(n / block))
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = (rng.choice(starts, k)[:, None] + np.arange(block)[None, :]).ravel()[:n]
        means[b] = d[idx].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(d.mean()), float(lo), float(hi)


def window_series(db, run_id: str, key: str) -> np.ndarray:
    rows = db.execute("select metrics_json from windows where run_id=? order by window", (run_id,)).fetchall()
    return np.array([json.loads(m).get(key, np.nan) for (m,) in rows], dtype=float)


def bootstrap_table(db, budget: str = "b0.10", key: str = "macro_f1_ow") -> dict[str, dict]:
    """Per-window difference NOVA - method (seed-averaged series), moving-block bootstrap CI."""
    res = {}
    for tag in TAGS:
        group = f"{tag} main {budget}"
        nova = [window_series(db, rid, key) for rid, _ in runs_like(db, f"{group} · nova · seed %")]
        if not nova:
            continue
        ref = np.nanmean(np.vstack(nova), axis=0)
        res[tag] = {}
        for m in METHODS[1:]:
            other = [window_series(db, rid, key) for rid, _ in runs_like(db, f"{group} · {m} · seed %")]
            if not other:
                continue
            o = np.nanmean(np.vstack(other), axis=0)
            n = min(len(ref), len(o))
            res[tag][m] = block_bootstrap(ref[:n] - o[:n])
    return res


ABLATIONS = ["guard", "active query", "recency weight", "calibration store", "balanced memory", "propagation"]


def ablation_bootstrap(db, key: str = "macro_f1_ow") -> dict[str, dict]:
    """Per-window difference ablated NOVA - full NOVA, both averaged over the ablation's seeds (full NOVA from the
    main comparison, restricted to those seeds); moving-block bootstrap CI. Negative = the component helps."""
    def by_seed(pattern):
        return {int(n.rsplit("seed ", 1)[1]): rid for rid, n in runs_like(db, pattern)}

    res = {}
    for tag in TAGS:
        full = by_seed(f"{tag} main b0.10 · nova · seed %")
        res[tag] = {}
        for a in ABLATIONS:
            abl = by_seed(f"{tag} ablation b0.10 · nova -{a} · seed %")
            seeds = sorted(set(abl) & set(full))
            if not seeds:
                continue
            f = np.nanmean(np.vstack([window_series(db, full[s], key) for s in seeds]), axis=0)
            o = np.nanmean(np.vstack([window_series(db, abl[s], key) for s in seeds]), axis=0)
            n = min(len(f), len(o))
            res[tag][a] = block_bootstrap(o[:n] - f[:n])
    return res


def ablation_bootstrap_rows(bt: dict) -> str:
    lines = []
    for a in ABLATIONS:
        cells = []
        for tag in TAGS:
            v = bt.get(tag, {}).get(a)
            cells.append("--" if v is None else f"{100 * v[0]:+.1f} [{100 * v[1]:+.1f}, {100 * v[2]:+.1f}]")
        lines.append(rf"\quad $-$\,{a} & " + " & ".join(cells) + r" \\")
    return "\n".join(lines) + "\n"


def bootstrap_rows(bt: dict, pct_scale: float = 100.0) -> str:
    lines = []
    for m in METHODS[1:]:
        cells = []
        for tag in TAGS:
            v = bt.get(tag, {}).get(m)
            cells.append("--" if v is None else
                         f"{pct_scale * v[0]:+.1f} [{pct_scale * v[1]:+.1f}, {pct_scale * v[2]:+.1f}]")
        if any(c != "--" for c in cells):
            lines.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + r" \\")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "experiments" / "paper"))
    a = ap.parse_args()
    out = Path(a.out)
    db = sqlite3.connect(f"file:{ROOT / 'data' / 'sentinel.db'}?mode=ro", uri=True)
    report = {}

    # 1. guard
    rows = []
    for tag in TAGS:
        for budget in ("b0.10", "b0.01"):
            s = guard_stats(db, f"{tag} main {budget}")
            if not s["n"]:
                continue
            report[f"guard {tag} {budget}"] = s
            rows.append(f"{DATASET_NAMES[tag]} & {budget[1:].replace('0.10', '10').replace('0.01', '1')}\\% & "
                        f"{s['proposed']:.1f} & {s['accepted']:.1f} & {s['rejected']:.1f} & "
                        f"{s['rejected_gain']:.1f} & {s['rejected_forgetting']:.1f} & "
                        f"{s['rejected_with_new_class']:.1f} & {s['rollbacks']:.1f} & "
                        f"{s['holdout_median']:.0f} ({s['holdout_min']:.0f}) \\\\")
    (out / "guard_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # 2. decomposition
    for tag in TAGS:
        for budget in ("b0.10",) + (("b0.01",) if tag == "UNSW" else ()):
            dec = decomposition(db, f"{tag} main {budget}")
            report[f"decomposition {tag} {budget}"] = dec
            lines = []
            for m, r in dec.items():
                lines.append(f"{DISPLAY.get(m, m)} & {r['known_macro_f1']:.3f} & {100 * r['known_false_reject']:.1f} & "
                             f"{r['known_attack_identified']:.3f} & {r['unknown_recall']:.3f} & "
                             f"{r['unknown_precision']:.3f} \\\\")
            text = "\n".join(lines).replace(" nan ", " -- ").replace("& nan", "& --")
            (out / f"owparts_{tag}_{budget.replace('.', '')}_paper.tex").write_text(text + "\n", encoding="utf-8")
            print(f"decomposition {tag} {budget} done", flush=True)

    # 3. bootstrap: OW-F1 at both budgets, FPR at 10% (FPR difference: negative = NOVA flags fewer benign flows)
    for name, budget, key in (("bootstrap", "b0.10", "macro_f1_ow"), ("bootstrap_b001", "b0.01", "macro_f1_ow"),
                              ("bootstrap_fpr", "b0.10", "detect_fpr")):
        bt = bootstrap_table(db, budget, key)
        report[name] = bt
        (out / f"{name}_paper.tex").write_text(bootstrap_rows(bt), encoding="utf-8")
    for name, key in (("bootstrap_ablation", "macro_f1_ow"), ("bootstrap_ablation_fpr", "detect_fpr")):
        bt = ablation_bootstrap(db, key)
        report[name] = bt
        (out / f"{name}_paper.tex").write_text(ablation_bootstrap_rows(bt), encoding="utf-8")

    (out / "review_analyses.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k.startswith("guard")}, indent=1))
    print("written to", out)


if __name__ == "__main__":
    main()
