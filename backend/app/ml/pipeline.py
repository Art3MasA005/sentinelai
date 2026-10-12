"""Experiment engine: deterministic chronological replay with prediction, drift detection,
open-world scoring and adaptation. Storage-agnostic; results go to a RunSink."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np

from app.ml import metrics as M
from app.ml.data import load_dataset
from app.ml.drift import DriftMonitor
from app.ml.labels import LabelOracle
from app.ml.models import DeployedModel, train_model
from app.ml.preprocessing import Preprocessor
from app.ml.strategies import STRATEGIES
from app.schemas.datasets import DatasetProfile
from app.schemas.experiments import ExperimentConfig

PAUSE_POLL_SECONDS = 0.25


class Cancelled(Exception):
    pass


class RunSink(Protocol):
    def log(self, message: str) -> None: ...
    def progress(self, phase: str, window: int, total_windows: int, flows: int) -> None: ...
    def control(self) -> str: ...  # "run" | "pause" | "step" | "cancel"
    def ack_step(self) -> None: ...
    def set_paused(self, paused: bool) -> None: ...
    def write_model(self, model: DeployedModel, status: str) -> None: ...
    def set_model_status(self, version: int, status: str) -> None: ...
    def write_window(self, window: dict, flows: list[dict], drift_events: list[dict], adaptation_events: list[dict]) -> None: ...
    def finish(self, summary: dict) -> None: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentEngine:
    def __init__(self, config: ExperimentConfig, files: list[Path], profile: DatasetProfile,
                 data_origin: str, sink: RunSink):
        self.cfg = config
        self.files = files
        self.profile = profile
        self.data_origin = data_origin
        self.sink = sink
        self.seed = config.seed
        self.benign = set(profile.benign_labels)
        # State visible to strategies.
        self.window = -1
        self.current: DeployedModel | None = None
        self.previous: DeployedModel | None = None
        self.drift_events: list[dict] = []
        self.unknown_rate = 0.0
        self._next_version = 1
        self._adapt_seq = 0
        self._window_events: list[dict] = []
        self._model_changed = False
        self._train_seconds = 0.0
        self._trainings = 0
        self._ref_cache: dict[int, float] = {}

    # ---------- helpers used by strategies ----------
    def window_x(self, w: int) -> np.ndarray:
        s, e = self._bounds[w]
        return self.x_stream[s:e]

    def train(self, x: np.ndarray, y: np.ndarray, calib: tuple[np.ndarray, np.ndarray] | None = None,
              sample_weight: np.ndarray | None = None) -> DeployedModel:
        """Train a candidate. Open-world thresholds are calibrated on the reference validation set plus
        `calib`, labelled flows the candidate was NOT trained on (lets newly learned classes get their own
        thresholds instead of the strict fallback)."""
        cal_x, cal_y = self.ref_x, self.ref_y
        if calib is not None and len(calib[1]):
            cal_x = np.vstack([self.ref_x, calib[0]])
            cal_y = np.concatenate([np.asarray(self.ref_y).astype(str), np.asarray(calib[1]).astype(str)])
        m = train_model(x, np.asarray(y).astype(str), cal_x, cal_y, self.cfg.model, self.cfg.openworld,
                        self.seed, self._next_version, self.current.version if self.current else None,
                        self.window, sample_weight)
        self._next_version += 1
        self._train_seconds += m.train_seconds
        self._trainings += 1
        self.sink.write_model(m, "candidate" if self.current else "active")
        self.sink.log(f"window {self.window}: trained model v{m.version} on {m.train_rows} rows "
                      f"in {m.train_seconds:.2f}s, classes={m.classes}"
                      + (f", left out rare classes {m.meta['excluded_rare_classes']}"
                         if m.meta.get("excluded_rare_classes") else ""))
        return m

    def score(self, model: DeployedModel, x: np.ndarray, y: np.ndarray, min_support: int = 1) -> float:
        """Open-world macro-F1 (fixed class set, UNKNOWN credited for classes the model does not know) of
        `model` on labelled data, so models that know different classes are compared on the same task."""
        y = np.asarray(y).astype(str)
        if min_support > 1 and len(y):
            # Classes with only a handful of labels make macro-F1 jump by 1/n_classes per flow; leave them
            # out of model-vs-model decisions.
            cls, cnt = np.unique(y, return_counts=True)
            keep = np.isin(y, cls[cnt >= min_support])
            x, y = x[keep], y[keep]
        if len(y) == 0:
            return 0.0
        out = model.predict(x, self.benign)
        return M.macro_f1_ow(y.astype(object), out["decision"], ~np.isin(y, model.classes))

    def ref_score(self, model: DeployedModel) -> float:
        if model.version not in self._ref_cache:
            self._ref_cache[model.version] = self.score(model, self.ref_x, self.ref_y)
        return self._ref_cache[model.version]

    def validation_report(self, cand: DeployedModel, hold_x, hold_y, passed, min_support: int = 1) -> dict:
        rep = {"ref_f1_current": self.ref_score(self.current), "ref_f1_candidate": self.ref_score(cand),
               "passed": passed}
        if hold_y is not None:
            rep.update(recent_f1_current=self.score(self.current, hold_x, hold_y, min_support),
                       recent_f1_candidate=self.score(cand, hold_x, hold_y, min_support),
                       holdout_rows=int(len(hold_y)))
        return rep

    def cost(self, model: DeployedModel) -> dict:
        return {"train_seconds": model.train_seconds, "train_rows": model.train_rows,
                "model_bytes": model.model_bytes, "labels_used_total": self.oracle.labels_used}

    def log_event(self, decision: str, reason: str, trigger: str, from_v: int, to_v: int | None,
                  validation: dict, cost: dict) -> None:
        self._adapt_seq += 1
        self._window_events.append({
            "event_id": f"adapt-{self._adapt_seq:05d}", "window": self.window, "decision": decision,
            "reason": reason, "trigger": trigger, "from_version": from_v, "to_version": to_v,
            "validation": validation, "cost": cost, "created_at": _now(),
        })
        self.sink.log(f"window {self.window}: adaptation {decision} v{from_v}->{to_v}: {reason}")

    def accept(self, cand: DeployedModel, reason: str, trigger: str, validation: dict) -> None:
        old = self.current
        self.log_event("accepted", reason, trigger, old.version, cand.version, validation, self.cost(cand))
        self.sink.set_model_status(old.version, "retired")
        self.sink.set_model_status(cand.version, "active")
        self.previous, self.current = old, cand
        self._model_changed = True

    def reject(self, cand: DeployedModel, reason: str, trigger: str, validation: dict) -> None:
        self.log_event("rejected", reason, trigger, self.current.version, cand.version, validation, self.cost(cand))
        self.sink.set_model_status(cand.version, "rejected")

    def rollback(self, reason: str, trigger: str, validation: dict) -> None:
        bad, good = self.current, self.previous
        self.log_event("rollback", reason, trigger, bad.version, good.version, validation, {})
        self.sink.set_model_status(bad.version, "rolled_back")
        self.sink.set_model_status(good.version, "active")
        self.current, self.previous = good, None
        self._model_changed = True

    # ---------- control ----------
    def _wait_for_control(self) -> None:
        ctl = self.sink.control()
        if ctl == "cancel":
            raise Cancelled()
        if ctl == "pause":
            self.sink.set_paused(True)
            while (ctl := self.sink.control()) == "pause":
                time.sleep(PAUSE_POLL_SECONDS)
            if ctl == "cancel":
                raise Cancelled()
            self.sink.set_paused(False)

    # ---------- main loop ----------
    def run(self) -> dict:
        cfg, sp = self.cfg, self.cfg.split
        self.sink.progress("loading", 0, 0, 0)
        data = load_dataset(self.files, self.profile, sp.max_rows)
        n = len(data.labels)
        n_train = int(n * sp.train_fraction)
        n_val = max(int(n_train * sp.val_fraction), 1)
        fit_end = n_train - n_val
        labels = data.labels.astype(str)
        holdout = set(sp.holdout_classes)

        fit_idx = np.arange(0, fit_end)
        val_idx = np.arange(fit_end, n_train)
        if holdout:
            fit_idx = fit_idx[~np.isin(labels[fit_idx], list(holdout))]
            val_idx = val_idx[~np.isin(labels[val_idx], list(holdout))]
        holdout_removed = int((fit_end - len(fit_idx)) + (n_val - len(val_idx)))
        # The reference set measures forgetting of what the initial model learned, so it keeps only classes that
        # occur in the fit period. A class that first appears in the reference period (SSH-Patator in CIC-IDS2017)
        # was never learned; keeping it would make "forgetting" reward or punish unknown detection instead.
        unseen_ref = ~np.isin(labels[val_idx], np.unique(labels[fit_idx]))
        ref_dropped = {str(c): int(k) for c, k in zip(*np.unique(labels[val_idx][unseen_ref], return_counts=True))}
        val_idx = val_idx[~unseen_ref]
        stream_idx = np.arange(n_train, n)
        if len(stream_idx) == 0 or len(fit_idx) == 0:
            raise ValueError("Split leaves no training or stream rows; adjust split.train_fraction.")
        self._bounds = [(s, min(s + sp.window_size, len(stream_idx))) for s in range(0, len(stream_idx), sp.window_size)]
        total_windows = len(self._bounds)
        self.sink.log(f"loaded {n} rows ({data.skipped_rows} skipped); train={len(fit_idx)} val={len(val_idx)} "
                      f"stream={len(stream_idx)} windows={total_windows}")

        self.sink.progress("preprocessing", 0, total_windows, 0)
        pre = Preprocessor(data.numeric_columns, data.categorical_columns).fit(data.frame.iloc[fit_idx])
        self.train_x = pre.transform(data.frame.iloc[fit_idx])
        self.train_y = labels[fit_idx].astype(object)
        self.ref_x = pre.transform(data.frame.iloc[val_idx])
        self.ref_y = labels[val_idx]
        self.x_stream = pre.transform(data.frame.iloc[stream_idx])
        y_stream = labels[stream_idx]
        ts_stream = data.timestamps[stream_idx]
        rows_stream = data.row_index[stream_idx]
        integrity = {
            "preprocessor_fitted_rows": pre.fitted_rows,
            "preprocessor_fit_on": "training period only (excluding reference validation and stream)",
            "train_end_timestamp": float(data.timestamps[n_train - 1]),
            "stream_start_timestamp": float(ts_stream[0]),
            "chronological_split": bool(data.timestamps[n_train - 1] <= ts_stream[0]),
            "holdout_rows_removed": holdout_removed,
            "reference_rows_dropped_unseen_classes": ref_dropped,
            "adaptation_label_access": "label oracle only (delay/budget enforced)",
        }

        self.sink.progress("training", 0, total_windows, 0)
        self.current = self.train(self.train_x, self.train_y)
        initial_classes = list(self.current.classes)
        self.oracle = LabelOracle([y_stream[s:e] for s, e in self._bounds], cfg.labels, self.seed)
        monitor = DriftMonitor(cfg.drift, self.seed)
        monitor.set_reference(self.ref_x, self.current.predict(self.ref_x, self.benign)["confidence"], -1)
        strategy = STRATEGIES[cfg.adaptation.method](cfg.adaptation, self)

        pooled = {k: [] for k in ("true", "decision", "unknown", "novel", "attack", "uscore")}
        ref_scores: list[float] = []
        latencies: list[float] = []
        first_seen: dict[str, int] = {}
        known_from: dict[str, int] = {c: -1 for c in initial_classes}
        drift_log: list[dict] = []
        adapt_log: list[dict] = []
        flows_done = 0

        for w, (s, e) in enumerate(self._bounds):
            self._wait_for_control()
            stepping = self.sink.control() == "step"
            self.window = w
            xw, yw = self.x_stream[s:e], y_stream[s:e]
            model = self.current
            t0 = time.perf_counter()
            out = model.predict(xw, self.benign)
            lat_ms = (time.perf_counter() - t0) * 1000 / max(len(yw), 1)
            latencies.append(lat_ms)
            novel = ~np.isin(yw, model.classes)
            win_metrics = M.evaluate(yw, out["decision"], out["is_unknown"], novel, out["attack_score"], self.benign,
                                     out["unknown_score"])
            win_metrics["latency_ms_per_flow"] = lat_ms
            for c in np.unique(yw):
                first_seen.setdefault(str(c), w)
            for c in model.classes:
                known_from.setdefault(c, w)

            checks = monitor.check(w, xw, out["confidence"])
            self.drift_events = []
            for method, r in checks.items():
                if r["triggered"]:
                    self.drift_events.append({
                        "event_id": f"drift-{w:05d}-{method}", "window": w, "method": method,
                        "score": r["score"], "threshold": r["threshold"],
                        "window_start": float(ts_stream[s]), "window_end": float(ts_stream[e - 1]),
                        "detected_at": _now(), "details": r["details"],
                    })
                    self.sink.log(f"window {w}: drift detected by {method} score={r['score']:.4f} > {r['threshold']}")
            self.unknown_rate = win_metrics["unknown_rate"]
            picked = strategy.select(w, xw, out)
            if picked is not None:
                self.oracle.request(w, picked)

            self._window_events, self._model_changed = [], False
            strategy.step()
            if self._model_changed and cfg.drift.reference_update == "on_adaptation":
                monitor.set_reference(xw, self.current.predict(xw, self.benign)["confidence"], w)
            elif self._model_changed:
                monitor.update_reference_confidence(self.current.predict(self.ref_x, self.benign)["confidence"])
            ref_f1 = self.ref_score(self.current)
            ref_scores.append(ref_f1)
            win_metrics["ref_macro_f1"] = ref_f1
            win_metrics["labels_used_total"] = self.oracle.labels_used

            flows = self._flow_rows(data, stream_idx, s, e, w, yw, ts_stream, rows_stream, out, novel, model)
            window_row = {
                "window": w, "start": float(ts_stream[s]), "end": float(ts_stream[e - 1]), "n_flows": int(e - s),
                "model_version": model.version, "metrics": win_metrics,
                "drift_scores": {m: {k: v for k, v in r.items() if k != "details"} for m, r in checks.items()},
            }
            self.sink.write_window(window_row, flows, self.drift_events, self._window_events)
            drift_log += self.drift_events
            adapt_log += self._window_events
            pooled["true"].append(yw)
            pooled["decision"].append(out["decision"])
            pooled["unknown"].append(out["is_unknown"])
            pooled["novel"].append(novel)
            pooled["attack"].append(out["attack_score"])
            pooled["uscore"].append(out["unknown_score"])
            flows_done += len(yw)
            self.sink.progress("running", w + 1, total_windows, flows_done)
            if stepping:
                self.sink.ack_step()

        cat = {k: np.concatenate(v) for k, v in pooled.items()}
        overall = M.evaluate(cat["true"], cat["decision"], cat["unknown"], cat["novel"], cat["attack"], self.benign,
                             cat["uscore"])
        y_open = np.where(cat["novel"], M.UNKNOWN, cat["true"]).astype(object)
        cm_labels, cm = M.confusion(y_open, cat["decision"])
        f_max, f_final = M.forgetting(ref_scores)

        accepted_windows = sorted(a["window"] for a in adapt_log if a["decision"] in ("accepted", "rollback"))
        delays = []
        for d in drift_log:
            nxt = next((aw for aw in accepted_windows if aw >= d["window"]), None)
            delays.append({"event_id": d["event_id"], "delay": None if nxt is None else nxt - d["window"]})
        resolved = [d["delay"] for d in delays if d["delay"] is not None]
        novel_delay = {c: (known_from[c] - w0 if c in known_from else None)
                       for c, w0 in first_seen.items() if c not in initial_classes}

        overall.update(
            ref_macro_f1_initial=ref_scores[0] if ref_scores else None,
            ref_macro_f1_final=ref_scores[-1] if ref_scores else None,
            forgetting_max=f_max,
            forgetting_final=f_final,
            adaptation_delay_windows={"mean": float(np.mean(resolved)) if resolved else None,
                                      "resolved": len(resolved), "unresolved": len(delays) - len(resolved)},
            novel_class_delay_windows=novel_delay,
            latency_ms_per_flow=float(np.mean(latencies)) if latencies else None,
            latency_ms_per_flow_median=float(np.median(latencies)) if latencies else None,
            train_seconds_total=self._train_seconds,
            n_trainings=self._trainings,
            labels_used=self.oracle.labels_used,
            label_fraction=self.oracle.labels_used / max(len(y_stream), 1),
            model_bytes_final=self.current.model_bytes,
            drift_events=len(drift_log),
            adaptations_accepted=sum(a["decision"] == "accepted" for a in adapt_log),
            adaptations_rejected=sum(a["decision"] == "rejected" for a in adapt_log),
            rollbacks=sum(a["decision"] == "rollback" for a in adapt_log),
        )
        summary = {
            "data_origin": self.data_origin,
            "method": cfg.adaptation.method,
            "windows": total_windows,
            "flows": int(len(y_stream)),
            "overall": overall,
            "confusion_matrix": {"labels": [str(l) for l in cm_labels], "matrix": cm.tolist()},
            "split": {
                "rows_total": n, "skipped_rows": data.skipped_rows, "train_rows": int(len(fit_idx)),
                "validation_rows": int(len(val_idx)), "stream_rows": int(len(stream_idx)),
                "window_size": sp.window_size, "holdout_classes": sorted(holdout),
            },
            "integrity": integrity,
            "initial_classes": initial_classes,
            "final_classes": list(self.current.classes),
            "final_model_version": self.current.version,
            "n_features": len(pre.feature_names),
            "feature_names": pre.feature_names,
            "openworld": self.current.openworld.describe(),
        }
        self.sink.finish(summary)
        return summary

    def _flow_rows(self, data, stream_idx, s, e, w, yw, ts, rows, out, novel, model) -> list[dict]:
        feats = (data.frame.iloc[stream_idx[s:e]].to_dict("records") if self.cfg.store_features else [None] * (e - s))
        ctx = data.context.iloc[stream_idx[s:e]].to_dict("records")
        classes = model.classes
        res = []
        for i in range(e - s):
            p = out["proba"][i]
            top = np.argsort(-p)[:5]
            att = out["attack_score"][i]
            nov = out["novelty"][i]
            res.append({
                "flow_id": s + i, "window": w, "row_index": int(rows[s + i]), "ts": float(ts[s + i]),
                "true_label": str(yw[i]), "predicted_label": str(out["predicted"][i]),
                "decision": str(out["decision"][i]), "confidence": float(out["confidence"][i]),
                "attack_score": None if np.isnan(att) else float(att),
                "novelty_score": None if np.isnan(nov) else float(nov),
                "is_unknown": bool(out["is_unknown"][i]), "unknown_reason": out["reason"][i],
                "is_novel_class": bool(novel[i]), "model_version": model.version,
                "src": ctx[i]["src"] or None, "dst": ctx[i]["dst"] or None, "protocol": ctx[i]["protocol"] or None,
                "probabilities": {classes[j]: round(float(p[j]), 6) for j in top},
                "features": _jsonable(feats[i]),
            })
        return res


def _jsonable(rec: dict | None) -> dict | None:
    if rec is None:
        return None
    out = {}
    for k, v in rec.items():
        if isinstance(v, float) and not np.isfinite(v):
            out[k] = None if np.isnan(v) else ("inf" if v > 0 else "-inf")
        elif isinstance(v, (np.integer, np.floating)):
            out[k] = v.item()
        else:
            out[k] = v if v is None or isinstance(v, (int, float, str, bool)) else str(v)
    return out
