"""End-to-end API tests. Runs execute in real worker subprocesses, as in production."""

import csv
import io
import json
import sqlite3
import time
import zipfile

import pytest

API = "/api/v1"
CFG = {
    "name": "api-test",
    "dataset_id": "DEMO_sentinel_synthetic",
    "seed": 5,
    "split": {"train_fraction": 0.3, "val_fraction": 0.2, "window_size": 300},
    "labels": {"delay_windows": 1, "budget": 0.5},
    "adaptation": {"method": "guarded_selective"},
}


def wait_for(client, run_id, statuses, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"{API}/experiments/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.3)
    raise AssertionError(f"run stuck in {run['status']}: {run}")


def test_health(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert all(c["ok"] for c in body["checks"].values())


def test_datasets_listed_with_demo_flag(client):
    items = client.get(f"{API}/datasets").json()["items"]
    demo = next(d for d in items if d["id"] == "DEMO_sentinel_synthetic")
    assert demo["is_demo"] and demo["data_origin"] == "demo"
    assert demo["detected_profile"] == "sentinel_demo"


def test_unknown_dataset_and_path_traversal(client):
    assert client.post(f"{API}/datasets/validate", json={"dataset_id": "nope"}).status_code == 404
    assert client.post(f"{API}/datasets/validate", json={"dataset_id": "../.."}).status_code == 400


@pytest.fixture(scope="module")
def completed_run(client):
    run = client.post(f"{API}/experiments", json=CFG).json()
    r = client.post(f"{API}/experiments/{run['run_id']}/start")
    if r.status_code == 409:  # not validated yet in this session
        assert "validate" in r.json()["detail"]
        v = client.post(f"{API}/datasets/validate", json={"dataset_id": CFG["dataset_id"]})
        assert v.status_code == 200 and v.json()["valid"]
        r = client.post(f"{API}/experiments/{run['run_id']}/start")
    assert r.status_code == 202
    # API must stay responsive while the worker runs.
    t0 = time.time()
    assert client.get(f"{API}/health").status_code == 200
    assert time.time() - t0 < 2
    done = wait_for(client, run["run_id"], {"completed", "failed"})
    assert done["status"] == "completed", done["error"]
    return done


def test_start_requires_validation(client, env):
    with sqlite3.connect(env.db_path) as c:
        c.execute("DELETE FROM dataset_validations")
    run = client.post(f"{API}/experiments", json=CFG).json()
    r = client.post(f"{API}/experiments/{run['run_id']}/start")
    assert r.status_code == 409
    assert "validate" in r.json()["detail"].lower()


def test_run_outputs_are_inspectable(client, completed_run):
    rid = completed_run["run_id"]
    assert completed_run["data_origin"] == "demo"
    assert completed_run["dataset_sha256"]

    page = client.get(f"{API}/experiments/{rid}/flows", params={"page_size": 10, "page": 2}).json()
    assert page["page"] == 2 and len(page["items"]) == 10 and page["data_origin"] == "demo"
    assert page["items"][0]["flow_id"] == 10

    unknown = client.get(f"{API}/experiments/{rid}/flows", params={"is_unknown": True, "page_size": 5}).json()
    assert unknown["total"] > 0
    assert all(f["decision"] == "UNKNOWN" for f in unknown["items"])

    detail = client.get(f"{API}/experiments/{rid}/flows/{unknown['items'][0]['flow_id']}").json()
    assert detail["features"] and detail["probabilities"] and detail["unknown_reason"]

    metrics = client.get(f"{API}/experiments/{rid}/metrics").json()
    for key in ("macro_f1", "per_class_recall", "fpr", "pr_auc", "unknown_recall", "forgetting_max",
                "adaptation_delay_windows", "latency_ms_per_flow", "train_seconds_total", "labels_used"):
        assert key in metrics["overall"]
    assert metrics["windows"] and "macro_f1" in metrics["definitions"]
    assert metrics["provenance"]["config_hash"] == completed_run["config_hash"]
    assert metrics["confusion_matrix"]["labels"]

    drift = client.get(f"{API}/experiments/{rid}/drift-events").json()
    adapt = client.get(f"{API}/experiments/{rid}/adaptation-events").json()
    assert drift["total"] >= 1 and adapt["total"] >= 1
    models = client.get(f"{API}/experiments/{rid}/models").json()
    assert sum(m["status"] == "active" for m in models) == 1

    ov = client.get(f"{API}/experiments/{rid}/overview").json()
    assert ov["is_demo"] and len(ov["trends"]) == ov["kpis"]["windows"]
    assert client.get(f"{API}/experiments/{rid}/logs").json()["lines"]


def test_exports_carry_provenance(client, completed_run):
    rid = completed_run["run_id"]
    r = client.get(f"{API}/experiments/{rid}/export", params={"format": "csv"})
    assert r.status_code == 200
    assert f"DEMO_{rid}_predictions.csv" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows and all(row["run_id"] == rid and row["data_origin"] == "DEMO" for row in rows[:50])
    assert rows[0]["dataset_sha256"] == completed_run["dataset_sha256"]

    bundle = client.get(f"{API}/experiments/{rid}/export", params={"format": "json"}).json()
    assert bundle["provenance"]["run_id"] == rid and bundle["provenance"]["is_demo"]
    assert bundle["config"]["seed"] == CFG["seed"]

    z = zipfile.ZipFile(io.BytesIO(client.get(f"{API}/experiments/{rid}/export", params={"format": "zip"}).content))
    names = z.namelist()
    assert any(n.endswith("DEMO_DATA_README.txt") for n in names)
    assert json.loads(z.read(next(n for n in names if n.endswith("run.json"))))["provenance"]["run_id"] == rid


def test_compare_flags_unfair_configs(client, completed_run):
    other = client.post(f"{API}/experiments", json={**CFG, "seed": 99}).json()
    cmp = client.get(f"{API}/experiments/compare",
                     params={"run_ids": f"{completed_run['run_id']},{other['run_id']}"}).json()
    assert not cmp["fair"] and "seed" in cmp["differences"]


def test_pause_step_resume_cancel(client, completed_run):
    run = client.post(f"{API}/experiments", json={**CFG, "adaptation": {"method": "static"}}).json()
    rid = run["run_id"]
    assert client.post(f"{API}/experiments/{rid}/start").status_code == 202
    assert client.post(f"{API}/experiments/{rid}/pause").status_code == 200
    paused = wait_for(client, rid, {"paused"})
    w0 = paused["progress"]["window"]
    assert client.post(f"{API}/experiments/{rid}/step").json()["control"] == "step"
    deadline = time.time() + 60
    while time.time() < deadline:
        run = client.get(f"{API}/experiments/{rid}").json()
        if run["progress"]["window"] == w0 + 1 and run["status"] == "paused":
            break
        time.sleep(0.2)
    assert run["progress"]["window"] == w0 + 1 and run["status"] == "paused"
    assert client.post(f"{API}/experiments/{rid}/cancel").status_code == 200
    assert wait_for(client, rid, {"cancelled"})["status"] == "cancelled"
    # Completed runs are immutable.
    assert client.post(f"{API}/experiments/{completed_run['run_id']}/start").status_code == 409
