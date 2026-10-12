"""Alert triage, policies, system status and report stats."""

import time

from tests.test_api import API, CFG, wait_for


def _completed(client):
    client.post(f"{API}/datasets/validate", json={"dataset_id": CFG["dataset_id"]})
    run = client.post(f"{API}/experiments", json={**CFG, "adaptation": {"method": "static"}}).json()
    assert client.post(f"{API}/experiments/{run['run_id']}/start").status_code == 202
    return wait_for(client, run["run_id"], {"completed", "failed"})


def test_alert_triage_workflow(client):
    run = _completed(client)
    rid = run["run_id"]
    alerts = client.get(f"{API}/experiments/{rid}/alerts", params={"page_size": 500}).json()
    assert alerts["total"] > 0 and alerts["data_origin"] == "demo"
    items = alerts["items"]
    assert all(a["decision"] != "BENIGN" for a in items)
    # UNKNOWN is always 'review' severity, never 'critical' (unknown != malicious).
    assert all(a["severity"] == "review" for a in items if a["decision"] == "UNKNOWN")
    assert all(a["state"] == "open" for a in items)

    before = client.get(f"{API}/experiments/{rid}/alerts/summary").json()
    target = items[0]["flow_id"]
    r = client.patch(f"{API}/experiments/{rid}/alerts/{target}", json={"state": "investigating", "note": "check"})
    assert r.status_code == 200 and r.json()["alert"]["state"] == "investigating"
    r = client.patch(f"{API}/experiments/{rid}/alerts/{target}", json={"state": "resolved", "note": "benign scan"})
    detail = r.json()
    assert [h["to_state"] for h in detail["history"]] == ["investigating", "resolved"]
    assert detail["flow"]["features"]
    after = client.get(f"{API}/experiments/{rid}/alerts/summary").json()
    assert after["resolved"] == before["resolved"] + 1 and after["resolved_today"] == before["resolved_today"] + 1
    assert after["open"] == before["open"] - 1
    resolved = client.get(f"{API}/experiments/{rid}/alerts", params={"state": "resolved"}).json()
    assert [a["flow_id"] for a in resolved["items"]] == [target]

    benign_flow = client.get(f"{API}/experiments/{rid}/flows", params={"decision": "BENIGN", "page_size": 1}).json()
    fid = benign_flow["items"][0]["flow_id"]
    assert client.patch(f"{API}/experiments/{rid}/alerts/{fid}", json={"state": "resolved"}).status_code == 404


def test_policies_are_versioned_and_applied(client):
    active = client.get(f"{API}/policies/active").json()
    assert active["status"] == "active" and active["policy_id"].startswith("POL-")
    body = active["body"]
    body["window_size"] = 250
    body["openworld"]["msp_quantile"] = 0.05
    body["adaptation"]["rollback"] = False
    new = client.post(f"{API}/policies", json={"body": body, "note": "tighter review budget"}).json()
    assert new["version"] == active["version"] + 1 and new["status"] == "active"
    history = client.get(f"{API}/policies").json()
    assert [p["status"] for p in history[:2]] == ["active", "superseded"]

    run = client.post(f"{API}/experiments", json={**CFG, "policy_version": new["version"]}).json()
    cfg = run["config"]
    assert cfg["split"]["window_size"] == 250 and cfg["openworld"]["msp_quantile"] == 0.05
    assert cfg["adaptation"]["rollback"] is False
    assert cfg["adaptation"]["method"] == CFG["adaptation"]["method"]  # method stays per-experiment
    assert cfg["policy_version"] == new["version"]


def test_system_and_report_stats(client):
    s = client.get(f"{API}/system").json()
    assert 0 <= s["cpu_percent"] <= 100 and s["memory_total_gb"] > 0
    assert {svc["name"] for svc in s["services"]} >= {"FastAPI", "Python", "SQLite"}
    assert s["worker"]["state"] in ("idle", "busy")
    before = client.get(f"{API}/reports/stats").json()
    run_id = client.get(f"{API}/experiments", params={"status": "completed"}).json()["items"][0]["run_id"]
    client.get(f"{API}/experiments/{run_id}/export", params={"format": "json"})
    after = client.get(f"{API}/reports/stats").json()
    assert after["exports_this_week"] == before["exports_this_week"] + 1
    assert after["last_export"]["run_id"] == run_id
