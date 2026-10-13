"""Adaptation strategies compared in experiments.

Every strategy runs AFTER the current window has been predicted and evaluated, so changes only
affect later windows (no look-ahead). Ground truth is only reachable through `engine.oracle`.

Families:
- Baselines: static, periodic_retrain, continual_replay, guarded_selective (guard + rollback only).
- Published approaches re-implemented under this protocol (same model, budget, delay and detector):
  uncertainty_al, insomnia, netguard_ps, cbrs_replay. See docs/LITERATURE.md for what each keeps
  from the original paper and what is out of scope.
- nova: the proposed method (Novelty-aware, Open-world, Validated Adaptation).

Query strategies may pick WHICH flows of the current window are labelled via `select`; how MANY is
fixed by the label budget, so every method pays the same labelling cost (insomnia pays none).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from app.schemas.experiments import AdaptationConfig

if TYPE_CHECKING:
    from app.ml.pipeline import ExperimentEngine


class ReplayBuffer:
    """Fixed-size reservoir sample over everything ever added (deterministic for a seed)."""

    def __init__(self, capacity: int, seed: int):
        self.capacity = capacity
        self.rng = np.random.default_rng(seed)
        self.x: np.ndarray | None = None
        self.y: np.ndarray | None = None
        self.seen = 0

    def add(self, x: np.ndarray, y: np.ndarray) -> None:
        if len(x) == 0:
            return
        if self.x is None:
            self.x = np.empty((0, x.shape[1]), dtype=x.dtype)
            self.y = np.empty(0, dtype=object)
        room = max(self.capacity - len(self.y), 0)
        if room:
            self.x = np.vstack([self.x, x[:room]])
            self.y = np.concatenate([self.y, y[:room].astype(object)])
        for i in range(room, len(x)):
            j = int(self.rng.integers(0, self.seen + i + 1))
            if j < self.capacity:
                self.x[j], self.y[j] = x[i], y[i]
        self.seen += len(x)


class ClassBalancedBuffer:
    """Class-balancing reservoir (CBRS, Chrysakis & Moens, ICML 2020; the memory used for NIDS replay by
    Amalapuram et al., NeurIPS 2023). While there is room every sample is kept. Once full, a sample of
    a class that is not the largest evicts a random member of the largest class; a sample of the
    largest class replaces a random member of its own class with probability size/seen (reservoir).
    "Largest" compares size / weight, so a weight of 4 lets BENIGN keep four shares: benign traffic is
    multi-modal and starving it raises false alarms."""

    def __init__(self, capacity: int, seed: int, weights: dict[str, float] | None = None):
        self.capacity = capacity
        self.rng = np.random.default_rng(seed)
        self.weights = weights or {}
        self.rows: dict[str, list[np.ndarray]] = {}
        self.seen: dict[str, int] = {}
        self.total = 0
        self._cache: tuple[np.ndarray, np.ndarray] | None = None

    def _largest(self) -> str:
        return max(self.rows, key=lambda c: len(self.rows[c]) / self.weights.get(c, 1.0))

    def add(self, x: np.ndarray, y: np.ndarray) -> None:
        if len(x) == 0:
            return
        self._cache = None
        for xi, yi in zip(x, np.asarray(y).astype(str)):
            bucket = self.rows.setdefault(yi, [])
            self.seen[yi] = self.seen.get(yi, 0) + 1
            if self.total < self.capacity:
                bucket.append(xi)
                self.total += 1
                continue
            big = self._largest()
            if big != yi:
                victim = self.rows[big]
                victim[int(self.rng.integers(len(victim)))] = victim[-1]
                victim.pop()
                bucket.append(xi)
            elif self.rng.random() < len(bucket) / self.seen[yi]:
                bucket[int(self.rng.integers(len(bucket)))] = xi

    def _arrays(self) -> tuple[np.ndarray, np.ndarray]:
        if self._cache is None:
            classes = [c for c in self.rows if self.rows[c]]
            self._cache = (np.vstack([np.vstack(self.rows[c]) for c in classes]),
                           np.concatenate([np.full(len(self.rows[c]), c, dtype=object) for c in classes]))
        return self._cache

    @property
    def x(self) -> np.ndarray:
        return self._arrays()[0]

    @property
    def y(self) -> np.ndarray:
        return self._arrays()[1]

    def counts(self) -> dict[str, int]:
        return {c: len(r) for c, r in self.rows.items() if r}


class Strategy:
    name = "base"

    def __init__(self, cfg: AdaptationConfig, engine: "ExperimentEngine"):
        self.cfg = cfg
        self.engine = engine

    def select(self, window: int, x: np.ndarray, out: dict) -> np.ndarray | None:
        """Flows of the just-predicted window to send to the analyst (None = uniform random sample)."""
        return None

    def step(self) -> None:
        raise NotImplementedError

    def _take_available_idx(self) -> list[tuple[int, np.ndarray, np.ndarray]]:
        """Like _take_available, but returns (window, indices within window, labels)."""
        e = self.engine
        out = []
        for w in e.oracle.available_windows(e.window):
            idx, y = e.oracle.take(w, e.window)
            if len(idx):
                out.append((w, idx, y))
        return out

    def _take_available(self, limit: int | None = None) -> list[tuple[int, np.ndarray, np.ndarray]]:
        e = self.engine
        windows = e.oracle.available_windows(e.window)
        if limit is not None:
            windows = windows[-limit:]
        out = []
        for w in windows:
            idx, y = e.oracle.take(w, e.window)
            if len(idx):
                out.append((w, e.window_x(w)[idx], y))
        return out


class StaticStrategy(Strategy):
    """Train once on the training period; never adapt, never consume labels."""

    name = "static"

    def step(self) -> None:
        return None


class PeriodicRetrainStrategy(Strategy):
    """Retrain from scratch every N windows on training data + recent labelled windows. Always deploys."""

    name = "periodic_retrain"

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        self.memory: deque[tuple[np.ndarray, np.ndarray]] = deque(maxlen=cfg.memory_windows)

    def step(self) -> None:
        e = self.engine
        for _, x, y in self._take_available():
            self.memory.append((x, y))
        if (e.window + 1) % self.cfg.retrain_every or not self.memory:
            return
        x = np.vstack([e.train_x, *(m[0] for m in self.memory)])
        y = np.concatenate([e.train_y, *(m[1] for m in self.memory)])
        cand = e.train(x, y)
        e.accept(cand, reason=f"scheduled retrain (every {self.cfg.retrain_every} windows)", trigger="schedule",
                 validation=e.validation_report(cand, None, None, passed=None))


class ContinualReplayStrategy(Strategy):
    """Experience replay: reservoir buffer seeded with training data, updated whenever labels arrive."""

    name = "continual_replay"

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        self.buffer = ReplayBuffer(cfg.buffer_size, engine.seed)
        self.buffer.add(engine.train_x, engine.train_y)

    def step(self) -> None:
        e = self.engine
        new = self._take_available()
        if not new:
            return
        for _, x, y in new:
            self.buffer.add(x, y)
        cand = e.train(self.buffer.x, self.buffer.y)
        e.accept(cand, reason="replay-buffer update on newly labelled data", trigger="new_labels",
                 validation=e.validation_report(cand, None, None, passed=None))


class GuardedSelectiveStrategy(Strategy):
    """Reference placeholder for the proposed method (see module docstring)."""

    name = "guarded_selective"

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        self.buffer = ReplayBuffer(cfg.buffer_size, engine.seed)
        self.buffer.add(engine.train_x, engine.train_y)
        self.watch: dict | None = None
        self.last_decision_window = -10**9

    def _check_rollback(self) -> None:
        e, w = self.engine, self.watch
        for _, x, y in self._take_available():
            self.buffer.add(x, y)
            if not self.cfg.rollback or e.previous is None:
                continue
            cur, prev = e.score(e.current, x, y), e.score(e.previous, x, y)
            if prev - cur > self.cfg.rollback_margin:
                e.rollback(
                    reason=f"post-deployment macro-F1 {cur:.3f} fell {prev - cur:.3f} below previous model",
                    trigger=w["trigger"],
                    validation={"deployed_f1": cur, "previous_f1": prev, "margin": self.cfg.rollback_margin},
                )
                self.watch = None
                return
        w["remaining"] -= 1
        if w["remaining"] <= 0:
            self.watch = None

    def step(self) -> None:
        e = self.engine
        if self.watch is not None and e.window > self.watch["deployed_at"]:
            self._check_rollback()

        triggers = [d["event_id"] for d in e.drift_events]
        if self.cfg.trigger == "drift_or_novelty" and e.unknown_rate >= self.cfg.novelty_trigger_rate:
            triggers.append(f"novelty@{e.window}(unknown_rate={e.unknown_rate:.2f})")
        if not triggers or self.watch is not None:
            return
        if e.window - self.last_decision_window <= self.cfg.rollback_watch_windows:
            return
        trigger = ",".join(triggers)
        self.last_decision_window = e.window

        labelled = self._take_available(limit=self.cfg.memory_windows)
        if not labelled:
            e.log_event("rejected", "no labelled windows available yet (label delay)", trigger,
                        e.current.version, None, {}, {})
            return
        # Chronological hold-out: the newest labelled window validates, older ones train.
        if len(labelled) >= 2:
            hold_x, hold_y = labelled[-1][1], labelled[-1][2]
            fresh = labelled[:-1]
        else:
            x, y = labelled[0][1], labelled[0][2]
            cut = int(len(y) * 0.7)
            hold_x, hold_y = x[cut:], y[cut:]
            fresh = [(labelled[0][0], x[:cut], y[:cut])]
        train_x = np.vstack([self.buffer.x, *(f[1] for f in fresh)])
        train_y = np.concatenate([self.buffer.y, *(f[2] for f in fresh)])

        cand = e.train(train_x, train_y)
        e.log_event("proposed", "drift/novelty trigger", trigger, e.current.version, cand.version, {},
                    e.cost(cand))
        report = e.validation_report(cand, hold_x, hold_y, passed=None)
        gain = report["recent_f1_candidate"] - report["recent_f1_current"]
        forget = report["ref_f1_current"] - report["ref_f1_candidate"]
        ref_ok = forget <= self.cfg.max_forgetting or not self.cfg.reference_guard
        passed = gain >= self.cfg.min_gain and ref_ok
        report.update(gain=gain, forgetting=forget, passed=passed, guard_enabled=self.cfg.validation_guard,
                      reference_guard=self.cfg.reference_guard,
                      drift_scores={d["method"]: {"score": d["score"], "threshold": d["threshold"]}
                                    for d in e.drift_events})

        for _, x, y in labelled:
            self.buffer.add(x, y)
        if passed or not self.cfg.validation_guard:
            reason = (f"gain {gain:+.3f} >= {self.cfg.min_gain}, forgetting {forget:.3f} <= {self.cfg.max_forgetting}"
                      if passed else "validation guard disabled (ablation)")
            e.accept(cand, reason=reason, trigger=trigger, validation=report)
            self.watch = {"deployed_at": e.window, "remaining": self.cfg.rollback_watch_windows, "trigger": trigger}
        else:
            e.reject(cand, reason=f"gain {gain:+.3f} vs min {self.cfg.min_gain}, forgetting {forget:.3f} vs max "
                                  f"{self.cfg.max_forgetting}", trigger=trigger, validation=report)


# ---------------------------------------------------------------------------------------------
# Published approaches, re-implemented under this protocol
# ---------------------------------------------------------------------------------------------


class UncertaintySamplingStrategy(ContinualReplayStrategy):
    """Least-confidence active learning: label the flows with the lowest max class probability. The
    standard query baseline in Chen et al. (USENIX Security 2023), OWAD (NDSS 2023) and NetGuard (2025),
    and INSOMNIA's "US + oracle" upper bound. Replay buffer, retrain per labelled window, always deploy."""

    name = "uncertainty_al"

    def select(self, window, x, out):
        k = self.engine.oracle.budget_for(window)
        return np.argsort(out["confidence"], kind="stable")[:k]


