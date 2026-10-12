"""Label oracle: the ONLY path by which adaptation strategies may see ground truth.

Evaluation reads the true labels directly; strategies must ask the oracle, which enforces the
label delay and budget and counts every label handed out.

By default the budgeted sample of a window is uniform at random. A query strategy may instead
`request` which flows of the CURRENT window an analyst should label (chosen from features and model
outputs only); the count is still capped by the budget and the labels still arrive after the delay.
"""

from __future__ import annotations

import numpy as np

from app.schemas.experiments import LabelPolicy


class LabelOracle:
    def __init__(self, window_labels: list[np.ndarray], policy: LabelPolicy, seed: int):
        self._labels = window_labels
        self.policy = policy
        self.seed = seed
        self.labels_used = 0
        self._taken: set[int] = set()
        self._requested: dict[int, np.ndarray] = {}

    def budget_for(self, window: int) -> int:
        n = len(self._labels[window])
        return n if self.policy.budget >= 1 else int(round(n * self.policy.budget))

    def request(self, window: int, indices) -> None:
        """Choose which flows of `window` get labelled (at most the budget, only while it is current)."""
        if window in self._requested or window in self._taken:
            raise PermissionError(f"Labels for window {window} were already requested.")
        idx = np.unique(np.asarray(indices, dtype=np.int64))
        n = len(self._labels[window])
        if len(idx) and (idx[0] < 0 or idx[-1] >= n):
            raise IndexError(f"Requested flow index out of range for window {window}.")
        if len(idx) > self.budget_for(window):
            raise PermissionError(f"Requested {len(idx)} labels; the budget for window {window} is "
                                  f"{self.budget_for(window)}.")
        self._requested[window] = idx

    def available_windows(self, current_window: int) -> list[int]:
        """Windows whose labels have arrived by the end of `current_window` and were not taken yet."""
        last = current_window - self.policy.delay_windows
        return [w for w in range(0, last + 1) if w not in self._taken]

    def take(self, window: int, current_window: int) -> tuple[np.ndarray, np.ndarray]:
        """Return (indices within window, labels) for the budgeted sample of a revealed window."""
        if window > current_window - self.policy.delay_windows:
            raise PermissionError(f"Labels for window {window} are not available at window {current_window}.")
        if window in self._taken:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=object)
        self._taken.add(window)
        y = self._labels[window]
        n = len(y)
        if window in self._requested:
            idx = self._requested.pop(window)
        else:
            k = self.budget_for(window)
            rng = np.random.default_rng(self.seed * 100_003 + window)
            idx = np.sort(rng.choice(n, k, replace=False)) if k < n else np.arange(n)
        self.labels_used += len(idx)
        return idx, y[idx]
