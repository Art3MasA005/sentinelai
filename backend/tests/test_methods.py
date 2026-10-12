"""Proposed method (nova), the re-implemented literature baselines and their building blocks."""

import numpy as np
import pytest

from app.ml import metrics as M
from app.ml.labels import LabelOracle
from app.ml.openworld import OpenWorldScorer
from app.ml.pipeline import ExperimentEngine
from app.ml.strategies import ClassBalancedBuffer, novelty_diverse_selection, propagate_labels
from app.schemas.experiments import ExperimentConfig, LabelPolicy, OpenWorldConfig
from app.services import datasets as ds
from tests.test_pipeline import MemorySink, digest


def run(env, openworld="msp+knn", **adaptation):
    cfg = ExperimentConfig.model_validate({
        "name": "test", "dataset_id": "DEMO_sentinel_synthetic", "seed": 11,
        "split": {"train_fraction": 0.3, "val_fraction": 0.2, "window_size": 300},
        "openworld": {"method": openworld, "knn_k": 5, "knn_bank_per_class": 500},
        "labels": {"delay_windows": 1, "budget": 0.2},
        "adaptation": {"buffer_size": 3000, **adaptation},
    })
    d = ds.resolve(env.datasets_dir, cfg.dataset_id)
    sink = MemorySink()
    ExperimentEngine(cfg, d.files, ds.pick_profile(d, None, None), d.data_origin, sink).run()
    return sink


# ---------- oracle ----------

def test_oracle_request_is_capped_by_budget_and_respects_delay():
    labels = [np.array([f"c{i % 3}" for i in range(100)], dtype=object) for _ in range(4)]
    o = LabelOracle(labels, LabelPolicy(delay_windows=1, budget=0.1), seed=1)
    with pytest.raises(PermissionError):
        o.request(0, np.arange(11))  # budget is 10
    o.request(0, [5, 3, 3, 7])  # duplicates collapse
    with pytest.raises(PermissionError):
        o.take(0, 0)  # delay
    idx, y = o.take(0, 1)
    assert idx.tolist() == [3, 5, 7] and y.tolist() == ["c0", "c2", "c1"]
    assert o.labels_used == 3
    with pytest.raises(PermissionError):
        o.request(0, [1])  # already taken
    idx, _ = o.take(1, 2)  # not requested -> uniform sample of the full budget
    assert len(idx) == 10


# ---------- memory ----------

def test_class_balanced_buffer_keeps_rare_classes_and_weights_benign():
    rng = np.random.default_rng(0)
    y = np.array(["BENIGN"] * 5000 + ["A"] * 50 + ["B"] * 1000, dtype=object)
    x = rng.normal(size=(len(y), 3))
    order = rng.permutation(len(y))
    buf = ClassBalancedBuffer(600, seed=0, weights={"BENIGN": 2.0})
    buf.add(x[order], y[order])
    c = buf.counts()
    assert sum(c.values()) == 600 == len(buf.y) == len(buf.x)
    assert c["A"] == 50  # a rare class is never evicted
    assert abs(c["BENIGN"] - 2 * c["B"]) <= 2  # benign holds two shares
    # rows stay aligned with labels
    lookup = {tuple(np.round(r, 9)): lab for r, lab in zip(x, y)}
    assert all(lookup[tuple(np.round(r, 9))] == lab for r, lab in zip(buf.x, buf.y))


# ---------- query + propagation ----------

def test_novelty_diverse_selection_is_exact_unique_and_covers_novel_cluster():
    rng = np.random.default_rng(1)
    normal = rng.normal(0, 1, size=(950, 4))
    novel = rng.normal(8, 0.3, size=(50, 4))
    x = np.vstack([normal, novel])
    score = np.r_[rng.uniform(0, 0.8, 950), rng.uniform(1.5, 3, 50)]
    pick = novelty_diverse_selection(x, score, k=40, random_fraction=0.25, n_clusters=8, seed=3)
    assert len(pick) == 40 == len(np.unique(pick))
    # The novel mode is 5% of the window (2 of 40 labels if uniform); novelty weighting gives it far more.
    assert (pick >= 950).sum() >= 6
    assert np.array_equal(pick, novelty_diverse_selection(x, score, 40, 0.25, 8, seed=3))


