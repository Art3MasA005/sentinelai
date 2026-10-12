"""Figures (P5), multi-seed batches with a worker queue, run deletion and the PyTorch MLP model."""

import io
import json
import zipfile

import pytest

from tests.test_api import API, CFG, wait_for
from tests.test_pipeline import digest, run as run_engine


def _validated(client):
    assert client.post(f"{API}/datasets/validate", json={"dataset_id": CFG["dataset_id"]}).json()["valid"]


@pytest.fixture(scope="module")
def batch(client, env):
    _validated(client)
    env.max_workers = 1  # force queueing
    try:
        body = {"base": {**CFG, "name": "batch", "adaptation": {"method": "static"}}, "seeds": [1, 2], "start": True}
        r = client.post(f"{API}/experiments/batch", json=body)
        assert r.status_code == 201, r.text
        res = r.json()
        statuses = sorted(x["status"] for x in res["runs"])
        assert statuses == ["queued", "running"]  # one worker slot -> second run waits
        runs = [wait_for(client, x["run_id"], {"completed", "failed"}) for x in res["runs"]]
    finally:
        env.max_workers = 2
    assert all(r["status"] == "completed" for r in runs), [r["error"] for r in runs]
    return res["group_id"], runs


def test_batch_runs_share_group_and_differ_only_by_seed(batch):
    group_id, runs = batch
    assert all(r["group_id"] == group_id for r in runs)
    assert sorted(r["config"]["seed"] for r in runs) == [1, 2]
    assert {r["config_hash"] for r in runs}.__len__() == 2


def test_compare_aggregates_mean_and_std(client, batch):
    _, runs = batch
    cmp = client.get(f"{API}/experiments/compare", params={"run_ids": ",".join(r["run_id"] for r in runs)}).json()
    assert cmp["fair"] is True  # seeds differ by design, everything else identical
    (agg,) = cmp["aggregates"]
    assert agg["method"] == "static" and agg["n"] == 2 and agg["seeds"] == [1, 2]
    vals = [r["summary"]["overall"]["macro_f1"] for r in runs]
    assert agg["metrics"]["macro_f1"]["mean"] == pytest.approx(sum(vals) / 2)
    assert agg["metrics"]["macro_f1"]["std"] >= 0


def _zip_names(content: bytes) -> list[str]:
    return zipfile.ZipFile(io.BytesIO(content)).namelist()


def test_run_figures_bundle(client, batch):
    _, runs = batch
    r = client.get(f"{API}/experiments/{runs[0]['run_id']}/export", params={"format": "figures"})
    assert r.status_code == 200 and "DEMO_" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    for stem in ("01_window_metrics", "02_decisions", "03_drift", "04_confusion", "05_adaptation"):
        assert any(n.endswith(f"{stem}.png") for n in names) and any(n.endswith(f"{stem}.pdf") for n in names)
    png = z.read(next(n for n in names if n.endswith("01_window_metrics.png")))
    assert png.startswith(b"\x89PNG")
    manifest = json.loads(z.read(next(n for n in names if n.endswith("figures.json"))))
    assert manifest["provenance"]["run_id"] == runs[0]["run_id"]


def test_comparison_figures(client, batch):
    _, runs = batch
    r = client.get(f"{API}/experiments/compare/figures", params={"run_ids": ",".join(x["run_id"] for x in runs)})
    assert r.status_code == 200
    names = _zip_names(r.content)
    assert any(n.endswith("compare_macro_f1_windows.png") for n in names)
    assert any(n.endswith("compare_methods.pdf") for n in names)


def test_delete_run(client, env, batch):
    _, runs = batch
    rid = runs[1]["run_id"]
    assert (env.results_dir / rid).exists()
    assert client.delete(f"{API}/experiments/{rid}").status_code == 200
    assert client.get(f"{API}/experiments/{rid}").status_code == 404
    assert client.get(f"{API}/experiments/{rid}/flows").status_code == 404
    assert not (env.results_dir / rid).exists()


def test_delete_refuses_active_run(client):
    _validated(client)
    run = client.post(f"{API}/experiments", json={**CFG, "adaptation": {"method": "static"}}).json()
    client.post(f"{API}/experiments/{run['run_id']}/start")
    client.post(f"{API}/experiments/{run['run_id']}/pause")
    wait_for(client, run["run_id"], {"paused", "completed"})
    if client.get(f"{API}/experiments/{run['run_id']}").json()["status"] == "paused":
        assert client.delete(f"{API}/experiments/{run['run_id']}").status_code == 409
        client.post(f"{API}/experiments/{run['run_id']}/cancel")
        wait_for(client, run["run_id"], {"cancelled"})
    assert client.delete(f"{API}/experiments/{run['run_id']}").status_code == 200


def test_cancel_queued_run(client, env):
    _validated(client)
    env.max_workers = 0  # treated as 1; occupy the slot with a paused run
    try:
        a = client.post(f"{API}/experiments", json={**CFG, "adaptation": {"method": "static"}}).json()
        b = client.post(f"{API}/experiments", json={**CFG, "adaptation": {"method": "static"}}).json()
        client.post(f"{API}/experiments/{a['run_id']}/start")
        client.post(f"{API}/experiments/{a['run_id']}/pause")
        assert client.post(f"{API}/experiments/{b['run_id']}/start").json()["status"] == "queued"
        assert client.post(f"{API}/experiments/{b['run_id']}/cancel").json()["status"] == "cancelled"
        client.post(f"{API}/experiments/{a['run_id']}/cancel")
        wait_for(client, a["run_id"], {"cancelled", "completed"})
    finally:
        env.max_workers = 2


def test_torch_mlp_model_trains_and_is_reproducible(env):
    pytest.importorskip("torch")
    s1 = run_engine(env, method="static")  # baseline import path
    assert s1.summary
    from app.ml.pipeline import ExperimentEngine
    from app.services import datasets as ds
    from tests.conftest import small_config
    from tests.test_pipeline import MemorySink

    def go():
        cfg = small_config(method="static")
        cfg.model.kind = "mlp"
        cfg.model.params = {"epochs": 5}
        d = ds.resolve(env.datasets_dir, cfg.dataset_id)
        sink = MemorySink()
        ExperimentEngine(cfg, d.files, ds.pick_profile(d, None, None), d.data_origin, sink).run()
        return sink

    a, b = go(), go()
    assert a.summary["overall"]["macro_f1"] > 0.3
    assert digest(a) == digest(b)


def test_flow_storage_file_streams_predictions_to_gzip(client, env):
    import csv
    import gzip

    _validated(client)
    r = client.post(f"{API}/experiments", json={**CFG, "name": "file flows", "flow_storage": "file"})
    assert r.status_code == 201, r.text
    rid = r.json()["run_id"]
    client.post(f"{API}/experiments/{rid}/start")
    run = wait_for(client, rid, {"completed", "failed"})
    assert run["status"] == "completed", run["error"]
    out = env.results_dir / rid
    with gzip.open(out / "predictions.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == run["summary"]["flows"]
    assert {"decision", "true_label", "probabilities_json"} <= set(rows[0])
    assert not (out / "predictions.csv").exists()  # nothing duplicated into an empty export
    flows = client.get(f"{API}/experiments/{rid}/flows").json()
    assert flows["total"] == 0  # the database holds windows and events only
