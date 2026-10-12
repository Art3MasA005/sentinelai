"""Paper tables and figures from completed SentinelAI runs.

usage (from backend/):  .venv/Scripts/python.exe ../experiments/analysis/paper_results.py [--db PATH] [--out DIR]

Run names follow "<group> · <variant> · seed <n>" (as created by batch runs / plan scripts). For every group the
script writes mean ± std over seeds to Markdown, CSV and LaTeX, plus:
- AUT(F1): area under the per-window open-world macro-F1 curve (TESSERACT, Pendlebury et al. 2019), normalised to [0,1];
- a paired Wilcoxon signed-rank test of NOVA against every other method on per-window macro_f1_ow averaged over seeds
  (windows are autocorrelated, so treat p-values as indicative);
- figures: macro_f1_ow over time, budget comparison, ablation bars.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
METRICS = [
    ("macro_f1_ow", "OW macro-F1", True),
    ("aut_f1_ow", "AUT(OW-F1)", True),
    ("attack_macro_recall_ow", "Attack macro-recall", True),
    ("detect_f1", "Detect F1", True),
    ("detect_recall", "Detect recall", True),
    ("detect_fpr", "Detect FPR", False),
    ("unknown_auroc", "Unknown AUROC", True),
    ("forgetting_max", "Max forgetting", False),
    ("labels_used", "Labels", False),
    ("train_seconds_total", "Train s", False),
]


def load(db_path: Path):
    db = sqlite3.connect(db_path)
    runs = db.execute("select run_id, name, summary_json from runs where status='completed'").fetchall()
    data = defaultdict(lambda: defaultdict(dict))  # group -> variant -> seed -> record
    for run_id, name, sj in runs:
        parts = [p.strip() for p in name.split("·")]
        if len(parts) < 3 or not parts[-1].startswith("seed"):
            continue
        group, variant, seed = " · ".join(parts[:-2]), parts[-2], int(parts[-1].split()[1])
        overall = json.loads(sj)["overall"]
        wins = db.execute("select window, metrics_json from windows where run_id=? order by window", (run_id,)).fetchall()
        series = np.array([json.loads(m).get("macro_f1_ow", np.nan) for _, m in wins], dtype=float)
        valid = series[np.isfinite(series)]
        overall["aut_f1_ow"] = float(np.trapezoid(valid) / (len(valid) - 1)) if len(valid) > 1 else None
        data[group][variant][seed] = {"overall": overall, "series": series, "run_id": run_id}
    return data


def agg(records: dict, key: str):
    v = [r["overall"].get(key) for r in records.values() if r["overall"].get(key) is not None]
    return (float(np.mean(v)), float(np.std(v)), len(v)) if v else (None, None, 0)


def fmt(m, s, key):
    if m is None:
        return "–"
    if key in ("labels_used", "train_seconds_total"):
        return f"{m:,.0f}"
    return f"{m:.3f} ± {s:.3f}"


def wilcoxon_vs(group: dict, ref: str = "nova") -> dict:
    from scipy.stats import wilcoxon

    if ref not in group:
        return {}
    ref_mean = np.nanmean(np.vstack([r["series"] for r in group[ref].values()]), axis=0)
    out = {}
    for variant, recs in group.items():
        if variant == ref:
            continue
        other = np.nanmean(np.vstack([r["series"] for r in recs.values()]), axis=0)
        n = min(len(ref_mean), len(other))
        d = ref_mean[:n] - other[:n]
        d = d[np.isfinite(d) & (d != 0)]
        out[variant] = float(wilcoxon(d).pvalue) if len(d) >= 10 else None
    return out


PAPER_COLS = [("macro_f1_ow", True), ("aut_f1_ow", True), ("detect_f1", True), ("detect_fpr", False),
              ("unknown_auroc", True), ("forgetting_max", False)]
DISPLAY = {"nova": r"\nova{} (ours)", "static": "Static", "periodic_retrain": "Periodic retrain",
           "continual_replay": "Continual replay", "guarded_selective": "Guarded selective",
           "uncertainty_al": "Uncertainty sampling", "insomnia": "INSOMNIA~\\cite{andresini2021insomnia}",
           "netguard_ps": "NetGuard PS~\\cite{gupta2025netguard}", "cbrs_replay": "CBRS replay~\\cite{chrysakis2020online}"}


def paper_rows(g: dict, order: list[str]) -> str:
    """Compact LaTeX rows for the paper: six metrics, best mean in bold, mean with std as a small subscript."""
    best = {}
    for key, higher in PAPER_COLS:
        means = {v: agg(g[v], key)[0] for v in g if agg(g[v], key)[0] is not None}
        if means:
            best[key] = (max if higher else min)(means.values())
    lines = []
    for v in order:
        cells = []
        for key, _ in PAPER_COLS:
            m, s, _n = agg(g[v], key)
            if m is None:
                cells.append("--")
                continue
            if key in ("detect_fpr",):
                txt, sd = f"{100 * m:.1f}", f"{100 * s:.1f}"
            else:
                txt, sd = f"{m:.3f}", f"{s:.3f}"
            if abs(m - best.get(key, float("nan"))) < 1e-12:
                txt = rf"\textbf{{{txt}}}"
            cells.append(rf"{txt}$_{{\pm{sd}}}$")
        name = DISPLAY.get(v, v.replace("nova ", r"\nova{} ").replace("_", r"\_"))
        lines.append(f"{name} & " + " & ".join(cells) + r" \\")
    return "\n".join(lines) + "\n"


DATASET_NAMES = {"CIC17": "CIC-IDS2017", "IDS18": "CSE-CIC-IDS2018", "UNSW": "UNSW-NB15"}


def budget_rows(data, budget: str) -> str:
    """One row per method, OW-F1 and FPR per dataset at one label budget (methods run on every dataset only)."""
    groups = [g for g in sorted(data, key=lambda g: ("CIC17", "IDS18", "UNSW").index(g.split()[0])
                                if g.split()[0] in ("CIC17", "IDS18", "UNSW") else 9)
              if g.endswith(f"main {budget}")]
    if not groups:
        return ""
    variants = set.intersection(*(set(data[g]) for g in groups))
    order = sorted(variants, key=lambda v: (v != "nova", v))
    best = {}
    for g in groups:
        for key, higher in (("macro_f1_ow", True), ("detect_fpr", False)):
            means = [agg(data[g][v], key)[0] for v in order]
            best[g, key] = (max if higher else min)(means)
    lines = [r"\multicolumn{1}{@{}l}{} & " + " & ".join(rf"\multicolumn{{2}}{{c}}{{{DATASET_NAMES.get(g.split()[0], g.split()[0])}}}" for g in groups)
             + r" \\", "Method & " + " & ".join("OW-F1 & FPR" for _ in groups) + r" \\", r"\midrule"]
    for v in order:
        cells = []
        for g in groups:
            for key in ("macro_f1_ow", "detect_fpr"):
                m = agg(data[g][v], key)[0]
                txt = f"{100 * m:.1f}" if key == "detect_fpr" else f"{m:.3f}"
                cells.append(rf"\textbf{{{txt}}}" if abs(m - best[g, key]) < 1e-12 else txt)
        name = DISPLAY.get(v, v.replace("_", r"\_"))
        lines.append(f"{name} & " + " & ".join(cells) + r" \\")
    return "\n".join(lines) + "\n"


def write_tables(data, out: Path) -> str:
    md = []
    for group in sorted(data):
        g = data[group]
        best = {}
        for key, _, higher in METRICS:
            means = {v: agg(r, key)[0] for v, r in g.items() if agg(r, key)[0] is not None}
            if means and key not in ("labels_used", "train_seconds_total"):
                best[key] = (max if higher else min)(means, key=means.get)
        pvals = wilcoxon_vs(g)
        md.append(f"\n### {group}\n")
        md.append("| Method | n | " + " | ".join(lbl for _, lbl, _ in METRICS) + " | p (NOVA vs) |")
        md.append("|---|---|" + "---|" * len(METRICS) + "---|")
        csv = ["method,n," + ",".join(f"{k}_mean,{k}_std" for k, _, _ in METRICS)]
        tex = []
        order = sorted(g, key=lambda v: (v != "nova" and not v.startswith("nova"), v))
        for v in order:
            cells, csv_cells, tex_cells = [], [], []
            n = len(g[v])
            for key, _, _ in METRICS:
                m, s, _ = agg(g[v], key)
                c = fmt(m, s, key)
                if best.get(key) == v:
                    c = f"**{c}**"
                cells.append(c)
                csv_cells += ["" if m is None else f"{m:.6f}", "" if s is None else f"{s:.6f}"]
                tex_cells.append("--" if m is None else (f"{m:,.0f}" if key in ("labels_used", "train_seconds_total")
                                                       else f"{m:.3f}$\\pm${s:.3f}"))
            p = pvals.get(v)
            md.append(f"| {v} | {n} | " + " | ".join(cells) + f" | {'' if p is None else f'{p:.2g}'} |")
            csv.append(f"{v},{n}," + ",".join(csv_cells))
            tex.append(f"{v.replace('_', chr(92) + '_')} & " + " & ".join(tex_cells) + r" \\")
        slug = group.replace(" ", "_").replace("·", "").replace(".", "")
        (out / f"{slug}.csv").write_text("\n".join(csv), encoding="utf-8")
        (out / f"{slug}.tex").write_text("\n".join(tex), encoding="utf-8")
        (out / f"{slug}_paper.tex").write_text(paper_rows(g, order), encoding="utf-8")
    low = budget_rows(data, "b0.01")
    if low:
        (out / "budget_b001_paper.tex").write_text(low, encoding="utf-8")
    text = "\n".join(md)
    (out / "tables.md").write_text("# Results (mean ± std over seeds)\n" + text + "\n", encoding="utf-8")
    return text


SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # validated categorical slots 1-4 (light surface)
OTHER = "#b9b8b2"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def _style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.xaxis.label.set_color(INK2)
    ax.yaxis.label.set_color(INK2)


def _save(fig, out: Path, name: str) -> None:
    fig.patch.set_facecolor(SURFACE)
    fig.tight_layout()
    fig.savefig(out / f"{name}.png", dpi=200)
    fig.savefig(out / f"{name}.pdf")
    plt.close(fig)


def figures(data, out: Path, tag: str) -> None:
    """Figures for one dataset (groups whose first word is `tag`)."""
    main = next((data[g] for g in data if "main b0.10" in g), None)
    if main:
        # NOVA, the two strongest baselines and the static reference in colour; the rest recede to grey.
        ranked = sorted((v for v in main if v not in ("nova", "static")),
                        key=lambda v: -(agg(main[v], "macro_f1_ow")[0] or 0))
        colored = [v for v in ["nova", *ranked[:2], "static"] if v in main]
        fig, ax = plt.subplots(figsize=(9, 4))
        _style(ax)
        k = 5
        ends = []
        other_label = "other baselines"
        for v in [*[v for v in main if v not in colored], *colored[::-1]]:
            s = np.nanmean(np.vstack([r["series"] for r in main[v].values()]), axis=0)
            sm = np.convolve(np.nan_to_num(s, nan=np.nanmean(s)), np.ones(k) / k, mode="valid")
            x = np.arange(len(sm)) + k // 2
            if v in colored:
                c = SERIES[colored.index(v)]
                ax.plot(x, sm, color=c, lw=2.0 if v == "nova" else 1.4, label=v, zorder=3)
                ends.append([sm[-1], v, c])
            else:
                ax.plot(x, sm, color=OTHER, lw=0.9, zorder=2, label=other_label)
                other_label = "_nolegend_"
        # Direct labels at the right edge, nudged apart so they never overlap.
        ends.sort()
        for i in range(1, len(ends)):
            ends[i][0] = max(ends[i][0], ends[i - 1][0] + 0.045)
        xmax = ax.get_xlim()[1]
        for y, v, c in ends:
            ax.annotate(v, (xmax, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=8, color=INK)
        ax.set_xlabel("window (4,000 flows, chronological)")
        ax.set_ylabel("open-world macro-F1 (5-window mean)")
        ax.set_ylim(0, 1.02)
        ax.grid(axis="y", color=GRID, lw=0.6)
        leg = ax.legend(ncol=5, fontsize=8, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0))
        for t in leg.get_texts():
            t.set_color(INK2)
        _save(fig, out, f"fig_ow_f1_over_time_{tag}")

    budgets = {g: data[g] for g in data if " main b" in g}
    if len(budgets) > 1:
        variants = sorted(set.intersection(*(set(d) for d in budgets.values())), key=lambda v: v != "nova")
        fig, ax = plt.subplots(figsize=(9, 3.6))
        _style(ax)
        width = 0.8 / len(budgets)
        for i, (g, d) in enumerate(sorted(budgets.items(), reverse=True)):
            ms = [agg(d[v], "macro_f1_ow") for v in variants]
            ax.bar(np.arange(len(variants)) + i * width, [m[0] for m in ms], width * 0.92, yerr=[m[1] for m in ms],
                   color=SERIES[i], label=f"label budget {float(g.split()[-1][1:]):.0%}", capsize=2,
                   error_kw={"elinewidth": 0.8, "ecolor": INK2})
        ax.set_xticks(np.arange(len(variants)) + width * (len(budgets) - 1) / 2, variants, rotation=25, ha="right")
        ax.set_ylabel("OW macro-F1")
        ax.grid(axis="y", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        ax.legend(frameon=False, fontsize=8)
        _save(fig, out, f"fig_budget_{tag}")

    abl = next((data[g] for g in data if "ablation" in g), None)
    if abl and main and "nova" in main:
        rows = [("NOVA (full)", agg(main["nova"], "macro_f1_ow"))] + [(v.replace("nova ", "NOVA "), agg(r, "macro_f1_ow"))
                                                                      for v, r in sorted(abl.items())]
        fig, ax = plt.subplots(figsize=(7, 3.6))
        _style(ax)
        ax.barh([r[0] for r in rows][::-1], [r[1][0] for r in rows][::-1], xerr=[r[1][1] for r in rows][::-1],
                color=["#86b6ef"] * (len(rows) - 1) + ["#1c5cab"], height=0.7, capsize=2,
                error_kw={"elinewidth": 0.8, "ecolor": INK2})
        for i, (_, (m, _s, _n)) in enumerate(rows[::-1]):
            ax.annotate(f"{m:.3f}", (m, i), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8,
                        color=INK)
        ax.set_xlabel("OW macro-F1 (mean ± std over seeds)")
        ax.set_xlim(0, 1)
        ax.grid(axis="x", color=GRID, lw=0.6)
        ax.set_axisbelow(True)
        _save(fig, out, f"fig_ablation_{tag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "sentinel.db"))
    ap.add_argument("--out", default=str(ROOT / "experiments" / "paper"))
    ap.add_argument("--groups", default="CIC17,IDS18,UNSW", help="comma-separated; keep groups containing any of these")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    wanted = [t for t in a.groups.split(",") if t]
    data = {g: v for g, v in load(Path(a.db)).items() if any(g.startswith(t) for t in wanted)}
    print(write_tables(data, out))
    for tag in sorted({g.split()[0] for g in data}):
        figures({g: v for g, v in data.items() if g.split()[0] == tag}, out, tag)
    print(f"\nwritten to {out}")


if __name__ == "__main__":
    main()
