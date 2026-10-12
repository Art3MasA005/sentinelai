"""Real-dataset path: CIC-IDS2017-style archives (AM/PM-less times, blank rows, Infinity, odd label bytes)."""

import io
import zipfile

import numpy as np
import pytest

from app.ml.data import load_dataset
from app.ml.profiles import get_profile
from tests.test_api import API

HEADER = (" Flow ID, Source IP, Source Port, Destination IP, Destination Port, Protocol, Timestamp, Flow Duration,"
          " Total Fwd Packets, Total Backward Packets, Flow Bytes/s, Fwd Packet Length Mean, Label")
DAYS = {  # file name -> (date, times as written in CIC (no AM/PM), labels)
    "Monday-WorkingHours.pcap_ISCX.csv": ("3/7/2017", ["9:01", "11:30", "1:15", "4:59"], ["BENIGN"]),
    "Tuesday-WorkingHours.pcap_ISCX.csv": ("4/7/2017", ["9:20", "10:05", "2:10", "3:00"], ["BENIGN", "FTP-Patator"]),
    "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv": ("7/7/2017", ["3:30", "3:56", "4:10"], ["BENIGN", "DDoS"]),
    "Friday-WorkingHours-Morning.pcap_ISCX.csv": ("7/7/2017", ["9:05", "10:00", "11:45"], ["BENIGN", "Bot"]),
}


def _csv(date, times, labels, rng) -> bytes:
    lines = [HEADER]
    for t in times:
        for k in range(30):
            label = labels[k % len(labels)]
            rate = "Infinity" if k == 7 else f"{rng.random() * 1e5:.1f}"
            lines.append(f"f{k},192.168.10.{k % 50},{40000 + k},10.0.0.{k % 9},{80 if k % 2 else 443},6,"
                         f"{date} {t},{rng.integers(10, 10**6)},{rng.integers(1, 50)},{rng.integers(0, 50)},"
                         f"{rate},{rng.random() * 900:.2f},{label}")
    lines += [",,,,,,,,,,,,"] * 25  # CIC files end with runs of empty rows
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.fixture(scope="module")
def cic_zip(tmp_path_factory):
    rng = np.random.default_rng(0)
    path = tmp_path_factory.mktemp("dl") / "GeneratedLabelledFlows.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, (date, times, labels) in DAYS.items():
            z.writestr(f"TrafficLabelling /{name}", _csv(date, times, labels, rng))
        # The real Thursday file has a cp1252 dash in "Web Attack – Brute Force".
        web = HEADER + "\n" + "\n".join(
            f"w{k},192.168.10.5,5000{k},10.0.0.1,80,6,6/7/2017 9:{10 + k},100,2,2,10.0,50.0,Web Attack – Brute Force"
            for k in range(20)) + "\n"
        z.writestr("TrafficLabelling /Thursday-WorkingHours-Morning-WebAttacks.pcap_ISCX.csv", web.encode("cp1252"))
        z.writestr("TrafficLabelling /../../evil.csv", HEADER + "\n")  # must not escape the dataset folder
        z.writestr("README.txt", "not a csv")
    return path


@pytest.fixture(scope="module")
def imported(client, env, cic_zip):
    r = client.post(f"{API}/datasets/import", json={"source": str(cic_zip), "name": "CIC-IDS2017-mini"})
    assert r.status_code == 201, r.text
    return r.json()


def test_import_orders_days_and_keeps_only_csv(imported, env):
    files = imported["files"]
    assert files[0].startswith("Monday") and files[1].startswith("Tuesday")
    assert files.index("Friday-WorkingHours-Morning.pcap_ISCX.csv") < files.index(
        "Friday-WorkingHours-Afternoon-DDos.pcap_ISCX.csv")
    assert "evil.csv" in files and not (env.datasets_dir.parent / "evil.csv").exists()
    assert imported["detected_profile"] == "cicids2017" and not imported["is_demo"]
    assert imported["data_origin"] == "replayed"


