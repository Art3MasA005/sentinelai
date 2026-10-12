import numpy as np
import pandas as pd
import pytest

from app.ml.data import load_dataset, validate_files
from app.ml.labels import LabelOracle
from app.ml.preprocessing import Preprocessor
from app.ml.profiles import get_profile
from app.schemas.experiments import LabelPolicy

PROFILE = get_profile("sentinel_demo")


def _csv(tmp_path, df, name="d.csv"):
    p = tmp_path / name
    df.to_csv(p, index=False)
    return p


def _frame(n=50):
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "timestamp": 1_700_000_000 + rng.permutation(n),
        "protocol": rng.choice(["TCP", "UDP"], n),
        "duration": rng.random(n), "fwd_pkts": rng.integers(1, 9, n), "bwd_pkts": rng.integers(0, 9, n),
        "label": rng.choice(["BENIGN", "DoS"], n), "is_demo": 1,
    })


def test_validation_reports_missing_columns(tmp_path):
    p = _csv(tmp_path, _frame().drop(columns=["fwd_pkts", "label"]))
    r = validate_files("x", [p], PROFILE, is_demo=True)
    assert not r.valid
    assert set(r.missing_columns) == {"fwd_pkts", "label"}


def test_validation_reports_invalid_numeric_column(tmp_path):
    df = _frame()
    df["duration"] = df["duration"].astype(object)
    df.loc[:10, "duration"] = "oops"
    r = validate_files("x", [_csv(tmp_path, df)], PROFILE, is_demo=True)
    assert not r.valid
    assert [i.column for i in r.invalid_columns] == ["duration"]
    assert r.invalid_columns[0].examples == ["oops"]


def test_validation_detects_bad_timestamps_and_disorder(tmp_path):
    df = _frame()
    df["timestamp"] = df["timestamp"].astype(object)
    df.loc[:9, "timestamp"] = "not-a-time"
    r = validate_files("x", [_csv(tmp_path, df)], PROFILE, is_demo=True)
    assert r.timestamp_parse_failures == 10
    assert not r.valid
    assert r.out_of_order_fraction > 0


def test_valid_dataset_passes(tmp_path):
    r = validate_files("x", [_csv(tmp_path, _frame())], PROFILE, is_demo=True)
    assert r.valid, r.errors
    assert r.data_origin == "demo"
    assert len(r.sha256) == 64


def test_load_is_chronological_and_stable(tmp_path):
    df = _frame(200)
    df.loc[5:9, "timestamp"] = df.loc[5, "timestamp"]  # ties keep file order
    d = load_dataset([_csv(tmp_path, df)], PROFILE)
    assert np.all(np.diff(d.timestamps) >= 0)
    tie_rows = d.row_index[d.timestamps == df.loc[5, "timestamp"]]
    assert list(tie_rows) == sorted(tie_rows)
    thinned = load_dataset([_csv(tmp_path, df)], PROFILE, max_rows=100)
    assert len(thinned.labels) == 100 and np.all(np.diff(thinned.timestamps) >= 0)


def test_preprocessor_fits_on_training_rows_only():
    train = pd.DataFrame({"a": [1.0, 2.0, 3.0], "c": ["x", "x", "y"]})
    later = pd.DataFrame({"a": [1000.0, np.inf], "c": ["z", "x"]})
    pre = Preprocessor(["a"], ["c"]).fit(train)
    expected = np.log1p(np.array([1.0, 2.0, 3.0]))
    assert pre.fitted_rows == 3
    assert pre.mean[0] == pytest.approx(expected.mean())
    out = pre.transform(later)
    assert np.isfinite(out).all()
    assert out[0, -1] == 1.0  # unseen category -> <other>
    assert pre.mean[0] == pytest.approx(expected.mean())  # transform never refits


def test_label_oracle_enforces_delay_and_budget():
    windows = [np.array(["A"] * 10), np.array(["B"] * 10), np.array(["C"] * 10)]
    o = LabelOracle(windows, LabelPolicy(delay_windows=1, budget=0.5), seed=1)
    assert o.available_windows(0) == []
    with pytest.raises(PermissionError):
        o.take(1, current_window=1)
    idx, y = o.take(0, current_window=1)
    assert len(idx) == 5 and set(y) == {"A"}
    assert o.take(0, current_window=2)[0].size == 0  # cannot take twice
    assert o.labels_used == 5
