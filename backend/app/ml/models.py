"""Classifier factory and the deployable model bundle (classifier + open-world scorer)."""

from __future__ import annotations

import pickle
import time
from dataclasses import dataclass, field

import numpy as np

from app.ml.openworld import OpenWorldScorer
from app.schemas.experiments import ModelConfig, OpenWorldConfig


def make_classifier(cfg: ModelConfig, seed: int):
    p = dict(cfg.params)
    cw = cfg.class_weight
    if cfg.kind == "hist_gb":
        from sklearn.ensemble import HistGradientBoostingClassifier

        p.setdefault("max_iter", 150)
        p.setdefault("early_stopping", False)
        # Without L2, multiclass boosting can diverge when a class has very few samples.
        p.setdefault("l2_regularization", 1.0)
        return HistGradientBoostingClassifier(random_state=seed, class_weight=cw, **p)
    if cfg.kind == "random_forest":
        from sklearn.ensemble import RandomForestClassifier

        p.setdefault("n_estimators", 100)
        p.setdefault("n_jobs", -1)
        return RandomForestClassifier(random_state=seed, class_weight=cw, **p)
    if cfg.kind == "lightgbm":
        from lightgbm import LGBMClassifier

        p.setdefault("n_estimators", 200)
        p.setdefault("verbose", -1)
        p.setdefault("reg_lambda", 1.0)
        return LGBMClassifier(random_state=seed, deterministic=True, class_weight=cw, **p)
    if cfg.kind == "xgboost":
        try:
            from xgboost import XGBClassifier
        except ImportError as e:
            raise RuntimeError("xgboost is not installed in the backend environment.") from e
        return _LabelEncodedXGB(XGBClassifier(random_state=seed, **p))
    if cfg.kind == "logreg":
        from sklearn.linear_model import LogisticRegression

        p.setdefault("max_iter", 1000)
        return LogisticRegression(random_state=seed, class_weight=cw, **p)
    if cfg.kind == "mlp":
        return TorchMLP(seed=seed, class_weight=cw, **p)
    raise ValueError(f"Unknown model kind {cfg.kind}")


class TorchMLP:
    """Feed-forward neural network (PyTorch, CPU) with the sklearn fit / predict_proba / classes_ interface.

    Inputs are already standardised by the Preprocessor. Seeded shuffling and initialisation keep runs
    reproducible for a fixed seed and thread count.
    """

    def __init__(self, seed: int, hidden: tuple[int, ...] = (128, 64), dropout: float = 0.1, epochs: int = 25,
                 batch_size: int = 512, lr: float = 1e-3, weight_decay: float = 1e-4,
                 class_weight: str | None = None, threads: int = 4, device: str = "auto"):
        self.seed, self.hidden, self.dropout, self.epochs = seed, tuple(hidden), dropout, epochs
        self.batch_size, self.lr, self.weight_decay = batch_size, lr, weight_decay
        self.class_weight, self.threads = class_weight, threads
        # "auto" uses the GPU when this PyTorch build has CUDA, else the CPU; "cpu" / "cuda" force one.
        self.device = device
        self.device_used: str | None = None
        self.classes_: np.ndarray | None = None
        self.net = None

    def _device(self, torch) -> str:
        if self.device == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return self.device

    @staticmethod
    def _torch():
        try:
            import torch
        except ImportError as e:
            raise RuntimeError("PyTorch is not installed in the backend environment (pip install torch).") from e
        return torch

    def fit(self, x: np.ndarray, y: np.ndarray) -> "TorchMLP":
        import os

        # Deterministic cuBLAS kernels; must be set before the first CUDA call in the process.
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch = self._torch()
        torch.manual_seed(self.seed)
        torch.set_num_threads(self.threads)
        torch.use_deterministic_algorithms(True, warn_only=True)
        dev = self.device_used = self._device(torch)
        self.classes_, yi = np.unique(y, return_inverse=True)
        layers, width = [], x.shape[1]
        for h in self.hidden:
            layers += [torch.nn.Linear(width, h), torch.nn.ReLU(), torch.nn.Dropout(self.dropout)]
            width = h
        layers.append(torch.nn.Linear(width, len(self.classes_)))
        # Weights are initialised on the CPU, so a seed gives the same starting network on either device.
        self.net = torch.nn.Sequential(*layers).to(dev)
        weight = None
        if self.class_weight == "balanced":
            counts = np.bincount(yi, minlength=len(self.classes_)).astype(np.float32)
            weight = torch.tensor(len(yi) / (len(counts) * np.maximum(counts, 1)), dtype=torch.float32, device=dev)
        loss_fn = torch.nn.CrossEntropyLoss(weight=weight)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr, weight_decay=self.weight_decay)
        xt = torch.tensor(np.asarray(x, dtype=np.float32), device=dev)
        yt = torch.tensor(yi, dtype=torch.long, device=dev)
        gen = torch.Generator().manual_seed(self.seed)  # CPU generator: the batch order is device-independent
        self.net.train()
        for _ in range(self.epochs):
            order = torch.randperm(len(yt), generator=gen).to(dev)
            for s in range(0, len(yt), self.batch_size):
                idx = order[s:s + self.batch_size]
                opt.zero_grad()
                loss_fn(self.net(xt[idx]), yt[idx]).backward()
                opt.step()
        self.net.eval()
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        torch = self._torch()
        dev = next(self.net.parameters()).device
        out = []
        with torch.no_grad():
            for s in range(0, len(x), 8192):
                xb = torch.tensor(np.asarray(x[s:s + 8192], dtype=np.float32), device=dev)
                out.append(torch.softmax(self.net(xb), dim=1).cpu().numpy())
        return np.concatenate(out) if out else np.empty((0, len(self.classes_)))


