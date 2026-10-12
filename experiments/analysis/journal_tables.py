"""Extra tables for the journal version: per-class open-world F1 and training cost.

usage (from backend/): .venv\\Scripts\\python.exe ..\\experiments\\analysis\\journal_tables.py [--out DIR]
Writes perclass_<TAG>_paper.tex and cost_paper.tex next to the other paper tables.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_results import DATASET_NAMES, DISPLAY, ROOT, agg, load  # noqa: E402

TAGS = ("CIC17", "IDS18", "UNSW")
COMPARE = ("nova", "cbrs_replay", "guarded_selective", "static")


def tex_escape(s: str) -> str:
    return s.replace("&", r"\&").replace("_", r"\_").replace("%", r"\%")


def stream_counts(run_id: str) -> pd.DataFrame:
    """Flows per class in the stream and whether the class was unknown to the initial model."""
    df = pd.read_csv(ROOT / "experiments" / "results" / run_id / "predictions.csv.gz",
                     usecols=["window", "true_label", "is_novel_class"])
    first = df[df.window == df.groupby("true_label").window.transform("min")]
    return pd.DataFrame({"flows": df.true_label.value_counts(),
                         "new": first.groupby("true_label").is_novel_class.max().astype(bool)})


def perclass(data, tag: str, out: Path) -> None:
    g = data.get(f"{tag} main b0.10")
    if not g:
        return
    static_run = next(iter(g["static"].values()))["run_id"]
    counts = stream_counts(static_run)
    means = {v: pd.DataFrame([r["overall"]["per_class_f1_ow"] for r in g[v].values()]).mean() for v in COMPARE if v in g}
    rows = []
    for cls in counts.sort_values("flows", ascending=False).index:
        vals = [means[v].get(cls, np.nan) for v in COMPARE if v in means]
        best = np.nanmax(vals)
        cells = [("--" if np.isnan(x) else (rf"\textbf{{{x:.2f}}}" if abs(x - best) < 1e-9 else f"{x:.2f}")) for x in vals]
        rows.append(f"{tex_escape(cls)} & {int(counts.flows[cls]):,} & {'yes' if counts.new[cls] else 'no'} & "
                    + " & ".join(cells) + r" \\")
    (out / f"perclass_{tag}_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")


def cost(data, out: Path) -> None:
    methods = ["nova", "cbrs_replay", "continual_replay", "guarded_selective", "uncertainty_al", "netguard_ps",
               "insomnia", "periodic_retrain", "static"]
    rows = []
    for v in methods:
        cells = []
        for tag in TAGS:
            g = data.get(f"{tag} main b0.10", {})
            m = agg(g[v], "train_seconds_total")[0] if v in g else None
            cells.append("--" if m is None else f"{m / 60:.1f}")
        rows.append(f"{DISPLAY.get(v, v)} & " + " & ".join(cells) + r" \\")
    (out / "cost_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")


ABLATIONS = ["nova -guard", "nova -active query", "nova -recency weight", "nova -calibration store",
             "nova -balanced memory", "nova -propagation"]


def _cell(g, v, key, pct=False):
    if not g or v not in g:
        return "--"
    m = agg(g[v], key)[0]
    if m is None:
        return "--"
    return f"{100 * m:.1f}" if pct else f"{m:.3f}"


def ablation_all(data, out: Path) -> None:
    """Rows: full NOVA and each one-component ablation; columns: OW-F1 and FPR per dataset (with delta)."""
    rows = []
    for v in ["nova"] + ABLATIONS:
        cells = []
        for tag in TAGS:
            src = data.get(f"{tag} main b0.10") if v == "nova" else data.get(f"{tag} ablation b0.10")
            full = data.get(f"{tag} main b0.10", {}).get("nova")
            if src is None or v not in src or full is None:
                cells += ["--", "--"]
                continue
            m = agg(src[v], "macro_f1_ow")[0]
            base = agg(full, "macro_f1_ow")[0]
            cells.append(f"{m:.3f}" if v == "nova" else f"{m:.3f} ({100 * (m - base):+.1f})")
            cells.append(_cell(src, v, "detect_fpr", pct=True))
        name = r"\nova{} (full)" if v == "nova" else r"\quad $-$\," + v.split(" -", 1)[1]
        rows.append(f"{name} & " + " & ".join(cells) + r" \\")
    (out / "ablation_all_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")


def sensitivity(data, out: Path) -> None:
    """Label delay (0/1/3) and review-rate (strict/default/lenient) on CIC17 for NOVA and CBRS (and static)."""
    main = data.get("CIC17 main b0.10", {})
    delay = data.get("CIC17 delay b0.10", {})
    rows = []
    for m in ("nova", "cbrs_replay"):
        cells = []
        for k in (0, 1, 3):
            g, v = (main, m) if k == 1 else (delay, f"{m} delay {k}")
            cells += [_cell(g, v, "macro_f1_ow"), _cell(g, v, "aut_f1_ow"), _cell(g, v, "detect_fpr", pct=True)]
        rows.append(f"{DISPLAY.get(m, m)} & " + " & ".join(cells) + r" \\")
    (out / "delay_paper.tex").write_text("\n".join(rows) + "\n", encoding="utf-8")

    review = data.get("CIC17 review-rate b0.10", {})
    rows = []
    for m in ("nova", "cbrs_replay", "static"):
        for lvl in ("strict", "default", "lenient"):
            g, v = (main, m) if lvl == "default" else (review, f"{m} {lvl}")
            cells = [_cell(g, v, "macro_f1_ow"), _cell(g, v, "detect_recall"), _cell(g, v, "detect_fpr", pct=True),
                     _cell(g, v, "unknown_auroc")]
            label = DISPLAY.get(m, m) if lvl == "strict" else ""
            rows.append(f"{label} & {lvl} & " + " & ".join(cells) + r" \\")
        rows.append(r"\midrule")
    (out / "review_paper.tex").write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "experiments" / "paper"))
    a = ap.parse_args()
    data = load(ROOT / "data" / "sentinel.db")
    out = Path(a.out)
    for tag in TAGS:
        perclass(data, tag, out)
    cost(data, out)
    ablation_all(data, out)
    sensitivity(data, out)
    print("written to", out, "datasets:", [DATASET_NAMES[t] for t in TAGS])


if __name__ == "__main__":
    main()
