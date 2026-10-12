import hashlib

import numpy as np
import pytest

from app.ml.pipeline import ExperimentEngine
from app.services import datasets as ds
from tests.conftest import small_config


class MemorySink:
    def __init__(self):
        self.flows, self.windows, self.drift, self.adapt, self.models = [], [], [], [], {}
        self.summary = None

    def log(self, message): pass
    def progress(self, *a): pass
    def control(self): return "run"
    def ack_step(self): pass
    def set_paused(self, paused): pass
    def write_model(self, model, status): self.models[model.version] = status
    def set_model_status(self, version, status): self.models[version] = status

    def write_window(self, window, flows, drift_events, adaptation_events):
        self.windows.append(window)
        self.flows += flows
        self.drift += drift_events
        self.adapt += adaptation_events

    def finish(self, summary): self.summary = summary


def run(env, **adaptation):
    cfg = small_config(**adaptation)
    d = ds.resolve(env.datasets_dir, cfg.dataset_id)
    sink = MemorySink()
    ExperimentEngine(cfg, d.files, ds.pick_profile(d, None, None), d.data_origin, sink).run()
    return sink


def digest(sink):
    h = hashlib.sha256()
    for f in sink.flows:
        h.update(f"{f['flow_id']}|{f['decision']}|{f['confidence']:.12f}|{f['model_version']}".encode())
    for a in sink.adapt:
        h.update(f"{a['event_id']}|{a['decision']}|{a['to_version']}".encode())
    return h.hexdigest()


@pytest.mark.parametrize("method", ["static", "guarded_selective"])
def test_replay_is_reproducible(env, method):
    assert digest(run(env, method=method)) == digest(run(env, method=method))


def test_replay_is_chronological_and_split_is_clean(env):
    s = run(env, method="static")
    ts = np.array([f["ts"] for f in s.flows])
    assert np.all(np.diff(ts) >= 0)
    assert [w["window"] for w in s.windows] == list(range(len(s.windows)))
    integ = s.summary["integrity"]
    assert integ["chronological_split"]
    assert integ["preprocessor_fitted_rows"] == s.summary["split"]["train_rows"]
    assert s.summary["data_origin"] == "demo"
    assert all(f["src"] and f["dst"] and f["protocol"] in ("TCP", "UDP") for f in s.flows[:50])
    assert len(s.summary["feature_names"]) == s.summary["n_features"]


def test_db_migration_adds_new_columns(tmp_path):
    import sqlite3

    from app.storage.db import init_db

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as c:  # first-release flows table without src/dst/protocol
        c.execute("CREATE TABLE flows (run_id TEXT, flow_id INTEGER, window INTEGER, decision TEXT, "
                  "is_unknown INTEGER, PRIMARY KEY (run_id, flow_id))")
    init_db(db)
    with sqlite3.connect(db) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(flows)")}
    assert {"src", "dst", "protocol"} <= cols


def test_static_consumes_no_labels_and_never_adapts(env):
    s = run(env, method="static")
    assert s.summary["overall"]["labels_used"] == 0
    assert s.adapt == []
    assert len({f["model_version"] for f in s.flows}) == 1


def test_novel_class_is_flagged_and_events_are_traceable(env):
    s = run(env, method="guarded_selective")
    novel = [f for f in s.flows if f["is_novel_class"]]
    assert novel, "demo stream must contain a class unseen in training"
    assert s.summary["overall"]["unknown_recall"] > 0.5
    for d in s.drift:
        assert {"method", "score", "threshold", "window", "window_start", "window_end", "detected_at"} <= d.keys()
        assert d["score"] > d["threshold"]
    for a in s.adapt:
        assert {"decision", "reason", "from_version", "to_version", "validation", "cost"} <= a.keys()
    accepted = {a["to_version"] for a in s.adapt if a["decision"] == "accepted"}
    # A model accepted at window w is only used from window w+1 on (no look-ahead).
    for a in s.adapt:
        if a["decision"] == "accepted":
            used = [f["window"] for f in s.flows if f["model_version"] == a["to_version"]]
            assert not used or min(used) > a["window"]
    assert accepted <= set(s.models)


def test_holdout_classes_are_removed_from_training(env):
    cfg = small_config(method="static")
    cfg.split.holdout_classes = ["DoS"]
    d = ds.resolve(env.datasets_dir, cfg.dataset_id)
    sink = MemorySink()
    ExperimentEngine(cfg, d.files, ds.pick_profile(d, None, None), d.data_origin, sink).run()
    assert "DoS" not in sink.summary["initial_classes"]
    assert all(f["is_novel_class"] for f in sink.flows if f["true_label"] == "DoS")


@pytest.mark.parametrize("train_fraction", [0.1, 0.3, 0.5])
def test_reference_set_only_holds_classes_learned_from_the_fit_period(env, train_fraction):
    """A class that first appears in the reference period was never learned, so it must not count as forgetting."""
    cfg = small_config(method="static").model_copy(deep=True)
    cfg.split.train_fraction = train_fraction
    d = ds.resolve(env.datasets_dir, cfg.dataset_id)
    sink = MemorySink()
    eng = ExperimentEngine(cfg, d.files, ds.pick_profile(d, None, None), d.data_origin, sink)
    eng.run()
    assert set(np.unique(eng.ref_y)) <= set(np.unique(eng.train_y.astype(str)))
    dropped = sink.summary["integrity"]["reference_rows_dropped_unseen_classes"]
    assert isinstance(dropped, dict) and not set(dropped) & set(np.unique(eng.train_y.astype(str)))
