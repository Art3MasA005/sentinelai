"""Unsupervised drift detectors. They only see features and model confidence, never labels.

Drift means the input distribution changed; it is NOT evidence of an attack.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import ks_2samp

from app.schemas.experiments import DriftConfig

PSI_BINS = 10
EPS = 1e-6


class DriftMonitor:
    def __init__(self, cfg: DriftConfig, seed: int):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.ref_x: np.ndarray | None = None
        self.ref_conf_mean = 0.0
        self.ref_window = -1  # -1 = training-period reference
        self.last_event: dict[str, int] = {}
        self._edges: list[np.ndarray] = []
        self._ref_hist: list[np.ndarray] = []
        self._active: np.ndarray | None = None

    def set_reference(self, x: np.ndarray, confidence: np.ndarray, window: int) -> None:
        if len(x) > self.cfg.max_reference_rows:
            pick = np.sort(self.rng.choice(len(x), self.cfg.max_reference_rows, replace=False))
            x, confidence = x[pick], confidence[pick]
        self.ref_x = x
        self.ref_conf_mean = float(confidence.mean()) if len(confidence) else 0.0
        self.ref_window = window
        self._active = np.flatnonzero(x.std(axis=0) > 1e-9)
        self._edges, self._ref_hist = [], []
        for j in self._active:
            edges = np.unique(np.quantile(x[:, j], np.linspace(0, 1, PSI_BINS + 1)[1:-1]))
            self._edges.append(edges)
            self._ref_hist.append(self._hist(x[:, j], edges))

    def update_reference_confidence(self, confidence: np.ndarray) -> None:
        """Called when a new model is deployed: confidence baseline belongs to the model."""
        self.ref_conf_mean = float(confidence.mean()) if len(confidence) else 0.0

    @staticmethod
    def _hist(col: np.ndarray, edges: np.ndarray) -> np.ndarray:
        counts = np.bincount(np.searchsorted(edges, col, side="right"), minlength=len(edges) + 1)
        return counts / max(len(col), 1)

    def _ks(self, x: np.ndarray) -> tuple[float, dict]:
        cols = self._active
        if cols is None or len(cols) == 0:
            return 0.0, {"features": 0}
        alpha = self.cfg.ks_alpha / len(cols)  # Bonferroni
        pvals = np.array([ks_2samp(self.ref_x[:, j], x[:, j], method="asymp").pvalue for j in cols])
        drifted = pvals < alpha
        top = np.argsort(pvals)[:5]
        return float(drifted.mean()), {
            "features_tested": int(len(cols)),
            "features_drifted": int(drifted.sum()),
            "corrected_alpha": alpha,
            "top_feature_indices": [int(cols[i]) for i in top],
        }

    def _psi(self, x: np.ndarray) -> tuple[float, dict]:
        if not self._edges:
            return 0.0, {}
        vals = []
        for j, edges, ref in zip(self._active, self._edges, self._ref_hist):
            cur = self._hist(x[:, j], edges)
            r, c = ref + EPS, cur + EPS
            vals.append(float(np.sum((c - r) * np.log(c / r))))
        vals = np.asarray(vals)
        top = np.argsort(-vals)[:5]
        return float(np.mean(vals)), {"top_feature_indices": [int(self._active[i]) for i in top],
                                      "max_feature_psi": float(vals.max())}

    def check(self, window: int, x: np.ndarray, confidence: np.ndarray) -> dict[str, dict]:
        """Return {method: {score, threshold, triggered, suppressed, details}} for this window."""
        out: dict[str, dict] = {}
        for method in self.cfg.detectors:
            if method == "ks":
                score, details = self._ks(x)
                thr = self.cfg.ks_threshold
            elif method == "psi":
                score, details = self._psi(x)
                thr = self.cfg.psi_threshold
            else:
                score = self.ref_conf_mean - float(confidence.mean())
                details = {"reference_confidence": self.ref_conf_mean, "window_confidence": float(confidence.mean())}
                thr = self.cfg.confidence_threshold
            over = score > thr
            last = self.last_event.get(method)
            suppressed = bool(over and last is not None and window - last <= self.cfg.cooldown_windows)
            triggered = bool(over and not suppressed)
            if triggered:
                self.last_event[method] = window
            details["reference_window"] = self.ref_window
            out[method] = {"score": score, "threshold": thr, "triggered": triggered,
                           "suppressed": suppressed, "details": details}
        return out
