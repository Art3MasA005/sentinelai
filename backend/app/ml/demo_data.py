"""Synthetic DEMO flow generator. Output is clearly marked DEMO and must never be presented as real traffic.

Timeline (fractions of the stream):
- benign traffic drifts gradually after 45% (larger transfers, longer flows);
- a class never seen before ("Exfiltration") starts at 60%;
- "PortScan" changes its behaviour after 75%.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DEMO_DATASET_ID = "DEMO_sentinel_synthetic"
MANIFEST = "sentinel_dataset.json"


def _flows(rng: np.random.Generator, label: str, n: int, t: np.ndarray) -> dict[str, np.ndarray]:
    drift = np.clip((t - 0.45) / 0.3, 0, 1)  # 0 before 45%, ramps to 1 by 75%
    if label == "BENIGN":
        dur = rng.lognormal(8 + 1.2 * drift, 1.5, n)
        fwd = rng.poisson(12 + 10 * drift, n) + 1
        bwd = rng.poisson(10 + 8 * drift, n)
        plen = rng.normal(600 + 250 * drift, 180, n).clip(40, 1500)
        syn = rng.binomial(1, 0.3, n)
        port = rng.choice([80, 443, 53, 22, 8080], n, p=[0.2, 0.55, 0.15, 0.05, 0.05])
        proto = rng.choice(["TCP", "UDP"], n, p=[0.8, 0.2])
    elif label == "DoS":
        dur = rng.lognormal(5, 0.8, n)
        fwd = rng.poisson(300, n) + 1
        bwd = rng.poisson(2, n)
        plen = rng.normal(80, 20, n).clip(40, 1500)
        syn = rng.binomial(1, 0.95, n)
        port = rng.choice([80, 443], n)
        proto = np.full(n, "TCP")
    elif label == "PortScan":
        late = t > 0.75
        dur = rng.lognormal(np.where(late, 7, 3), 0.6, n)
        fwd = rng.poisson(np.where(late, 6, 1), n) + 1
        bwd = rng.poisson(np.where(late, 2, 0.3), n)
        plen = rng.normal(np.where(late, 200, 60), 15, n).clip(40, 1500)
        syn = rng.binomial(1, 0.9, n)
        port = rng.integers(1, 65535, n)
        proto = np.full(n, "TCP")
    elif label == "BruteForce":
        dur = rng.lognormal(9, 0.5, n)
        fwd = rng.poisson(25, n) + 1
        bwd = rng.poisson(22, n)
        plen = rng.normal(180, 30, n).clip(40, 1500)
        syn = rng.binomial(1, 0.5, n)
        port = rng.choice([22, 21, 3389], n)
        proto = np.full(n, "TCP")
    else:  # Exfiltration (novel)
        dur = rng.lognormal(11, 0.7, n)
        fwd = rng.poisson(400, n) + 1
        bwd = rng.poisson(15, n)
        plen = rng.normal(1350, 80, n).clip(40, 1500)
        syn = rng.binomial(1, 0.2, n)
        port = rng.choice([443, 53, 8443], n)
        proto = rng.choice(["TCP", "UDP"], n, p=[0.6, 0.4])
    fwd_bytes = fwd * plen
    bwd_bytes = bwd * rng.normal(500, 150, n).clip(40, 1500)
    secs = np.maximum(dur / 1e6, 1e-6)
    return {
        "protocol": proto,
        "dst_port": port,
        "duration": dur.round(0),
        "fwd_pkts": fwd,
        "bwd_pkts": bwd,
        "fwd_bytes": fwd_bytes.round(0),
        "bwd_bytes": bwd_bytes.round(0),
        "pkt_len_mean": plen.round(2),
        "pkt_len_std": np.abs(rng.normal(plen * 0.2, 20, n)).round(2),
        "iat_mean": (dur / np.maximum(fwd + bwd, 1)).round(2),
        "syn_flag_count": syn,
        "rst_flag_count": rng.binomial(1, 0.05, n),
        "flow_bytes_per_s": ((fwd_bytes + bwd_bytes) / secs).round(2),
        "down_up_ratio": (bwd / np.maximum(fwd, 1)).round(3),
    }


def generate_demo(n_rows: int = 30000, seed: int = 7, hours: float = 12.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = np.sort(rng.random(n_rows))
    probs = np.tile([0.82, 0.07, 0.06, 0.05, 0.0], (n_rows, 1))
    late = t >= 0.6
    probs[late] = [0.78, 0.06, 0.05, 0.04, 0.07]
    labels_all = np.array(["BENIGN", "DoS", "PortScan", "BruteForce", "Exfiltration"])
    cum = probs.cumsum(axis=1)
    cum[:, -1] = np.inf  # guard against float round-off past the last class
    label_idx = (rng.random(n_rows)[:, None] > cum).sum(axis=1)
    labels = labels_all[label_idx]

    cols: dict[str, np.ndarray] = {}
    order = np.arange(n_rows)
    parts = []
    for lab in labels_all:
        m = labels == lab
        if m.any():
            parts.append((order[m], _flows(rng, lab, int(m.sum()), t[m])))
    for idx, feats in parts:
        for k, v in feats.items():
            if k not in cols:
                cols[k] = np.empty(n_rows, dtype=v.dtype if v.dtype.kind != "U" else object)
            cols[k][idx] = v

    start = pd.Timestamp("2026-01-05 08:00:00").timestamp()
    df = pd.DataFrame({
        "flow_id": [f"demo-{i:06d}" for i in range(n_rows)],
        "timestamp": (start + t * hours * 3600).round(3),
        "src_ip": [f"10.0.{rng.integers(0, 4)}.{rng.integers(2, 250)}" for _ in range(n_rows)],
        "dst_ip": [f"192.168.1.{rng.integers(2, 250)}" for _ in range(n_rows)],
        **cols,
        "label": labels,
        "is_demo": 1,
    })
    return df


def write_demo_dataset(datasets_dir: Path, n_rows: int = 30000, seed: int = 7, overwrite: bool = False) -> Path:
    folder = datasets_dir / DEMO_DATASET_ID
    csv_path = folder / "DEMO_flows.csv"
    if csv_path.exists() and not overwrite:
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    generate_demo(n_rows, seed).to_csv(csv_path, index=False)
    (folder / MANIFEST).write_text(json.dumps({
        "name": "DEMO · SentinelAI synthetic flows",
        "profile": "sentinel_demo",
        "is_demo": True,
        "files": ["DEMO_flows.csv"],
        "generator": {"module": "app.ml.demo_data", "n_rows": n_rows, "seed": seed},
    }, indent=2), encoding="utf-8")
    return folder
