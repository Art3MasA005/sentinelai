"""SQLite storage shared by the API process and worker processes (WAL mode)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    control TEXT NOT NULL DEFAULT 'run',
    method TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    profile TEXT,
    data_origin TEXT,
    dataset_sha256 TEXT,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    progress_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT,
    error TEXT,
    pid INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS windows (
    run_id TEXT NOT NULL,
    window INTEGER NOT NULL,
    start_ts REAL,
    end_ts REAL,
    n_flows INTEGER NOT NULL,
    model_version INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    drift_json TEXT NOT NULL,
    PRIMARY KEY (run_id, window)
);
CREATE TABLE IF NOT EXISTS flows (
    run_id TEXT NOT NULL,
    flow_id INTEGER NOT NULL,
    window INTEGER NOT NULL,
    row_index INTEGER NOT NULL,
    ts REAL,
    true_label TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    attack_score REAL,
    novelty_score REAL,
    is_unknown INTEGER NOT NULL,
    unknown_reason TEXT,
    is_novel_class INTEGER NOT NULL,
    model_version INTEGER NOT NULL,
    probabilities_json TEXT NOT NULL,
    features_json TEXT,
    src TEXT,
    dst TEXT,
    protocol TEXT,
    PRIMARY KEY (run_id, flow_id)
);
CREATE INDEX IF NOT EXISTS ix_flows_window ON flows (run_id, window);
CREATE INDEX IF NOT EXISTS ix_flows_decision ON flows (run_id, decision);
CREATE INDEX IF NOT EXISTS ix_flows_unknown ON flows (run_id, is_unknown);
CREATE TABLE IF NOT EXISTS drift_events (
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    window INTEGER NOT NULL,
    method TEXT NOT NULL,
    score REAL NOT NULL,
    threshold REAL NOT NULL,
    start_ts REAL,
    end_ts REAL,
    detected_at TEXT NOT NULL,
    details_json TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id)
);
CREATE TABLE IF NOT EXISTS adaptation_events (
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    window INTEGER NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    trigger TEXT NOT NULL,
    from_version INTEGER NOT NULL,
    to_version INTEGER,
    validation_json TEXT NOT NULL,
    cost_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, event_id)
);
CREATE TABLE IF NOT EXISTS model_versions (
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    parent_version INTEGER,
    created_window INTEGER NOT NULL,
    status TEXT NOT NULL,
    classes_json TEXT NOT NULL,
    train_rows INTEGER NOT NULL,
    train_seconds REAL NOT NULL,
    model_bytes INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, version)
);
CREATE TABLE IF NOT EXISTS dataset_validations (
    dataset_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    valid INTEGER NOT NULL,
    rows INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    report_json TEXT NOT NULL,
    validated_at TEXT NOT NULL,
    PRIMARY KEY (dataset_id, profile)
);
CREATE TABLE IF NOT EXISTS alert_triage (
    run_id TEXT NOT NULL,
    flow_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    note TEXT,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, flow_id)
);
CREATE INDEX IF NOT EXISTS ix_triage_state ON alert_triage (run_id, state);
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    flow_id INTEGER NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    note TEXT,
    updated_by TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS policies (
    version INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT,
    name TEXT NOT NULL,
    phone TEXT,
    country TEXT,
    institution TEXT,
    role TEXT,
    avatar_file TEXT,
    google_sub TEXT UNIQUE,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    client TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions (user_id);
CREATE TABLE IF NOT EXISTS export_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    format TEXT NOT NULL,
    kind TEXT,
    at TEXT NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Columns added after the first release: (table, column, type).
MIGRATIONS = [
    ("flows", "src", "TEXT"),
    ("flows", "dst", "TEXT"),
    ("flows", "protocol", "TEXT"),
    ("runs", "group_id", "TEXT"),
]


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


@contextmanager
def closing(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


def loads(text: str | None):
    return None if text is None else json.loads(text)