class NetGuardPriorSelectionStrategy(ContinualReplayStrategy):
    """NetGuard's density-aware prior selection (Gupta et al., 2025): fit one Gaussian mixture to the
    labelled memory and one to the new window, then label the flows with the largest
    log p_new(x) - log p_labelled(x) (typical of the new traffic, atypical of what is already labelled).
    The generative minority-class augmentation (RealTabFormer, GPU hours per cycle) is not reproduced."""

    name = "netguard_ps"
    FIT_ROWS = 10000

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        self.gmm_labelled = None

    def _gmm(self, x: np.ndarray):
        from sklearn.mixture import GaussianMixture

        rng = np.random.default_rng(self.engine.seed)
        if len(x) > self.FIT_ROWS:
            x = x[rng.choice(len(x), self.FIT_ROWS, replace=False)]
        k = max(1, min(self.cfg.netguard_components, len(x) // 50))
        # A component can collapse onto duplicate flows; retry with stronger regularisation (fits that succeed
        # first time are unchanged).
        for reg in (1e-3, 1e-2, 1e-1, 1.0):
            try:
                return GaussianMixture(k, covariance_type="diag", reg_covar=reg, max_iter=100,
                                       random_state=self.engine.seed).fit(x)
            except ValueError:
                sink = getattr(self.engine, "sink", None)
                if sink is not None:
                    sink.log(f"netguard_ps: mixture fit failed with reg_covar={reg:g}; retrying")
        return GaussianMixture(1, covariance_type="diag", reg_covar=1.0, random_state=self.engine.seed).fit(x)

    def select(self, window, x, out):
        if self.gmm_labelled is None:
            self.gmm_labelled = self._gmm(self.buffer.x)
        score = self._gmm(x).score_samples(x) - self.gmm_labelled.score_samples(x)
        k = self.engine.oracle.budget_for(window)
        return np.argsort(-score, kind="stable")[:k]

    def step(self):
        before = self.engine.current
        super().step()
        if self.engine.current is not before:
            self.gmm_labelled = None  # the labelled memory changed


class InsomniaStrategy(Strategy):
    """INSOMNIA (Andresini et al., ACM AISec 2021), multi-class: no analyst labels during deployment.
    After each window the share `insomnia_selection_rate` of least-confident flows is labelled by a
    nearest-centroid (NC) estimator built on the initial labelled data and refreshed with its own
    estimates; the model is then retrained on the original labels plus the estimates. Keeping the
    original labels mirrors the paper's guard against self-poisoning. Being label-free it can never
    learn a class that was absent from training."""

    name = "insomnia"

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        self.pseudo = ReplayBuffer(cfg.buffer_size, engine.seed)
        ty = engine.train_y.astype(str)
        self.classes = np.unique(ty)
        self.sums = np.vstack([engine.train_x[ty == c].sum(0, dtype=np.float64) for c in self.classes])
        self.counts = np.array([(ty == c).sum() for c in self.classes], dtype=np.float64)
        self.pending: tuple[np.ndarray, np.ndarray] | None = None

    def select(self, window, x, out):
        k = int(round(len(x) * self.cfg.insomnia_selection_rate))
        self.pending = (x, np.argsort(out["confidence"], kind="stable")[:k])
        return None  # no analyst labels

    def step(self):
        e = self.engine
        if self.pending is None:
            return
        x, idx = self.pending
        self.pending = None
        xs = np.asarray(x[idx], dtype=np.float64)
        cents = self.sums / self.counts[:, None]
        d2 = (xs ** 2).sum(1)[:, None] - 2.0 * xs @ cents.T + (cents ** 2).sum(1)[None, :]
        est = d2.argmin(axis=1)
        for i in range(len(self.classes)):
            m = est == i
            self.sums[i] += xs[m].sum(0)
            self.counts[i] += m.sum()
        self.pseudo.add(x[idx], self.classes[est].astype(object))
        cand = e.train(np.vstack([e.train_x, self.pseudo.x]), np.concatenate([e.train_y, self.pseudo.y]))
        e.accept(cand, reason=f"self-training on {len(idx)} NC-estimated labels (no analyst labels)",
                 trigger="window", validation=e.validation_report(cand, None, None, passed=None))


class CBRSReplayStrategy(ContinualReplayStrategy):
    """Continual learning with a class-balanced replay memory (CBRS; the memory behind ECBRS in
    Amalapuram et al., NeurIPS 2023), uniformly sampled labels, retrain per labelled window."""

    name = "cbrs_replay"

    def __init__(self, cfg, engine):
        Strategy.__init__(self, cfg, engine)
        self.buffer = ClassBalancedBuffer(cfg.buffer_size, engine.seed)
        self.buffer.add(engine.train_x, engine.train_y)


# ---------------------------------------------------------------------------------------------
# Proposed method
# ---------------------------------------------------------------------------------------------


def novelty_diverse_selection(x: np.ndarray, score: np.ndarray, k: int, random_fraction: float,
                              n_clusters: int, seed: int) -> np.ndarray:
    """Pick k flows: a uniform share (keeps an unbiased view of benign drift) plus a novelty-weighted,
    cluster-stratified share. Clusters receive quota proportional to sqrt(size) * (0.1 + mean novelty),
    at least one each, so every emerging traffic mode gets labels; inside a cluster the most novel
    flows go first."""
    n = len(x)
    k = min(k, n)
    if k <= 0:
        return np.empty(0, dtype=np.int64)
    rng = np.random.default_rng(seed)
    n_rand = int(round(k * random_fraction))
    chosen = rng.choice(n, n_rand, replace=False) if n_rand else np.empty(0, dtype=np.int64)
    rest = k - n_rand
    if rest <= 0:
        return np.sort(chosen)
    acq = np.clip(np.nan_to_num(np.asarray(score, float), nan=0.0, posinf=5.0), 0.0, 5.0)
    pool = np.setdiff1d(np.arange(n), chosen)
    m = min(n_clusters, rest, len(pool))
    if m <= 1:
        return np.sort(np.concatenate([chosen, pool[np.argsort(-acq[pool], kind="stable")[:rest]]]))
    from sklearn.cluster import KMeans

    lab = KMeans(m, n_init=1, max_iter=50, random_state=seed % (2**31)).fit_predict(np.asarray(x[pool], np.float32))
    sizes = np.bincount(lab, minlength=m)
    mean_acq = np.array([acq[pool][lab == c].mean() if sizes[c] else 0.0 for c in range(m)])
    weight = np.sqrt(sizes) * (0.1 + mean_acq)
    quota = np.minimum(np.ones(m, dtype=int), sizes)
    left = rest - int(quota.sum())
    if left > 0:
        share = weight / weight.sum() * left
        extra = np.floor(share).astype(int)
        for c in np.argsort(-(share - extra), kind="stable")[: left - int(extra.sum())]:
            extra[c] += 1
        quota = np.minimum(quota + extra, sizes)
    picked = [pool[lab == c][np.argsort(-acq[pool[lab == c]], kind="stable")[:quota[c]]] for c in range(m)]
    picked = np.concatenate(picked)
    if len(picked) < rest:  # clusters too small for their quota: fill with the most novel leftovers
        left_pool = np.setdiff1d(pool, picked)
        picked = np.concatenate([picked, left_pool[np.argsort(-acq[left_pool], kind="stable")[:rest - len(picked)]]])
    return np.sort(np.concatenate([chosen, picked[:rest]]))


def propagate_labels(xw: np.ndarray, lab_idx: np.ndarray, lab_y: np.ndarray, k: int,
                     max_ratio: float) -> tuple[np.ndarray, np.ndarray]:
    """Conservative label propagation inside one window (analyst labels -> unlabelled neighbours).

    An unlabelled flow takes the class c of its nearest labelled flow when (1) its min(k, n_c) nearest
    labelled flows all have class c and (2) that nearest distance is within c's radius: the 90th
    percentile of nearest-same-class distances among c's labelled flows. At most max_ratio pseudo
    labels per analyst label of c are kept, closest first. Classes with a single label do not spread.
    """
    empty = np.empty(0, dtype=np.int64), np.empty(0, dtype=object)
    n = len(xw)
    unl = np.setdiff1d(np.arange(n), lab_idx)
    if len(unl) == 0 or len(lab_idx) < 2 or max_ratio <= 0:
        return empty
    lab_y = np.asarray(lab_y).astype(str)
    L = np.asarray(xw[lab_idx], np.float32)
    U = np.asarray(xw[unl], np.float32)
    l2 = np.einsum("ij,ij->i", L, L)
    d_ul = np.sqrt(np.maximum(np.einsum("ij,ij->i", U, U)[:, None] - 2.0 * U @ L.T + l2[None, :], 0.0))
    d_ll = np.sqrt(np.maximum(l2[:, None] - 2.0 * L @ L.T + l2[None, :], 0.0))
    np.fill_diagonal(d_ll, np.inf)
    kk = min(k, len(lab_idx))
    order = np.argsort(d_ul, axis=1, kind="stable")[:, :kk]
    nn_lab = lab_y[order]
    d1 = d_ul[np.arange(len(unl)), order[:, 0]]
    take_idx, take_y = [], []
    for c in np.unique(lab_y):
        members = np.flatnonzero(lab_y == c)
        if len(members) < 2:
            continue
        radius = float(np.quantile(d_ll[np.ix_(members, members)].min(axis=1), 0.9))
        need = min(kk, len(members))
        ok = (nn_lab[:, :need] == c).all(axis=1) & (d1 <= radius)
        cand = np.flatnonzero(ok)
        cand = cand[np.argsort(d1[cand], kind="stable")[: int(max_ratio * len(members))]]
        take_idx.append(unl[cand])
        take_y.append(np.full(len(cand), c, dtype=object))
    if not take_idx:
        return empty
    return np.concatenate(take_idx), np.concatenate(take_y)


class NovaStrategy(Strategy):
    """NOVA: Novelty-aware, Open-world, Validated Adaptation (proposed).

    1. Query: novelty-weighted, cluster-diverse selection of the label budget (plus a uniform share),
       instead of uniform or pure-uncertainty sampling.
    2. Propagation: analyst labels spread to agreeing, nearby flows of the same window.
    3. Memory: class-balanced reservoir (benign weighted) so rare and new attack classes survive.
    4. Guard: a candidate trained on memory + new labels is deployed only if it is at least as good as
       the current model on a held-out slice of the newest analyst labels and does not forget the
       reference set; a deployed model is rolled back if the next labels show it is worse.
    Each switch (active_selection, propagate, class_balanced_memory, validation_guard,
    reference_guard, rollback) can be turned off for ablations.
    """

    name = "nova"

    def __init__(self, cfg, engine):
        super().__init__(cfg, engine)
        if cfg.class_balanced_memory:
            self.memory = ClassBalancedBuffer(cfg.buffer_size, engine.seed,
                                              {b: cfg.benign_weight for b in engine.benign})
        else:
            self.memory = ReplayBuffer(cfg.buffer_size, engine.seed)
        self.memory.add(engine.train_x, engine.train_y)
        self.rng = np.random.default_rng(engine.seed + 7919)
        self.watch: dict | None = None
        # Held-out analyst labels, never trained on, used to calibrate open-world thresholds of later models.
        self.calib: dict[str, list[np.ndarray]] = {}

    def _calib_arrays(self) -> tuple[np.ndarray, np.ndarray] | None:
        rows = [(c, r) for c, rs in self.calib.items() for r in rs]
        if not rows:
            return None
        return np.vstack([r for _, r in rows]), np.array([c for c, _ in rows], dtype=object)

    def _keep_for_calibration(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Move hold-out flows into the calibration store while their class has room and is already
        well represented in training memory (a new, rare class must be learned first); returns the mask
        of flows that were NOT kept (those go to the training memory)."""
        rest = np.ones(len(y), bool)
        in_memory = dict(zip(*np.unique(self.memory.y.astype(str), return_counts=True)))
        for i, c in enumerate(np.asarray(y).astype(str)):
            if in_memory.get(c, 0) < self.cfg.calib_min_train:
                continue
            store = self.calib.setdefault(c, [])
            if len(store) < self.cfg.calib_per_class:
                store.append(x[i])
                rest[i] = False
        return rest

    def select(self, window, x, out):
        if not self.cfg.active_selection:
            return None
        return novelty_diverse_selection(x, out["unknown_score"], self.engine.oracle.budget_for(window),
                                         self.cfg.random_fraction, self.cfg.select_clusters,
                                         self.engine.seed * 1009 + window)

    def _split_holdout(self, y: np.ndarray) -> np.ndarray:
        """Boolean mask of a stratified hold-out (classes with >= 4 labels contribute)."""
        hold = np.zeros(len(y), bool)
        if self.cfg.holdout_fraction <= 0:
            return hold
        for c in np.unique(y):
            members = np.flatnonzero(y == c)
            if len(members) >= 4:
                take = max(1, int(round(len(members) * self.cfg.holdout_fraction)))
                hold[self.rng.choice(members, take, replace=False)] = True
        return hold

    def _check_rollback(self, x: np.ndarray, y: np.ndarray) -> None:
        e, w = self.engine, self.watch
        if self.cfg.rollback and e.previous is not None and len(y):
            ms = self.cfg.min_support
            cur, prev = e.score(e.current, x, y, ms), e.score(e.previous, x, y, ms)
            # A rollback is a deployment too: the restored model must pass the same reference check.
            ref_ok = (not self.cfg.reference_guard
                      or e.ref_score(e.current) - e.ref_score(e.previous) <= self.cfg.max_forgetting)
            if prev - cur > self.cfg.rollback_margin and ref_ok:
                e.rollback(reason=f"post-deployment macro-F1 {cur:.3f} fell {prev - cur:.3f} below previous model",
                           trigger=w["trigger"],
                           validation={"deployed_f1": cur, "previous_f1": prev, "margin": self.cfg.rollback_margin,
                                       "ref_f1_deployed": e.ref_score(e.current),
                                       "ref_f1_previous": e.ref_score(e.previous)})
                self.watch = None
                return
        w["remaining"] -= 1
        if w["remaining"] <= 0:
            self.watch = None

    def step(self):
        e = self.engine
        new = self._take_available_idx()
        if not new:
            return
        xs = np.vstack([e.window_x(w)[idx] for w, idx, _ in new])
        ys = np.concatenate([np.asarray(y).astype(str) for _, _, y in new]).astype(object)
        if self.watch is not None and e.window > self.watch["deployed_at"]:
            self._check_rollback(xs, ys)

        hold = self._split_holdout(ys.astype(str)) if self.cfg.validation_guard else np.zeros(len(ys), bool)
        px, py = [], []
        if self.cfg.propagate:
            offset = 0
            for w, idx, y in new:
                keep = ~hold[offset:offset + len(idx)]
                offset += len(idx)
                pi, pl = propagate_labels(e.window_x(w), idx[keep], np.asarray(y)[keep], self.cfg.propagate_k,
                                          self.cfg.propagate_max_ratio)
                if len(pi):
                    px.append(e.window_x(w)[pi])
                    py.append(pl)
        pseudo_x = np.vstack(px) if px else np.empty((0, xs.shape[1]), xs.dtype)
        pseudo_y = np.concatenate(py) if py else np.empty(0, dtype=object)

        trigger = "labels@" + ",".join(str(w) for w, _, _ in new)
        mem_x, mem_y = self.memory.x, self.memory.y
        n_new = int((~hold).sum()) + len(pseudo_y)
        weight = np.r_[np.ones(len(mem_y)), np.full(n_new, self.cfg.recent_weight)]
        cand = e.train(np.vstack([mem_x, xs[~hold], pseudo_x]), np.concatenate([mem_y, ys[~hold], pseudo_y]),
                       calib=self._calib_arrays(), sample_weight=weight if self.cfg.recent_weight != 1 else None)
        e.log_event("proposed", f"{int((~hold).sum())} analyst + {len(pseudo_y)} propagated labels", trigger,
                    e.current.version, cand.version, {}, e.cost(cand))
        if self.cfg.validation_guard and hold.any():
            report = e.validation_report(cand, xs[hold], ys[hold], passed=None, min_support=self.cfg.min_support)
            gain = report["recent_f1_candidate"] - report["recent_f1_current"]
        else:
            report = e.validation_report(cand, None, None, passed=None)
            gain = 0.0
        forget = report["ref_f1_current"] - report["ref_f1_candidate"]
        ref_ok = forget <= self.cfg.max_forgetting or not self.cfg.reference_guard
        passed = gain >= self.cfg.min_gain and ref_ok
        report.update(gain=gain, forgetting=forget, passed=passed, analyst_labels=int(len(ys)),
                      propagated_labels=int(len(pseudo_y)), guard_enabled=self.cfg.validation_guard,
                      reference_guard=self.cfg.reference_guard)
        # After the decision the hold-out tops up the calibration store; everything else (and the
        # propagated labels) goes to the training memory.
        to_memory = ~hold
        if hold.any():
            hold_idx = np.flatnonzero(hold)
            to_memory[hold_idx[self._keep_for_calibration(xs[hold], ys[hold])]] = True
        self.memory.add(xs[to_memory], ys[to_memory])
        self.memory.add(pseudo_x, pseudo_y)
        if passed or not self.cfg.validation_guard:
            reason = (f"gain {gain:+.3f} >= {self.cfg.min_gain}, forgetting {forget:+.3f} <= {self.cfg.max_forgetting}"
                      if self.cfg.validation_guard else "validation guard disabled (ablation)")
            e.accept(cand, reason=reason, trigger=trigger, validation=report)
            self.watch = {"deployed_at": e.window, "remaining": self.cfg.rollback_watch_windows, "trigger": trigger}
        else:
            e.reject(cand, reason=f"gain {gain:+.3f} vs min {self.cfg.min_gain}, forgetting {forget:+.3f} vs max "
                                  f"{self.cfg.max_forgetting}", trigger=trigger, validation=report)


STRATEGIES: dict[str, type[Strategy]] = {
    s.name: s for s in (StaticStrategy, PeriodicRetrainStrategy, ContinualReplayStrategy, GuardedSelectiveStrategy,
                        UncertaintySamplingStrategy, InsomniaStrategy, NetGuardPriorSelectionStrategy,
                        CBRSReplayStrategy, NovaStrategy)
}
