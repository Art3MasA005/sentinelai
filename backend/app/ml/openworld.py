"""Open-world (unknown) scoring.

UNKNOWN means "unfamiliar or uncertain for the deployed model, needs review". It is NOT a
statement that the flow is malicious.

Every detector is normalised so that its threshold sits at 1.0; `unknown_score` is the maximum over
the enabled detectors, so `unknown_score > 1` is exactly the UNKNOWN decision and the score itself
ranks flows for AUROC and for label selection.

- msp: max softmax probability below a per-class validation quantile.
- centroid: distance to the nearest class centroid, scaled by that class's median spread.
- knn: distance to the k-th nearest training flow *of the predicted class* (class-conditional deep
  k-NN, Sun et al. ICML 2022; Corsini & Yang 2023 found k-NN the strongest single OOD detector for
  NIDS). Unlike one centroid per class it follows multi-modal classes such as BENIGN.
"""

from __future__ import annotations

import numpy as np

from app.schemas.experiments import OpenWorldConfig

MAX_PER_CLASS = 5000
MIN_CALIBRATION = 30
CHUNK = 4096


def _sq_norms(x: np.ndarray) -> np.ndarray:
    return np.einsum("ij,ij->i", x, x)


def _kth_distance(q: np.ndarray, bank: np.ndarray, bank_sq: np.ndarray, k: int, skip_self: bool = False) -> np.ndarray:
    """Euclidean distance from each row of q to its k-th nearest row of bank (chunked, float32)."""
    kk = min(k + int(skip_self), len(bank)) - 1
    out = np.empty(len(q), dtype=np.float32)
    for s in range(0, len(q), CHUNK):
        qb = q[s:s + CHUNK]
        d2 = _sq_norms(qb)[:, None] - 2.0 * (qb @ bank.T) + bank_sq[None, :]
        out[s:s + CHUNK] = np.sqrt(np.maximum(np.partition(d2, kk, axis=1)[:, kk], 0.0))
    return out


