"""All SQL lives here. Each call opens its own short-lived connection (safe across threads/processes)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.storage.db import closing, connect, dumps, loads

FLOW_SORTS = {"flow_id": "flow_id", "confidence": "confidence", "attack_score": "attack_score",
              "novelty_score": "novelty_score", "timestamp": "ts"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _conn(self):
        return closing(connect(self.db_path))

    # ---------- runs ----------
    def create_run(self, row: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO runs (run_id, name, status, method, dataset_id, profile, data_origin,
                   dataset_sha256, config_json, config_hash, progress_json, created_at, group_id)
                   VALUES (:run_id, :name, 'created', :method, :dataset_id, :profile, :data_origin,
                   :dataset_sha256, :config_json, :config_hash, :progress_json, :created_at, :group_id)""",
                {"group_id": None, **row},
            )

    def get_run(self, run_id: str) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT rowid AS seq, * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(r) if r else None

    def list_runs(self, status: str | None, method: str | None, offset: int, limit: int) -> tuple[list[dict], int]:
        where, args = [], []
        if status:
            where.append("status = ?")
            args.append(status)
        if method:
            where.append("method = ?")
            args.append(method)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM runs {clause}", args).fetchone()[0]
            rows = c.execute(f"SELECT rowid AS seq, * FROM runs {clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                             [*args, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def update_run(self, run_id: str, **fields) -> None:
        if not fields:
            return
        for k in ("progress", "summary"):
            if k in fields:
                fields[f"{k}_json"] = dumps(fields.pop(k))
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE runs SET {sets} WHERE run_id = :run_id", {**fields, "run_id": run_id})

    def count_status(self, *statuses: str) -> int:
        marks = ",".join("?" * len(statuses))
        with self._conn() as c:
            return c.execute(f"SELECT COUNT(*) FROM runs WHERE status IN ({marks})", statuses).fetchone()[0]

    def oldest_queued(self) -> str | None:
        with self._conn() as c:
            r = c.execute("SELECT run_id FROM runs WHERE status = 'queued' ORDER BY started_at, rowid LIMIT 1").fetchone()
        return r["run_id"] if r else None

    def delete_run(self, run_id: str) -> None:
        with self._conn() as c:
            for t in ("windows", "flows", "drift_events", "adaptation_events", "model_versions", "alert_triage",
                      "alert_history", "export_log"):
                c.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))
            c.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    def get_control(self, run_id: str) -> str:
        with self._conn() as c:
            r = c.execute("SELECT control FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return r["control"] if r else "cancel"

    def delete_run_results(self, run_id: str) -> None:
        with self._conn() as c:
            for t in ("windows", "flows", "drift_events", "adaptation_events", "model_versions"):
                c.execute(f"DELETE FROM {t} WHERE run_id = ?", (run_id,))

    # ---------- worker writes ----------
    def write_window(self, run_id: str, window: dict, flows: list[dict], drift: list[dict], adapt: list[dict]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO windows VALUES (?,?,?,?,?,?,?,?)",
                (run_id, window["window"], window["start"], window["end"], window["n_flows"],
                 window["model_version"], dumps(window["metrics"]), dumps(window["drift_scores"])),
            )
            c.executemany(
                "INSERT OR REPLACE INTO flows (run_id, flow_id, window, row_index, ts, true_label, predicted_label, "
                "decision, confidence, attack_score, novelty_score, is_unknown, unknown_reason, is_novel_class, "
                "model_version, probabilities_json, features_json, src, dst, protocol) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, f["flow_id"], f["window"], f["row_index"], f["ts"], f["true_label"], f["predicted_label"],
                  f["decision"], f["confidence"], f["attack_score"], f["novelty_score"], int(f["is_unknown"]),
                  f["unknown_reason"], int(f["is_novel_class"]), f["model_version"], dumps(f["probabilities"]),
                  None if f["features"] is None else dumps(f["features"]), f.get("src"), f.get("dst"),
                  f.get("protocol")) for f in flows],
            )
            c.executemany(
                "INSERT OR REPLACE INTO drift_events VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(run_id, d["event_id"], d["window"], d["method"], d["score"], d["threshold"], d["window_start"],
                  d["window_end"], d["detected_at"], dumps(d["details"])) for d in drift],
            )
            c.executemany(
                "INSERT OR REPLACE INTO adaptation_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(run_id, a["event_id"], a["window"], a["decision"], a["reason"], a["trigger"], a["from_version"],
                  a["to_version"], dumps(a["validation"]), dumps(a["cost"]), a["created_at"]) for a in adapt],
            )

    def write_model(self, run_id: str, m: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO model_versions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (run_id, m["version"], m["parent_version"], m["created_window"], m["status"], dumps(m["classes"]),
                 m["train_rows"], m["train_seconds"], m["model_bytes"], m["created_at"]),
            )

    def set_model_status(self, run_id: str, version: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE model_versions SET status = ? WHERE run_id = ? AND version = ?", (status, run_id, version))

    # ---------- reads ----------
    def windows(self, run_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM windows WHERE run_id = ? ORDER BY window", (run_id,)).fetchall()
        return [{**dict(r), "metrics": loads(r["metrics_json"]), "drift": loads(r["drift_json"])} for r in rows]

    def flows(self, run_id: str, filters: dict, sort: str, desc: bool, offset: int, limit: int,
              with_details: bool = False) -> tuple[list[dict], int]:
        where, args = ["run_id = ?"], [run_id]
        for key, col in (("window", "window"), ("decision", "decision"), ("true_label", "true_label"),
                         ("predicted_label", "predicted_label"), ("model_version", "model_version")):
            if filters.get(key) is not None:
                where.append(f"{col} = ?")
                args.append(filters[key])
        if filters.get("is_unknown") is not None:
            where.append("is_unknown = ?")
            args.append(int(filters["is_unknown"]))
        if filters.get("is_novel_class") is not None:
            where.append("is_novel_class = ?")
            args.append(int(filters["is_novel_class"]))
        if filters.get("min_attack_score") is not None:
            where.append("attack_score >= ?")
            args.append(filters["min_attack_score"])
        if filters.get("max_confidence") is not None:
            where.append("confidence <= ?")
            args.append(filters["max_confidence"])
        if filters.get("misclassified"):
            where.append("(decision != true_label)")
        clause = " AND ".join(where)
        cols = "*" if with_details else "run_id, flow_id, window, row_index, ts, true_label, predicted_label, " \
               "decision, confidence, attack_score, novelty_score, is_unknown, unknown_reason, is_novel_class, model_version, " \
               "src, dst, protocol"
        order = f"{FLOW_SORTS.get(sort, 'flow_id')} {'DESC' if desc else 'ASC'}, flow_id ASC"
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM flows WHERE {clause}", args).fetchone()[0]
            rows = c.execute(f"SELECT {cols} FROM flows WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                             [*args, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def iter_flows(self, run_id: str, batch: int = 20000):
        last = -1
        while True:
            with self._conn() as c:
                rows = c.execute("SELECT * FROM flows WHERE run_id = ? AND flow_id > ? ORDER BY flow_id LIMIT ?",
                                 (run_id, last, batch)).fetchall()
            if not rows:
                return
            yield from (dict(r) for r in rows)
            last = rows[-1]["flow_id"]

    def flow(self, run_id: str, flow_id: int) -> dict | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM flows WHERE run_id = ? AND flow_id = ?", (run_id, flow_id)).fetchone()
        return dict(r) if r else None

    def label_counts(self, run_id: str) -> dict[str, dict[str, int]]:
        with self._conn() as c:
            t = c.execute("SELECT true_label, COUNT(*) n FROM flows WHERE run_id = ? GROUP BY true_label", (run_id,))
            true = {r["true_label"]: r["n"] for r in t.fetchall()}
            d = c.execute("SELECT decision, COUNT(*) n FROM flows WHERE run_id = ? GROUP BY decision", (run_id,))
            dec = {r["decision"]: r["n"] for r in d.fetchall()}
        return {"true": true, "decision": dec}

    def drift_events(self, run_id: str, method: str | None, offset: int, limit: int) -> tuple[list[dict], int]:
        where, args = "run_id = ?", [run_id]
        if method:
            where += " AND method = ?"
            args.append(method)
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM drift_events WHERE {where}", args).fetchone()[0]
            rows = c.execute(f"SELECT * FROM drift_events WHERE {where} ORDER BY window, event_id LIMIT ? OFFSET ?",
                             [*args, limit, offset]).fetchall()
        return [{**dict(r), "details": loads(r["details_json"])} for r in rows], total

    def adaptation_events(self, run_id: str, decision: str | None, offset: int, limit: int) -> tuple[list[dict], int]:
        where, args = "run_id = ?", [run_id]
        if decision:
            where += " AND decision = ?"
            args.append(decision)
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) FROM adaptation_events WHERE {where}", args).fetchone()[0]
            rows = c.execute(f"SELECT * FROM adaptation_events WHERE {where} ORDER BY event_id LIMIT ? OFFSET ?",
                             [*args, limit, offset]).fetchall()
        return [{**dict(r), "validation": loads(r["validation_json"]), "cost": loads(r["cost_json"])} for r in rows], total

    def model_versions(self, run_id: str) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM model_versions WHERE run_id = ? ORDER BY version", (run_id,)).fetchall()
        return [{**dict(r), "classes": loads(r["classes_json"])} for r in rows]

    # ---------- dataset validations ----------
    def save_validation(self, report: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO dataset_validations VALUES (?,?,?,?,?,?,?,?)",
                (report["dataset_id"], report["profile"], int(report["valid"]), report["rows"], report["fingerprint"],
                 report["sha256"], dumps(report), str(report["validated_at"])),
            )

    def get_validation(self, dataset_id: str, profile: str | None = None) -> dict | None:
        q = "SELECT report_json FROM dataset_validations WHERE dataset_id = ?"
        args: list = [dataset_id]
        if profile:
            q += " AND profile = ?"
            args.append(profile)
        with self._conn() as c:
            r = c.execute(q + " ORDER BY validated_at DESC LIMIT 1", args).fetchone()
        return loads(r["report_json"]) if r else None

    # ---------- alerts (flows whose decision is not benign) ----------
    _SEVERITY = ("CASE WHEN f.decision = 'UNKNOWN' THEN 'review' "
                 "WHEN f.attack_score >= 0.9 THEN 'critical' WHEN f.attack_score >= 0.75 THEN 'high' "
                 "WHEN f.attack_score >= 0.5 THEN 'medium' ELSE 'low' END")

    def _alert_where(self, run_id: str, benign: list[str], filters: dict) -> tuple[str, list]:
        marks = ",".join("?" * len(benign)) or "''"
        where = [f"f.run_id = ?", f"f.decision NOT IN ({marks})"]
        args: list = [run_id, *benign]
        if filters.get("severity"):
            where.append(f"{self._SEVERITY} = ?")
            args.append(filters["severity"])
        if filters.get("state"):
            where.append("COALESCE(t.state, 'open') = ?")
            args.append(filters["state"])
        if filters.get("window") is not None:
            where.append("f.window = ?")
            args.append(filters["window"])
        if filters.get("decision"):
            where.append("f.decision = ?")
            args.append(filters["decision"])
        if filters.get("flow_id") is not None:
            where.append("f.flow_id = ?")
            args.append(filters["flow_id"])
        return " AND ".join(where), args

    def alerts(self, run_id: str, benign: list[str], filters: dict, sort: str, desc: bool,
               offset: int, limit: int) -> tuple[list[dict], int]:
        where, args = self._alert_where(run_id, benign, filters)
        order_col = {"flow_id": "f.flow_id", "confidence": "f.confidence", "attack_score": "f.attack_score",
                     "timestamp": "f.ts"}.get(sort, "f.flow_id")
        base = f"FROM flows f LEFT JOIN alert_triage t ON t.run_id = f.run_id AND t.flow_id = f.flow_id WHERE {where}"
        with self._conn() as c:
            total = c.execute(f"SELECT COUNT(*) {base}", args).fetchone()[0]
            rows = c.execute(
                f"""SELECT f.flow_id, f.window, f.ts, f.true_label, f.predicted_label, f.decision, f.confidence,
                    f.src, f.dst, f.protocol,
                    f.attack_score, f.novelty_score, f.unknown_reason, f.is_novel_class, f.model_version,
                    {self._SEVERITY} AS severity, COALESCE(t.state, 'open') AS state, t.note, t.updated_at,
                    t.updated_by {base} ORDER BY {order_col} {'DESC' if desc else 'ASC'}, f.flow_id DESC
                    LIMIT ? OFFSET ?""",
                [*args, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def alert_summary(self, run_id: str, benign: list[str], today_prefix: str) -> dict:
        where, args = self._alert_where(run_id, benign, {})
        with self._conn() as c:
            r = c.execute(
                f"""SELECT COUNT(*) AS total,
                    SUM(COALESCE(t.state, 'open') = 'open') AS open,
                    SUM(COALESCE(t.state, 'open') = 'investigating') AS investigating,
                    SUM(COALESCE(t.state, 'open') = 'resolved') AS resolved,
                    SUM({self._SEVERITY} = 'critical' AND COALESCE(t.state, 'open') != 'resolved') AS critical,
                    SUM(f.decision = 'UNKNOWN' AND COALESCE(t.state, 'open') != 'resolved') AS under_review,
                    SUM(t.state = 'resolved' AND t.updated_at LIKE ?) AS resolved_today
                    FROM flows f LEFT JOIN alert_triage t ON t.run_id = f.run_id AND t.flow_id = f.flow_id
                    WHERE {where}""",
                [today_prefix + "%", *args]).fetchone()
        return {k: int(r[k] or 0) for k in r.keys()}

    def set_alert_state(self, run_id: str, flow_id: int, state: str, note: str | None, by: str) -> str:
        now = utcnow()
        with self._conn() as c:
            prev = c.execute("SELECT state FROM alert_triage WHERE run_id = ? AND flow_id = ?",
                             (run_id, flow_id)).fetchone()
            prev_state = prev["state"] if prev else "open"
            c.execute("INSERT OR REPLACE INTO alert_triage VALUES (?,?,?,?,?,?)", (run_id, flow_id, state, note, by, now))
            c.execute("INSERT INTO alert_history (run_id, flow_id, from_state, to_state, note, updated_by, at) "
                      "VALUES (?,?,?,?,?,?,?)", (run_id, flow_id, prev_state, state, note, by, now))
        return prev_state

    def alert_history(self, run_id: str, flow_id: int) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT from_state, to_state, note, updated_by, at FROM alert_history "
                             "WHERE run_id = ? AND flow_id = ? ORDER BY id", (run_id, flow_id)).fetchall()
        return [dict(r) for r in rows]

    # ---------- policies ----------
    def policies(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM policies ORDER BY version DESC").fetchall()
        return [{**dict(r), "body": loads(r["body_json"])} for r in rows]

    def policy(self, version: int | None = None) -> dict | None:
        q = "SELECT * FROM policies WHERE " + ("version = ?" if version is not None else "status = 'active'")
        with self._conn() as c:
            r = c.execute(q, () if version is None else (version,)).fetchone()
        return {**dict(r), "body": loads(r["body_json"])} if r else None

    def add_policy(self, body: dict, note: str, by: str) -> int:
        with self._conn() as c:
            c.execute("UPDATE policies SET status = 'superseded' WHERE status = 'active'")
            nxt = (c.execute("SELECT MAX(version) FROM policies").fetchone()[0] or 0) + 1
            c.execute("INSERT INTO policies VALUES (?,?,?,?,?,?)", (nxt, "active", note, by, dumps(body), utcnow()))
        return nxt

    # ---------- export log ----------
    def log_export(self, run_id: str, fmt: str, kind: str | None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO export_log (run_id, format, kind, at) VALUES (?,?,?,?)", (run_id, fmt, kind, utcnow()))

    def export_stats(self, since_iso: str) -> dict:
        with self._conn() as c:
            n = c.execute("SELECT COUNT(*) FROM export_log WHERE at >= ?", (since_iso,)).fetchone()[0]
            last = c.execute("SELECT run_id, format, kind, at FROM export_log ORDER BY id DESC LIMIT 1").fetchone()
            completed = c.execute("SELECT COUNT(*) FROM runs WHERE status = 'completed'").fetchone()[0]
        return {"exports_since": n, "last_export": dict(last) if last else None, "completed_runs": completed}

    # ---------- users & sessions ----------
    def create_user(self, row: dict) -> int:
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        with self._conn() as c:
            cur = c.execute(f"INSERT INTO users ({cols}) VALUES ({marks})", row)
            return int(cur.lastrowid)

    def user_by(self, field: str, value) -> dict | None:
        assert field in ("id", "email", "google_sub")
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM users WHERE {field} = ?", (value,)).fetchone()
        return dict(r) if r else None

    def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = :{k}" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE users SET {sets} WHERE id = :id", {**fields, "id": user_id})

    def count_users(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create_session(self, token_hash: str, user_id: int, expires_at: str, client: str | None) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (utcnow(),))
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?)", (token_hash, user_id, utcnow(), expires_at, client))

    def session_user(self, token_hash: str) -> tuple[dict, str] | None:
        with self._conn() as c:
            r = c.execute(
                "SELECT u.*, s.expires_at AS session_expires FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?", (token_hash, utcnow())).fetchone()
        if not r:
            return None
        d = dict(r)
        return d, d.pop("session_expires")

    def delete_session(self, token_hash: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id: int, keep: str | None = None) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep or ""))
