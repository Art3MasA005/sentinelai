"""Metrics are checked against hand-computed values and, independently, against scikit-learn."""

import numpy as np
import pytest
from sklearn.metrics import average_precision_score, f1_score, recall_score

from app.ml import metrics as M


def test_macro_f1_hand_computed():
    y_true = ["A", "A", "A", "B", "B", "UNKNOWN"]
    y_pred = ["A", "A", "B", "B", "UNKNOWN", "UNKNOWN"]
    # A: tp2 fp0 fn1 -> 4/5 ; B: tp1 fp1 fn1 -> 2/4 ; UNKNOWN: tp1 fp1 fn0 -> 2/3
    assert M.macro_f1(y_true, y_pred) == pytest.approx((0.8 + 0.5 + 2 / 3) / 3)


def test_macro_f1_ignores_classes_absent_from_truth():
    # UNKNOWN predicted but never true: it must not add a 0 term, only cost recall of A.
    y_true = ["A", "A", "B", "B"]
    y_pred = ["A", "UNKNOWN", "B", "B"]
    assert M.macro_f1(y_true, y_pred) == pytest.approx((2 / 3 + 1.0) / 2)


def test_macro_f1_matches_sklearn_on_random_data():
    rng = np.random.default_rng(0)
    labels = np.array(["BENIGN", "DoS", "Scan", "UNKNOWN"])
    for _ in range(20):
        t = labels[rng.integers(0, 4, 300)]
        p = labels[rng.integers(0, 4, 300)]
        present = sorted(set(t))
        ref = f1_score(t, p, labels=present, average="macro", zero_division=0)
        assert M.macro_f1(t, p) == pytest.approx(ref)
        rec = recall_score(t, p, labels=present, average=None, zero_division=0)
        assert [M.per_class_recall(t, p)[c] for c in present] == pytest.approx(list(rec))


def test_fpr_excludes_unknown_reviews():
    t = ["BENIGN"] * 4 + ["DoS"]
    p = ["BENIGN", "DoS", "UNKNOWN", "BENIGN", "DoS"]
    assert M.false_positive_rate(t, p, {"BENIGN"}) == pytest.approx(1 / 4)
    assert M.benign_review_rate(t, p, {"BENIGN"}) == pytest.approx(1 / 4)
    assert M.false_positive_rate(["DoS"], ["DoS"], {"BENIGN"}) is None


@pytest.mark.parametrize("seed", range(10))
def test_average_precision_matches_sklearn_including_ties(seed):
    rng = np.random.default_rng(seed)
    y = rng.random(200) < 0.3
    s = np.round(rng.random(200), 1)  # many ties
    assert M.average_precision(y, s) == pytest.approx(average_precision_score(y, s))


def test_average_precision_hand_computed():
    # scores desc: 0.9(+) 0.8(-) 0.7(+) -> AP = 0.5*1 + 0.5*(2/3)
    assert M.average_precision([1, 0, 1], [0.9, 0.8, 0.7]) == pytest.approx(0.5 + 1 / 3)
    assert M.average_precision([1, 1], [0.2, 0.3]) is None


def test_unknown_rates():
    novel = [True, True, False, False, False]
    unk = [True, False, True, False, False]
    assert M.unknown_recall(novel, unk) == 0.5
    assert M.known_false_unknown_rate(novel, unk) == pytest.approx(1 / 3)
    assert M.unknown_recall([False], [True]) is None


def test_forgetting():
    assert M.forgetting([0.8, 0.9, 0.7, 0.85]) == (pytest.approx(0.2), pytest.approx(0.05))
    assert M.forgetting([]) == (0.0, 0.0)


def test_evaluate_maps_novel_classes_to_unknown():
    true = np.array(["BENIGN", "Exfil", "Exfil", "DoS"])
    dec = np.array(["BENIGN", "UNKNOWN", "BENIGN", "DoS"], dtype=object)
    unk = np.array([False, True, False, False])
    novel = np.array([False, True, True, False])
    out = M.evaluate(true, dec, unk, novel, np.array([0.1, 0.9, 0.2, 0.95]), {"BENIGN"})
    assert out["per_class_recall"]["UNKNOWN"] == 0.5
    assert out["unknown_recall"] == 0.5
    assert out["fpr"] == 0.0


@pytest.mark.parametrize("seed", range(5))
def test_roc_auc_and_precision_match_sklearn(seed):
    from sklearn.metrics import precision_score, roc_auc_score

    rng = np.random.default_rng(seed)
    y = rng.random(300) < 0.2
    s = np.round(rng.random(300) + y * 0.3, 1)  # ties
    assert M.roc_auc(y, s) == pytest.approx(roc_auc_score(y, s))
    assert M.roc_auc([True, True], [0.1, 0.2]) is None
    labels = np.array(["A", "B", "C"])
    t, p = labels[rng.integers(0, 3, 200)], labels[rng.integers(0, 3, 200)]
    ref = precision_score(t, p, labels=sorted(set(t)), average=None, zero_division=0)
    assert [M.per_class_precision(t, p)[c] for c in sorted(set(t))] == pytest.approx(list(ref))