def test_propagation_only_labels_agreeing_close_neighbours():
    rng = np.random.default_rng(2)
    a = rng.normal(0, 0.2, size=(100, 2))
    b = rng.normal(5, 0.2, size=(100, 2))
    far = np.array([[20.0, 20.0]])
    x = np.vstack([a, b, far])
    lab_idx = np.r_[0:10, 100:110]
    lab_y = np.array(["A"] * 10 + ["B"] * 10, dtype=object)
    idx, y = propagate_labels(x, lab_idx, lab_y, k=3, max_ratio=3.0)
    assert len(idx) and not set(idx) & set(lab_idx)
    truth = np.where(idx < 100, "A", "B")
    assert (y == truth).all()  # never crosses clusters
    assert 200 not in idx  # an outlier is not labelled
    assert (y == "A").sum() <= 30 and (y == "B").sum() <= 30  # capped at max_ratio per class


# ---------- open-world ----------

class _Clf:
    classes_ = np.array(["A", "B"])

    def predict_proba(self, x):
        p = 1 / (1 + np.exp(-(x[:, 0] - 2.5) * 4))
        return np.c_[1 - p, p]


def test_knn_scorer_flags_far_flows_and_threshold_is_at_one():
    rng = np.random.default_rng(3)
    xa = np.c_[rng.normal(0, 1, 2000), rng.normal(0, 1, 2000)]
    xb = np.c_[rng.normal(5, 1, 2000), rng.normal(0, 1, 2000)]
    x = np.vstack([xa, xb]).astype(np.float32)
    y = np.array(["A"] * 2000 + ["B"] * 2000, dtype=object)
    sc = OpenWorldScorer(OpenWorldConfig(method="knn", knn_k=5, knn_bank_per_class=500), seed=0)
    sc.fit(_Clf(), x[::2], y[::2], x[1::2], y[1::2])
    test = np.array([[0.0, 0.0], [5.0, 0.0], [0.0, 30.0]], dtype=np.float32)
    p = _Clf().predict_proba(test)
    unknown, reason, novelty, score = sc.score(test, p.max(1), p.argmax(1))
    assert unknown.tolist() == [False, False, True]
    assert reason[2] == "far_from_known"
    assert ((score > 1.0) == unknown).all() and score[2] > 3


def test_open_world_credit_metrics():
    true = np.array(["BENIGN", "BENIGN", "X", "X", "Y"], dtype=object)
    dec = np.array(["BENIGN", "UNKNOWN", "UNKNOWN", "BENIGN", "Y"], dtype=object)
    novel = np.array([False, False, True, True, False])
    # X is unknown to the model, so UNKNOWN on an X flow is credited; on a BENIGN flow it is not.
    assert M.open_world_credit(true, dec, novel).tolist() == ["BENIGN", "UNKNOWN", "X", "BENIGN", "Y"]
    d = M.detection(true, dec, {"BENIGN"})
    assert d["detect_recall"] == pytest.approx(2 / 3) and d["detect_fpr"] == pytest.approx(0.5)


# ---------- strategies end to end ----------

@pytest.mark.parametrize("method", ["uncertainty_al", "netguard_ps", "cbrs_replay", "insomnia", "nova"])
def test_new_strategies_run_and_respect_label_budget(env, method):
    s = run(env, method=method)
    o = s.summary["overall"]
    stream = s.summary["flows"]
    if method == "insomnia":
        assert o["labels_used"] == 0
    else:
        assert 0 < o["labels_used"] <= int(np.ceil(0.2 * stream)) + len(s.windows)
    for k in ("macro_f1_ow", "detect_f1", "unknown_auroc"):
        assert o[k] is None or 0.0 <= o[k] <= 1.0


def test_nova_is_reproducible_and_logs_guard_decisions(env):
    a, b = run(env, method="nova"), run(env, method="nova")
    assert digest(a) == digest(b)
    decided = [x for x in a.adapt if x["decision"] in ("accepted", "rejected")]
    assert decided
    v = decided[0]["validation"]
    assert {"gain", "forgetting", "analyst_labels", "propagated_labels"} <= set(v)
    # Deployments, rollbacks included, never trade more than max_forgetting of reference macro-F1.
    for x in a.adapt:
        if x["decision"] == "rollback":
            r = x["validation"]
            assert r["ref_f1_deployed"] - r["ref_f1_previous"] <= 0.05 + 1e-9
        elif x["decision"] == "accepted":
            assert x["validation"]["forgetting"] <= 0.05 + 1e-9


def test_nova_ablation_switches_change_behaviour(env):
    full = run(env, method="nova")
    no_guard = run(env, method="nova", validation_guard=False)
    assert all(x["decision"] != "rejected" for x in no_guard.adapt)
    passive = run(env, method="nova", active_selection=False, propagate=False)
    props = [x["validation"].get("propagated_labels") for x in passive.adapt if x["decision"] == "accepted"]
    assert props and all(p == 0 for p in props)
    assert digest(full) != digest(passive)
