"""Paper-ready figures (PRD phase P5): PNG for slides, PDF (vector) for papers.

Every figure carries a footer with run label, method, dataset hash and config hash; figures from
DEMO runs get a diagonal "DEMO DATA" watermark so they cannot be mistaken for real results.
"""

from __future__ import annotations

import io
import json
import zipfile

import matplotlib

matplotlib.use("Agg")  # headless: never opens a window

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.config import APP_VERSION  # noqa: E402
from app.storage.db import loads  # noqa: E402
from app.storage.repository import Repository  # noqa: E402

INK = "#1f2937"
MUTED = "#6b7280"
GRID = "#e5e7eb"
PALETTE = ["#2563eb", "#7c3aed", "#d97706", "#dc2626", "#16a34a", "#0891b2", "#db2777", "#4b5563"]
METHOD_NAMES = {
    "static": "Static baseline",
    "periodic_retrain": "Periodic retrain",
    "continual_replay": "Continual replay",
    "guarded_selective": "Selective adaptation",
}

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.edgecolor": MUTED,
    "axes.labelcolor": INK,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "legend.frameon": False,
    "legend.fontsize": 8,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
})


def run_label(seq: int | None) -> str:
    return f"RUN-{seq:03d}" if seq else "RUN"


def _footer(fig, run: dict) -> None:
    text = (f"{run_label(run.get('seq'))} · {METHOD_NAMES.get(run['method'], run['method'])} · "
            f"dataset {str(run.get('dataset_sha256') or '')[:10]} · config {run['config_hash'][:10]} · "
            f"SentinelAI {APP_VERSION}")
    # Place the footer ~0.42 inch below the figure so it never collides with the x-axis label.
    fig.text(0.01, -0.42 / fig.get_size_inches()[1], text, fontsize=6.5, color=MUTED, ha="left", va="top")
    if run.get("data_origin") == "demo":
        fig.text(0.5, 0.5, "DEMO DATA", fontsize=46, color="#d97706", alpha=0.12, rotation=25,
                 ha="center", va="center", weight="bold")


def _save(fig, name: str, out: dict[str, bytes]) -> None:
    for ext in ("png", "pdf"):
        buf = io.BytesIO()
        fig.savefig(buf, format=ext)
        out[f"{name}.{ext}"] = buf.getvalue()
    plt.close(fig)


def _drift_windows(windows: list[dict]) -> list[int]:
    return [w["window"] for w in windows if any(d.get("triggered") for d in (w["drift"] or {}).values())]


def _mark_drift(ax, windows: list[dict]) -> None:
    for i, x in enumerate(_drift_windows(windows)):
        ax.axvline(x, color="#7c3aed", alpha=0.25, lw=0.8, ls="--", label="Drift detected" if i == 0 else None)


