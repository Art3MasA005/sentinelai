"""Built-in dataset profiles for supported IDS CSV schemas."""

from __future__ import annotations

from app.schemas.datasets import DatasetProfile

UNSW_NB15_COLUMNS = [
    "srcip", "sport", "dstip", "dsport", "proto", "state", "dur", "sbytes", "dbytes", "sttl",
    "dttl", "sloss", "dloss", "service", "Sload", "Dload", "Spkts", "Dpkts", "swin", "dwin",
    "stcpb", "dtcpb", "smeansz", "dmeansz", "trans_depth", "res_bdy_len", "Sjit", "Djit",
    "Stime", "Ltime", "Sintpkt", "Dintpkt", "tcprtt", "synack", "ackdat", "is_sm_ips_ports",
    "ct_state_ttl", "ct_flw_http_mthd", "is_ftp_login", "ct_ftp_cmd", "ct_srv_src",
    "ct_srv_dst", "ct_dst_ltm", "ct_src_ltm", "ct_src_dport_ltm", "ct_dst_sport_ltm",
    "ct_dst_src_ltm", "attack_cat", "Label",
]

BUILTIN_PROFILES: dict[str, DatasetProfile] = {
    p.name: p
    for p in [
        DatasetProfile(
            name="sentinel_demo",
            description="Synthetic SentinelAI DEMO flows (generated locally, never real traffic).",
            timestamp_column="timestamp",
            label_column="label",
            benign_labels=["BENIGN"],
            drop_columns=["flow_id", "src_ip", "dst_ip", "timestamp", "label", "is_demo"],
            categorical_columns=["protocol"],
            required_columns=["timestamp", "label", "is_demo", "duration", "fwd_pkts", "bwd_pkts"],
            source_column="src_ip", destination_column="dst_ip", protocol_column="protocol",
            timestamp_unit="s",
        ),
        DatasetProfile(
            name="cicids2017",
            description="CIC-IDS2017 'TrafficLabelling' CSVs (the MachineLearningCVE variant has no Timestamp).",
            timestamp_column="Timestamp",
            label_column="Label",
            benign_labels=["BENIGN"],
            drop_columns=["Flow ID", "Source IP", "Source Port", "Destination IP", "Timestamp", "Label"],
            required_columns=[
                "Timestamp", "Label", "Flow Duration", "Total Fwd Packets", "Total Backward Packets",
                "Destination Port",
            ],
            source_column="Source IP", destination_column="Destination IP", protocol_column="Protocol",
            timestamp_dayfirst=True,
            # Captured 09:00-17:00 but afternoon times are written as 1:00-5:59 without PM.
            timestamp_pm_before_hour=8,
        ),
        DatasetProfile(
            name="cicids2018",
            description="CSE-CIC-IDS2018 CICFlowMeter CSVs.",
            timestamp_column="Timestamp",
            label_column="Label",
            benign_labels=["Benign", "BENIGN"],
            drop_columns=["Flow ID", "Src IP", "Src Port", "Dst IP", "Timestamp", "Label"],
            required_columns=["Timestamp", "Label", "Flow Duration", "Tot Fwd Pkts", "Tot Bwd Pkts", "Dst Port"],
            source_column="Src IP", destination_column="Dst IP", protocol_column="Protocol",
            timestamp_dayfirst=True,
        ),
        DatasetProfile(
            name="unswnb15",
            description="UNSW-NB15 raw CSVs UNSW-NB15_1..4.csv (headerless; the train/test partition files lack Stime).",
            timestamp_column="Stime",
            label_column="attack_cat",
            benign_labels=["Normal"],
            drop_columns=["srcip", "sport", "dstip", "dsport", "Stime", "Ltime", "attack_cat", "Label"],
            categorical_columns=["proto", "state", "service"],
            required_columns=["Stime", "attack_cat", "dur", "sbytes", "dbytes", "proto"],
            source_column="srcip", destination_column="dstip", protocol_column="proto",
            has_header=False,
            column_names=UNSW_NB15_COLUMNS,
            timestamp_unit="s",
            label_fill="Normal",
            label_map={"Backdoors": "Backdoor"},
        ),
    ]
}


def get_profile(name: str) -> DatasetProfile:
    try:
        return BUILTIN_PROFILES[name]
    except KeyError:
        raise KeyError(f"Unknown profile '{name}'. Built-ins: {', '.join(BUILTIN_PROFILES)}") from None


def score_profile(profile: DatasetProfile, first_line: list[str]) -> float:
    """Return 0..1 confidence that a CSV whose first line is `first_line` matches the profile."""
    if profile.has_header:
        cols = {c.strip() for c in first_line}
        if not profile.required_columns:
            return 0.0
        return sum(c in cols for c in profile.required_columns) / len(profile.required_columns)
    # Headerless: the first line is really data, so compare width and look for a dotted IP first.
    names = profile.column_names or []
    if len(first_line) != len(names):
        return 0.0
    cell = first_line[0].strip()
    looks_like_ip = cell.count(".") == 3 and cell.replace(".", "").isdigit()
    return 0.9 if looks_like_ip else 0.5


def detect_profile(first_line: list[str]) -> str | None:
    best, best_score = None, 0.0
    for p in BUILTIN_PROFILES.values():
        s = score_profile(p, first_line)
        if s > best_score:
            best, best_score = p.name, s
    return best if best_score >= 0.5 else None
