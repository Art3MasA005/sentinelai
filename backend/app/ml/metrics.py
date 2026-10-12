"""Evaluation metrics, implemented from first principles so tests can verify them independently.

Label conventions:
- y_true for evaluation is the true class if the model knew that class, else UNKNOWN (open-set).
- y_pred is the reported decision: a known class or UNKNOWN (= needs review, not "malicious").
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

UNKNOWN = "UNKNOWN"

DEFINITIONS: dict[str, str] = {
    "macro_f1": "Unweighted mean of per-class F1 over the classes present in the ground truth (open-set: "
                "true classes unseen by the deployed model count as one UNKNOWN class). Predictions of classes "
                "absent from the ground truth still lower the recall of the true classes.",
    "per_class_recall": "TP / (TP + FN) per true class (open-set labels).",
    "accuracy": "Fraction of flows whose reported decision equals the open-set true label.",
    "fpr": "Benign flows reported as an attack class / all benign flows. UNKNOWN decisions are "
           "reviews, not alarms, and are excluded (see benign_review_rate).",
    "benign_review_rate": "Benign flows reported as UNKNOWN / all benign flows.",
    "pr_auc": "Average precision of attack_score = 1 - P(benign) for attack-vs-benign; "
              "null when a window has only one of the two.",
    "unknown_recall": "Flows whose true class was unseen by the deployed model that were reported "
                      "UNKNOWN / all such flows (unknown rejection).",
    "known_false_unknown_rate": "Flows of known classes reported UNKNOWN / all known-class flows.",
    "unknown_rate": "Flows reported UNKNOWN / all flows.",
    "unknown_auroc": "AUROC of the open-world unknown_score (normalised so the UNKNOWN threshold is 1; for msp "
                     "alone it ranks like 1 - max class probability) for separating flows of classes unseen by the "
                     "deployed model from known-class flows (threshold-free unknown detection).",
    "macro_f1_ow": "Open-world macro-F1 over a FIXED class set (every true class in the data), comparable across "
                   "methods that learn different classes: a flow counts as correct when the decision is its true "
                   "class, or when its class is unknown to the deployed model and the decision is UNKNOWN.",
    "per_class_f1_ow": "Per true class F1 with the open-world credit of macro_f1_ow.",
    "attack_macro_recall_ow": "Mean over attack classes of the open-world-credited recall (correct class, or "
                              "UNKNOWN while the class is unknown to the deployed model).",
    "detect_f1": "Binary attack detection, comparable with binary NIDS papers: a flow is flagged when the "
                 "decision is anything but benign (an attack class or UNKNOWN, both reach an analyst). F1 of "
                 "flagged vs true attack.",
    "detect_recall": "True attack flows that were flagged (attack class or UNKNOWN) / all attack flows.",
    "detect_precision": "Flagged flows that are true attacks / all flagged flows.",
    "detect_fpr": "Benign flows flagged (attack class or UNKNOWN) / all benign flows = fpr + benign_review_rate.",
    "per_class_precision": "TP / (TP + FP) per true class (open-set labels).",
    "per_class_f1": "F1 per true class (open-set labels).",
    "macro_precision": "Unweighted mean of per_class_precision.",
    "macro_recall": "Unweighted mean of per_class_recall.",
    "ref_macro_f1": "Open-set macro-F1 of the deployed model on the fixed reference validation set "
                    "(end of the training period), measured after the window's adaptation step.",
    "forgetting_max": "Largest drop of ref_macro_f1 below its running maximum over the stream.",
    "forgetting_final": "Best ref_macro_f1 so far minus the final ref_macro_f1.",
    "adaptation_delay_windows": "Windows from a drift event to the first accepted adaptation at or after it.",
    "novel_class_delay_windows": "Windows from a class's first appearance in the stream until a deployed "
                                 "model knows it.",
    "latency_ms_per_flow": "Wall-clock inference time (predict + open-world scoring) per flow.",
    "train_seconds_total": "Wall-clock training time of all model versions incl. the initial model.",
    "labels_used": "Ground-truth labels consumed by the adaptation strategy through the label oracle.",
}


def _arr(x: Sequence) -> np.ndarray:
    return np.asarray(x, dtype=object)


def confusion(y_true: Sequence, y_pred: Sequence, labels: list[str] | None = None) -> tuple[list[str], np.ndarray]:
    t, p = _arr(y_true), _arr(y_pred)
    if labels is None:
        labels = sorted(set(t.tolist()) | set(p.tolist()), key=str)
    idx = {lab: i for i, lab in enumerate(labels)}
    m = np.zeros((len(labels), len(labels)), dtype=np.int64)
    for a, b in zip(t, p):
        if a in idx and b in idx:
            m[idx[a], idx[b]] += 1
    return labels, m


def per_class_f1(y_true: Sequence, y_pred: Sequence) -> dict[str, float]:
    """F1 for every class present in y_true."""
    labels, m = confusion(y_true, y_pred)
    present = set(_arr(y_true).tolist())
    out = {}
    for i, lab in enumerate(labels):
        if lab not in present:
            continue
        tp = m[i, i]
        fp = m[:, i].sum() - tp
        fn = m[i, :].sum() - tp
        denom = 2 * tp + fp + fn
        out[lab] = float(2 * tp / denom) if denom else 0.0
    return out


def per_class_precision(y_true: Sequence, y_pred: Sequence) -> dict[str, float]:
    """TP / (TP + FP) for every class present in y_true (0 when the class is never predicted)."""
    labels, m = confusion(y_true, y_pred)
    present = set(_arr(y_true).tolist())
    out = {}
    for i, lab in enumerate(labels):
        if lab in present:
            col = m[:, i].sum()
            out[lab] = float(m[i, i] / col) if col else 0.0
    return out


def roc_auc(y_binary: Sequence, scores: Sequence) -> float | None:
    """Mann-Whitney AUROC with average ranks for ties; None when only one class is present."""
    from scipy.stats import rankdata

    y = np.asarray(y_binary, dtype=bool)
    s = np.asarray(scores, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = rankdata(s)
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def macro_f1(y_true: Sequence, y_pred: Sequence) -> float:
    f = per_class_f1(y_true, y_pred)
    return float(np.mean(list(f.values()))) if f else 0.0


def per_class_recall(y_true: Sequence, y_pred: Sequence) -> dict[str, float]:
    t, p = _arr(y_true), _arr(y_pred)
    return {str(c): float(np.mean(p[t == c] == c)) for c in sorted(set(t.tolist()), key=str)}


def accuracy(y_true: Sequence, y_pred: Sequence) -> float:
    t, p = _arr(y_true), _arr(y_pred)
    return float(np.mean(t == p)) if len(t) else 0.0


def false_positive_rate(y_true: Sequence, y_pred: Sequence, benign: set[str]) -> float | None:
    t, p = _arr(y_true), _arr(y_pred)
    is_benign = np.isin(t, list(benign))
    if not is_benign.any():
        return None
    pb = p[is_benign]
    alarms = ~np.isin(pb, list(benign)) & (pb != UNKNOWN)
    return float(alarms.mean())


def benign_review_rate(y_true: Sequence, y_pred: Sequence, benign: set[str]) -> float | None:
    t, p = _arr(y_true), _arr(y_pred)
    is_benign = np.isin(t, list(benign))
    if not is_benign.any():
        return None
    return float((p[is_benign] == UNKNOWN).mean())


def average_precision(y_binary: Sequence, scores: Sequence) -> float | None:
    """Step-wise AP = sum_k (R_k - R_{k-1}) * P_k over distinct score thresholds (descending)."""
    y = np.asarray(y_binary, dtype=bool)
    s = np.asarray(scores, dtype=float)
    ok = np.isfinite(s)
    y, s = y[ok], s[ok]
    n_pos = int(y.sum())
    if n_pos == 0 or n_pos == len(y):
        return None
    order = np.argsort(-s, kind="mergesort")
    y, s = y[order], s[order]
    last_of_group = np.r_[np.diff(s) != 0, True]
    tp = np.cumsum(y)[last_of_group]
    fp = np.cumsum(~y)[last_of_group]
    precision = tp / (tp + fp)
    recall = tp / n_pos
    prev_recall = np.r_[0.0, recall[:-1]]
    return float(np.sum((recall - prev_recall) * precision))


def unknown_recall(is_novel: Sequence, is_unknown: Sequence) -> float | None:
    n, u = np.asarray(is_novel, bool), np.asarray(is_unknown, bool)
    return float(u[n].mean()) if n.any() else None


def known_false_unknown_rate(is_novel: Sequence, is_unknown: Sequence) -> float | None:
    n, u = np.asarray(is_novel, bool), np.asarray(is_unknown, bool)
    return float(u[~n].mean()) if (~n).any() else None


def forgetting(ref_scores: Sequence[float]) -> tuple[float, float]:
    """(max drop below running max, final drop below best-so-far)."""
    s = np.asarray(ref_scores, dtype=float)
    if s.size == 0:
        return 0.0, 0.0
    running_max = np.maximum.accumulate(s)
    drops = running_max - s
    return float(drops.max()), float(drops[-1])


def open_world_credit(true_labels: Sequence, decisions: Sequence, is_novel: Sequence) -> np.ndarray:
    """Decisions with UNKNOWN replaced by the true class where that class is unknown to the model."""
    t, p = _arr(true_labels), _arr(decisions).copy()
    m = np.asarray(is_novel, bool) & (p == UNKNOWN)
    p[m] = t[m]
    return p


def macro_f1_ow(true_labels: Sequence, decisions: Sequence, is_novel: Sequence) -> float:
    return macro_f1(_arr(true_labels), open_world_credit(true_labels, decisions, is_novel))


def detection(true_labels: Sequence, decisions: Sequence, benign: set[str]) -> dict:
    """Binary view: flagged = decision is not a benign class (attack class or UNKNOWN)."""
    t, p = _arr(true_labels), _arr(decisions)
    attack = ~np.isin(t, list(benign))
    flagged = ~np.isin(p, list(benign))
    tp = int((attack & flagged).sum())
    fp = int((~attack & flagged).sum())
    fn = int((attack & ~flagged).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    fpr = fp / int((~attack).sum()) if (~attack).any() else None
    return {"detect_f1": f1, "detect_recall": rec, "detect_precision": prec, "detect_fpr": fpr}


def evaluate(
    true_labels: np.ndarray,
    decisions: np.ndarray,
    is_unknown: np.ndarray,
    is_novel: np.ndarray,
    attack_scores: np.ndarray,
    benign: set[str],
    unknown_score: np.ndarray | None = None,
) -> dict:
    """Window-level (or pooled) metrics. true_labels are raw dataset labels."""
    y_true = np.where(is_novel, UNKNOWN, true_labels).astype(object)
    y_pred = decisions.astype(object)
    is_attack = ~np.isin(true_labels, list(benign))
    recall = per_class_recall(y_true, y_pred)
    precision = per_class_precision(y_true, y_pred)
    return {
        "n": int(len(true_labels)),
        "macro_f1": macro_f1(y_true, y_pred),
        "macro_precision": float(np.mean(list(precision.values()))) if precision else 0.0,
        "macro_recall": float(np.mean(list(recall.values()))) if recall else 0.0,
        "accuracy": accuracy(y_true, y_pred),
        "per_class_recall": recall,
        "per_class_precision": precision,
        "per_class_f1": per_class_f1(y_true, y_pred),
        "unknown_auroc": None if unknown_score is None else roc_auc(is_novel, np.asarray(unknown_score, float)),
        "fpr": false_positive_rate(true_labels, y_pred, benign),
        "benign_review_rate": benign_review_rate(true_labels, y_pred, benign),
        "pr_auc": average_precision(is_attack, attack_scores),
        "unknown_recall": unknown_recall(is_novel, is_unknown),
        "known_false_unknown_rate": known_false_unknown_rate(is_novel, is_unknown),
        "unknown_rate": float(np.mean(is_unknown)) if len(is_unknown) else 0.0,
        "class_distribution": {str(k): int(v) for k, v in zip(*np.unique(true_labels, return_counts=True))},
        "decision_distribution": {str(k): int(v) for k, v in zip(*np.unique(y_pred.astype(str), return_counts=True))},
        **detection(true_labels, y_pred, benign),
        **_open_world_block(true_labels, y_pred, is_novel, benign),
    }


def _open_world_block(true_labels, y_pred, is_novel, benign: set[str]) -> dict:
    t = _arr(true_labels).astype(object)
    credited = open_world_credit(t, y_pred, is_novel)
    f1 = per_class_f1(t, credited)
    rec = per_class_recall(t, credited)
    attack_rec = [v for c, v in rec.items() if c not in benign]
    return {
        "macro_f1_ow": float(np.mean(list(f1.values()))) if f1 else 0.0,
        "per_class_f1_ow": f1,
        "attack_macro_recall_ow": float(np.mean(attack_rec)) if attack_rec else None,
    }