class _LabelEncodedXGB:
    """XGBoost needs integer labels; keep the sklearn string-label interface."""

    def __init__(self, inner):
        self.inner = inner
        self.classes_ = None

    def fit(self, x, y, sample_weight=None):
        self.classes_, enc = np.unique(y, return_inverse=True)
        self.inner.fit(x, enc, sample_weight=sample_weight)
        return self

    def predict_proba(self, x):
        return self.inner.predict_proba(x)


@dataclass
class DeployedModel:
    version: int
    parent_version: int | None
    created_window: int
    classifier: object
    openworld: OpenWorldScorer
    classes: list[str]
    train_rows: int
    train_seconds: float
    model_bytes: int = 0
    meta: dict = field(default_factory=dict)

    def predict(self, x: np.ndarray, benign: set[str]) -> dict[str, np.ndarray]:
        proba = self.classifier.predict_proba(x)
        classes = np.asarray(self.classes, dtype=object)
        top = proba.argmax(axis=1)
        conf = proba[np.arange(len(x)), top]
        unknown, reason, novelty, unknown_score = self.openworld.score(x, conf, top)
        benign_idx = [i for i, c in enumerate(self.classes) if c in benign]
        attack = 1.0 - proba[:, benign_idx].sum(axis=1) if benign_idx else np.full(len(x), np.nan)
        predicted = classes[top]
        return {
            "proba": proba,
            "predicted": predicted,
            "decision": np.where(unknown, "UNKNOWN", predicted).astype(object),
            "confidence": conf,
            "attack_score": attack,
            "novelty": novelty,
            "unknown_score": unknown_score,
            "is_unknown": unknown,
            "reason": reason,
        }


def train_model(
    x: np.ndarray,
    y: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    model_cfg: ModelConfig,
    ow_cfg: OpenWorldConfig,
    seed: int,
    version: int,
    parent: int | None,
    window: int,
    sample_weight: np.ndarray | None = None,
) -> DeployedModel:
    classes, counts = np.unique(y, return_counts=True)
    rare = classes[counts < model_cfg.min_class_samples]
    if len(rare):
        keep = ~np.isin(y, rare)
        x, y = x[keep], y[keep]
        if sample_weight is not None:
            sample_weight = sample_weight[keep]
        classes = classes[counts >= model_cfg.min_class_samples]
    if len(classes) < 2:
        raise ValueError(
            f"Training data has a single class ({classes[0] if len(classes) else 'none'}). "
            "Increase split.train_fraction or choose a time range that contains attacks."
        )
    t0 = time.perf_counter()
    clf = make_classifier(model_cfg, seed)
    if sample_weight is not None and model_cfg.kind != "mlp":
        clf.fit(x, y, sample_weight=sample_weight)
    else:
        clf.fit(x, y)
    ow = OpenWorldScorer(ow_cfg, seed).fit(clf, x, y, x_val, y_val)
    elapsed = time.perf_counter() - t0
    model = DeployedModel(
        version=version,
        parent_version=parent,
        created_window=window,
        classifier=clf,
        openworld=ow,
        classes=[str(c) for c in clf.classes_],
        train_rows=int(len(y)),
        train_seconds=elapsed,
        meta={"excluded_rare_classes": [str(c) for c in rare],
              **({"device": clf.device_used} if getattr(clf, "device_used", None) else {})},
    )
    model.model_bytes = len(pickle.dumps(clf, protocol=pickle.HIGHEST_PROTOCOL))
    return model