class OpenWorldScorer:
    def __init__(self, cfg: OpenWorldConfig, seed: int):
        self.cfg = cfg
        self.seed = seed
        # Per-class thresholds, indexed like clf.classes_.
        self.msp_tau = np.zeros(0)
        self.classes: list[str] = []
        self.dist_tau = np.inf
        self.centroids: np.ndarray | None = None
        self.scales: np.ndarray | None = None
        self.banks: list[np.ndarray] = []
        self.bank_sq: list[np.ndarray] = []
        self.knn_tau = np.zeros(0)

    @property
    def uses_msp(self) -> bool:
        return self.cfg.method in ("msp", "msp+centroid", "msp+knn")

    @property
    def uses_distance(self) -> bool:
        return self.cfg.method in ("centroid", "msp+centroid")

    @property
    def uses_knn(self) -> bool:
        return self.cfg.method in ("knn", "msp+knn")

    def _distance(self, x: np.ndarray) -> np.ndarray:
        # Normalized Euclidean distance to the nearest class centroid.
        x = x.astype(np.float64, copy=False)
        c = self.centroids
        d2 = (x ** 2).sum(1)[:, None] - 2.0 * (x @ c.T) + (c ** 2).sum(1)[None, :]
        return (np.sqrt(np.clip(d2, 0.0, None)) / self.scales).min(axis=1)

    def _knn(self, x: np.ndarray, top: np.ndarray) -> np.ndarray:
        """Distance to the k-th nearest training flow of each row's predicted class."""
        x = np.asarray(x, dtype=np.float32)
        out = np.zeros(len(x), dtype=np.float32)
        for c in np.unique(top):
            rows = np.flatnonzero(top == c)
            out[rows] = _kth_distance(x[rows], self.banks[c], self.bank_sq[c], self.cfg.knn_k)
        return out

    def fit(self, clf, x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray):
        """Thresholds are calibrated on the reference validation set of known classes only."""
        self.classes = [str(c) for c in clf.classes_]
        if self.cfg.method == "none":
            return self
        rng = np.random.default_rng(self.seed)
        known = set(clf.classes_.tolist())
        mask = np.isin(y_val, list(known))
        xv = x_val[mask] if mask.any() else x_train[: min(len(x_train), 5000)]
        yv = np.asarray(y_val)[mask] if mask.any() else np.asarray(y_train)[: len(xv)]
        proba_v = clf.predict_proba(xv) if (self.uses_msp or self.uses_knn) else None
        if self.uses_msp:
            # Class-conditional: a global quantile is dominated by the majority class and rejects
            # every newly learned class. Classes absent from validation get the most lenient threshold.
            top, conf = proba_v.argmax(axis=1), proba_v.max(axis=1)
            taus = np.full(len(clf.classes_), np.nan)
            for i in range(len(clf.classes_)):
                if (top == i).sum() >= 20:
                    taus[i] = np.quantile(conf[top == i], self.cfg.msp_quantile)
            fallback = np.nanmin(taus) if np.isfinite(taus).any() else float(np.quantile(conf, self.cfg.msp_quantile))
            self.msp_tau = np.where(np.isfinite(taus), taus, fallback)
        if self.uses_distance:
            cents, scales = [], []
            for c in clf.classes_:
                xc = x_train[y_train == c]
                if len(xc) > MAX_PER_CLASS:
                    xc = xc[rng.choice(len(xc), MAX_PER_CLASS, replace=False)]
                mu = xc.mean(axis=0)
                cents.append(mu)
                d = np.sqrt(((xc - mu) ** 2).sum(axis=1))
                scales.append(max(float(np.median(d)), 1e-6))
            self.centroids = np.vstack(cents)
            self.scales = np.asarray(scales)
            self.dist_tau = float(np.quantile(self._distance(xv), self.cfg.distance_quantile))
        if self.uses_knn:
            self.banks, self.bank_sq = [], []
            taus = np.zeros(len(clf.classes_))
            top_v = proba_v.argmax(axis=1)
            for i, c in enumerate(clf.classes_):
                xc = np.asarray(x_train[y_train == c], dtype=np.float32)
                if len(xc) > self.cfg.knn_bank_per_class:
                    xc = xc[np.sort(rng.choice(len(xc), self.cfg.knn_bank_per_class, replace=False))]
                self.banks.append(np.ascontiguousarray(xc))
                self.bank_sq.append(_sq_norms(xc))
                # Calibrate on held-out flows of this class that the model also predicts as this class;
                # newly learned classes have no validation flows, so fall back to leave-one-out on the bank.
                hv = xv[(top_v == i) & (yv == c)]
                if len(hv) >= MIN_CALIBRATION:
                    d = _kth_distance(np.asarray(hv, np.float32), xc, self.bank_sq[-1], self.cfg.knn_k)
                else:
                    d = _kth_distance(xc, xc, self.bank_sq[-1], self.cfg.knn_k, skip_self=True)
                taus[i] = max(float(np.quantile(d, self.cfg.distance_quantile)), 1e-6)
            self.knn_tau = taus
        return self

    def score(self, x: np.ndarray, confidence: np.ndarray, top: np.ndarray):
        """Returns (is_unknown, reason, novelty, unknown_score)."""
        n = len(x)
        parts: list[np.ndarray] = []
        reasons = np.full(n, None, dtype=object)

        def flag(mask: np.ndarray, name: str) -> None:
            for i in np.flatnonzero(mask):
                reasons[i] = name if reasons[i] is None else f"{reasons[i]}+{name}"

        if self.uses_msp:
            tau = self.msp_tau[top]
            s = (1.0 - confidence) / np.maximum(1.0 - tau, 1e-9)
            parts.append(s)
            flag(s > 1.0, "low_confidence")
        novelty = np.full(n, np.nan)
        if self.uses_distance:
            novelty = self._distance(x)
            s = novelty / self.dist_tau
            parts.append(s)
            flag(s > 1.0, "far_from_known")
        if self.uses_knn:
            novelty = self._knn(x, top).astype(np.float64)
            s = novelty / self.knn_tau[top]
            parts.append(s)
            flag(s > 1.0, "far_from_known")
        score = np.max(np.vstack(parts), axis=0) if parts else np.zeros(n)
        return score > 1.0, reasons, novelty, score

    def describe(self) -> dict:
        d = {"method": self.cfg.method, "msp_thresholds": dict(zip(self.classes, map(float, self.msp_tau))),
             "distance_threshold": None if not np.isfinite(self.dist_tau) else self.dist_tau}
        if self.uses_knn:
            d.update(knn_k=self.cfg.knn_k, knn_thresholds=dict(zip(self.classes, map(float, self.knn_tau))))
        return d