def run_figures(repo: Repository, run: dict) -> dict[str, bytes]:
    """Figures for one run. Returns {filename: bytes}."""
    windows = repo.windows(run["run_id"])
    summary = loads(run["summary_json"]) or {}
    out: dict[str, bytes] = {}
    if not windows:
        return out
    x = [w["window"] for w in windows]

    # 1. Detection quality per window
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for key, label, color, ls in [("macro_f1", "Macro-F1 (open-set)", PALETTE[0], "-"),
                                  ("ref_macro_f1", "Reference macro-F1", PALETTE[1], "-"),
                                  ("unknown_recall", "Unknown recall", PALETTE[2], "--"),
                                  ("fpr", "False positive rate", PALETTE[3], "-")]:
        y = [w["metrics"].get(key) for w in windows]
        y = [np.nan if v is None else v for v in y]
        ax.plot(x, y, color=color, ls=ls, lw=1.6, marker="o", ms=2.5, label=label)
    _mark_drift(ax, windows)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("Replay window")
    ax.set_ylabel("Score")
    ax.set_title("Detection performance over the stream")
    ax.legend(loc="lower left", ncol=2)
    _footer(fig, run)
    _save(fig, "01_window_metrics", out)

    # 2. Decisions per window
    benign = {"BENIGN", "Benign", "Normal"}
    b, a, u = [], [], []
    for w in windows:
        d = w["metrics"].get("decision_distribution", {})
        u.append(d.get("UNKNOWN", 0))
        b.append(sum(v for k, v in d.items() if k in benign))
        a.append(sum(v for k, v in d.items() if k not in benign and k != "UNKNOWN"))
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.stackplot(x, b, a, u, labels=["Benign", "Attack class", "UNKNOWN (review)"],
                 colors=[PALETTE[0], PALETTE[3], PALETTE[2]], alpha=0.85)
    ax.set_xlabel("Replay window")
    ax.set_ylabel("Flows")
    ax.set_title("Reported decisions per window")
    ax.legend(loc="upper left", ncol=3)
    _footer(fig, run)
    _save(fig, "02_decisions", out)

    # 3. Drift detectors: score vs threshold
    methods = sorted({m for w in windows for m in (w["drift"] or {})})
    if methods:
        fig, axes = plt.subplots(len(methods), 1, figsize=(6.4, 1.9 * len(methods)), sharex=True, squeeze=False)
        for ax, m in zip(axes[:, 0], methods):
            score = [(w["drift"] or {}).get(m, {}).get("score", np.nan) for w in windows]
            thr = [(w["drift"] or {}).get(m, {}).get("threshold", np.nan) for w in windows]
            hit = [xi for xi, w in zip(x, windows) if (w["drift"] or {}).get(m, {}).get("triggered")]
            ax.plot(x, score, color=PALETTE[1], lw=1.5, label="Score")
            ax.plot(x, thr, color=PALETTE[3], lw=1, ls="--", label="Threshold")
            if hit:
                ax.scatter(hit, [score[x.index(h)] for h in hit], color=PALETTE[3], s=14, zorder=3, label="Triggered")
            ax.set_ylabel({"ks": "KS share", "psi": "PSI", "confidence": "Conf. drop"}.get(m, m))
            ax.legend(loc="upper right", ncol=3)
        axes[0, 0].set_title("Drift detectors (unsupervised; drift is not evidence of an attack)")
        axes[-1, 0].set_xlabel("Replay window")
        _footer(fig, run)
        _save(fig, "03_drift", out)

    # 4. Confusion matrix (row-normalised)
    cm = summary.get("confusion_matrix") or {}
    labels, matrix = cm.get("labels") or [], np.array(cm.get("matrix") or [], dtype=float)
    if len(labels):
        norm = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1)
        fig, ax = plt.subplots(figsize=(1.0 + 0.62 * len(labels), 0.8 + 0.55 * len(labels)))
        ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
        ax.grid(False)
        ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
        ax.set_yticks(range(len(labels)), labels)
        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, f"{int(matrix[i, j])}", ha="center", va="center", fontsize=7,
                        color="white" if norm[i, j] > 0.55 else INK)
        ax.set_xlabel("Reported decision")
        ax.set_ylabel("Ground truth (open-set)")
        ax.set_title("Confusion matrix (row-normalised colour)")
        _footer(fig, run)
        _save(fig, "04_confusion", out)

    # 5. Adaptation timeline: deployed model version per window + decisions
    events, _ = repo.adaptation_events(run["run_id"], None, 0, 10**6)
    fig, ax = plt.subplots(figsize=(6.4, 2.6))
    ax.step(x, [w["model_version"] for w in windows], where="post", color=INK, lw=1.4, label="Deployed model")
    for decision, color, marker in [("accepted", PALETTE[4], "^"), ("rejected", PALETTE[3], "x"),
                                    ("rollback", PALETTE[1], "v")]:
        pts = [(e["window"], e["to_version"] if decision != "rejected" else e["from_version"])
               for e in events if e["decision"] == decision]
        if pts:
            ax.scatter(*zip(*pts), color=color, marker=marker, s=28, zorder=3, label=decision.capitalize())
    _mark_drift(ax, windows)
    ax.set_xlabel("Replay window")
    ax.set_ylabel("Model version")
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax.set_title("Adaptation decisions")
    ax.set_ylim(0.5, max(w["model_version"] for w in windows) + 1.2)  # headroom for the legend
    ax.legend(loc="upper left", ncol=4)
    _footer(fig, run)
    _save(fig, "05_adaptation", out)
    return out


def comparison_figures(repo: Repository, runs: list[dict], aggregates: list[dict]) -> dict[str, bytes]:
    """Macro-F1 over windows per run, and per-method means with std error bars (multi-seed)."""
    out: dict[str, bytes] = {}
    demo = any(r.get("data_origin") == "demo" for r in runs)
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    for i, r in enumerate(runs):
        w = repo.windows(r["run_id"])
        ax.plot([v["window"] for v in w], [v["metrics"].get("macro_f1") for v in w], lw=1.4,
                color=PALETTE[i % len(PALETTE)],
                label=f"{run_label(r.get('seq'))} {METHOD_NAMES.get(r['method'], r['method'])}")
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Replay window")
    ax.set_ylabel("Macro-F1 (open-set)")
    ax.set_title("Macro-F1 over the stream")
    ax.legend(loc="lower left", ncol=2)
    if demo:
        fig.text(0.5, 0.5, "DEMO DATA", fontsize=46, color="#d97706", alpha=0.12, rotation=25,
                 ha="center", va="center", weight="bold")
    _save(fig, "compare_macro_f1_windows", out)

    keys = [("macro_f1", "Macro-F1"), ("unknown_recall", "Unknown recall"), ("fpr", "FPR"),
            ("forgetting_max", "Forgetting")]
    groups = [a for a in aggregates if a["metrics"]]
    if groups:
        fig, ax = plt.subplots(figsize=(6.4, 3.0))
        width = 0.8 / len(groups)
        for i, g in enumerate(groups):
            means = [g["metrics"].get(k, {}).get("mean", np.nan) for k, _ in keys]
            stds = [g["metrics"].get(k, {}).get("std", 0) for k, _ in keys]
            ax.bar(np.arange(len(keys)) + i * width - 0.4 + width / 2, means, width, yerr=stds, capsize=2,
                   color=PALETTE[i % len(PALETTE)], label=f"{METHOD_NAMES.get(g['method'], g['method'])} (n={g['n']})")
        ax.set_xticks(range(len(keys)), [label for _, label in keys])
        ax.set_ylim(0, 1.05)
        ax.set_title("Method comparison (mean ± std over seeds)")
        ax.legend(loc="upper right", ncol=2)
        if demo:
            fig.text(0.5, 0.5, "DEMO DATA", fontsize=46, color="#d97706", alpha=0.12, rotation=25,
                     ha="center", va="center", weight="bold")
        _save(fig, "compare_methods", out)
    return out


def zip_figures(files: dict[str, bytes], manifest: dict, prefix: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            z.writestr(f"{prefix}/{name}", data)
        z.writestr(f"{prefix}/figures.json", json.dumps(manifest, indent=2, default=str))
    return buf.getvalue()
