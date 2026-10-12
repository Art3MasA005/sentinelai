"""Feature preprocessing. Fitted ONLY on the training period (research-integrity rule)."""

from __future__ import annotations

import numpy as np
import pandas as pd

MAX_CATEGORIES = 32


class Preprocessor:
    def __init__(self, numeric: list[str], categorical: list[str]):
        self.numeric = list(numeric)
        self.categorical = list(categorical)
        self.fitted_rows = 0
        self.medians: np.ndarray | None = None
        self.mean: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.categories: dict[str, list[str]] = {}

    @staticmethod
    def _numeric_block(df: pd.DataFrame, cols: list[str]) -> np.ndarray:
        x = df[cols].to_numpy(dtype="float64", copy=True) if cols else np.empty((len(df), 0))
        x[~np.isfinite(x)] = np.nan
        return x

    def fit(self, df: pd.DataFrame) -> "Preprocessor":
        x = self._numeric_block(df, self.numeric)
        with np.errstate(all="ignore"):
            med = np.nanmedian(x, axis=0) if x.shape[1] else np.empty(0)
        self.medians = np.where(np.isfinite(med), med, 0.0)
        x = np.where(np.isnan(x), self.medians, x)
        # Clip extreme magnitudes before scaling so a few huge flow-rate values don't dominate.
        x = np.sign(x) * np.log1p(np.abs(x))
        self.mean = x.mean(axis=0) if len(x) else np.zeros(x.shape[1])
        std = x.std(axis=0) if len(x) else np.ones(x.shape[1])
        self.scale = np.where(std > 1e-12, std, 1.0)
        for c in self.categorical:
            counts = df[c].value_counts()
            self.categories[c] = counts.index[:MAX_CATEGORIES].astype(str).tolist()
        self.fitted_rows = len(df)
        return self

    def transform(self, df: pd.DataFrame, chunk: int = 200_000) -> np.ndarray:
        if self.mean is None:
            raise RuntimeError("Preprocessor is not fitted.")
        if len(df) > chunk:  # keep float64 temporaries small for multi-million-row streams
            return np.vstack([self.transform(df.iloc[s:s + chunk], chunk) for s in range(0, len(df), chunk)])
        x = self._numeric_block(df, self.numeric)
        x = np.where(np.isnan(x), self.medians, x)
        x = (np.sign(x) * np.log1p(np.abs(x)) - self.mean) / self.scale
        blocks = [x]
        for c in self.categorical:
            vals = df[c].astype(str).to_numpy()
            cats = self.categories[c]
            onehot = np.zeros((len(df), len(cats) + 1))  # last column = "other / unseen"
            idx = {v: i for i, v in enumerate(cats)}
            onehot[np.arange(len(df)), [idx.get(v, len(cats)) for v in vals]] = 1.0
            blocks.append(onehot)
        return np.hstack(blocks).astype(np.float32)

    @property
    def feature_names(self) -> list[str]:
        names = list(self.numeric)
        for c in self.categorical:
            names += [f"{c}={v}" for v in self.categories[c]] + [f"{c}=<other>"]
        return names