def test_import_refuses_duplicates_and_bad_names(client, cic_zip):
    assert client.post(f"{API}/datasets/import", json={"source": str(cic_zip), "name": "CIC-IDS2017-mini"}).status_code == 409
    assert client.post(f"{API}/datasets/import", json={"source": str(cic_zip), "name": "../x"}).status_code == 422
    assert client.post(f"{API}/datasets/import", json={"source": "C:/nope.zip", "name": "x"}).status_code == 404


def test_validation_handles_blank_rows_ampm_and_labels(client, imported):
    rep = client.post(f"{API}/datasets/validate", json={"dataset_id": imported["id"]}).json()
    assert rep["valid"], rep["errors"]
    assert rep["blank_rows"] == 25 * 4
    assert rep["timestamp_parse_failures"] == 0
    assert rep["label_distribution"]["Web Attack - Brute Force"] == 20
    # 4:59 on Monday is 16:59 (PM), so the range ends in the afternoon of Friday.
    assert rep["timestamp_max"].startswith("2017-07-07T16:10")
    assert rep["timestamp_min"].startswith("2017-07-03T09:01")


def test_loader_sorts_with_pm_fix_and_thins_while_reading(env, imported):
    from app.services import datasets as ds

    d = ds.resolve(env.datasets_dir, imported["id"])
    full = load_dataset(d.files, get_profile("cicids2017"))
    assert np.all(np.diff(full.timestamps) >= 0)
    hours = (full.timestamps % 86400) / 3600
    assert hours.min() >= 9 and hours.max() < 17.5  # no 1:00-5:59 "morning" artefacts left
    assert full.frame.dtypes.iloc[0] == np.float32
    assert set(full.context["protocol"]) == {"TCP"}
    thin = load_dataset(d.files, get_profile("cicids2017"), max_rows=100)
    assert len(thin.labels) <= 100 and np.all(np.diff(thin.timestamps) >= 0)


def test_experiment_runs_on_imported_dataset(client, imported):
    from tests.test_api import wait_for

    cfg = {"name": "cic-mini", "dataset_id": imported["id"], "seed": 3,
           "split": {"train_fraction": 0.4, "val_fraction": 0.2, "window_size": 40},
           "adaptation": {"method": "guarded_selective"}}
    run = client.post(f"{API}/experiments", json=cfg).json()
    assert client.post(f"{API}/experiments/{run['run_id']}/start").status_code == 202
    done = wait_for(client, run["run_id"], {"completed", "failed"})
    assert done["status"] == "completed", done["error"]
    assert done["data_origin"] == "replayed"
    flows = client.get(f"{API}/experiments/{run['run_id']}/flows", params={"page_size": 3}).json()
    assert flows["data_origin"] == "replayed" and flows["items"][0]["src"].startswith("192.168.10.")


def test_files_differing_only_in_dropped_identifier_columns_validate(tmp_path):
    """CSE-CIC-IDS2018: one day file carries Flow ID / Src IP / Src Port / Dst IP, the others do not."""
    from app.ml.data import validate_files

    base = "Dst Port,Protocol,Timestamp,Flow Duration,Tot Fwd Pkts,Tot Bwd Pkts,Label"
    a = tmp_path / "Wednesday-14-02-2018_TrafficForML_CICFlowMeter.csv"
    b = tmp_path / "Thuesday-20-02-2018_TrafficForML_CICFlowMeter.csv"
    a.write_text(base + "\n" + "\n".join(f"80,6,14/02/2018 08:{m:02d}:00,{m * 10},3,1,Benign" for m in range(30)) + "\n")
    b.write_text("Flow ID,Src IP,Src Port,Dst IP," + base + "\n" + "\n".join(
        f"x{m},1.2.3.4,5555,5.6.7.8,80,6,20/02/2018 10:{m:02d}:00,{m * 7},9,9,DDoS attacks-LOIC-HTTP"
        for m in range(30)) + "\n")
    rep = validate_files("ids2018", [a, b], get_profile("cicids2018"), is_demo=False)
    assert rep.valid, rep.errors
    assert any("only in ignored columns" in w for w in rep.warnings)
    data = load_dataset([a, b], get_profile("cicids2018"))
    assert set(data.labels) == {"Benign", "DDoS attacks-LOIC-HTTP"} and len(data.labels) == 60
    assert "Src Port" not in data.numeric_columns
