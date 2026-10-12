"""CSV/JSON/ZIP exports. Every artifact carries the run ID and provenance; DEMO runs are marked in
file names and in every CSV row so demo values can never be mixed silently with real results."""

from __future__ import annotations

import csv
import io
import json
import platform
import zipfile
from collections.abc import Iterable, Iterator
from importlib import metadata
from pathlib import Path

from app.config import APP_VERSION
from app.ml.metrics import DEFINITIONS
from app.storage.db import loads
from app.storage.repository import Repository, utcnow

CSV_KINDS = ("predictions", "windows", "drift", "adaptation", "models")
LIBRARIES = ("numpy", "pandas", "scikit-learn", "scipy", "lightgbm", "fastapi", "pydantic")


def package_version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def provenance(run: dict) -> dict:
    cfg = loads(run["config_json"])
    return {
        "run_id": run["run_id"],
        "run_name": run["name"],
        "status": run["status"],
        "method": run["method"],
        "data_origin": run["data_origin"],
        "is_demo": run["data_origin"] == "demo",
        "dataset_id": run["dataset_id"],
        "dataset_sha256": run["dataset_sha256"],
        "profile": run["profile"],
        "config_hash": run["config_hash"],
        "seed": cfg.get("seed"),
        "created_at": run["created_at"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "exported_at": utcnow(),
        "sentinelai_version": APP_VERSION,
        "python": platform.python_version(),
        "libraries": {p: package_version(p) for p in LIBRARIES},
    }


def file_prefix(run: dict) -> str:
    return f"{'DEMO_' if run['data_origin'] == 'demo' else ''}{run['run_id']}"


def _prov_cols(run: dict) -> dict:
    return {"run_id": run["run_id"], "data_origin": (run["data_origin"] or "").upper(),
            "dataset_sha256": run["dataset_sha256"], "config_hash": run["config_hash"]}


def _rows(repo: Repository, run: dict, kind: str) -> Iterator[dict]:
    rid = run["run_id"]
    if kind == "predictions":
        for f in repo.iter_flows(rid):
            yield {k: v for k, v in f.items() if k not in ("run_id", "features_json")}
    elif kind == "windows":
        for w in repo.windows(rid):
            m = w["metrics"]
            row = {"window": w["window"], "start_ts": w["start_ts"], "end_ts": w["end_ts"], "n_flows": w["n_flows"],
                   "model_version": w["model_version"]}
            row.update({k: v for k, v in m.items() if not isinstance(v, dict)})
            for method, d in (w["drift"] or {}).items():
                row[f"drift_{method}_score"] = d["score"]
                row[f"drift_{method}_threshold"] = d["threshold"]
                row[f"drift_{method}_triggered"] = d["triggered"]
            yield row
    elif kind == "drift":
        rows, _ = repo.drift_events(rid, None, 0, 10**9)
        for r in rows:
            yield {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()
                   if k not in ("run_id", "details_json")}
    elif kind == "adaptation":
        rows, _ = repo.adaptation_events(rid, None, 0, 10**9)
        for r in rows:
            yield {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()
                   if k not in ("run_id", "validation_json", "cost_json")}
    elif kind == "models":
        for m in repo.model_versions(rid):
            yield {k: (json.dumps(v) if isinstance(v, list) else v) for k, v in m.items()
                   if k not in ("run_id", "classes_json")}
    else:
        raise ValueError(f"Unknown export kind '{kind}'. Use one of {CSV_KINDS}.")


def csv_chunks(repo: Repository, run: dict, kind: str) -> Iterable[str]:
    prov = _prov_cols(run)
    buf = io.StringIO()
    writer = None
    for i, row in enumerate(_rows(repo, run, kind)):
        row = {**prov, **row}
        if writer is None:
            writer = csv.DictWriter(buf, fieldnames=list(row.keys()), extrasaction="ignore")
            writer.writeheader()
        writer.writerow(row)
        if i % 5000 == 4999:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()
    if writer is None:
        buf.write(",".join(prov.keys()) + "\n")
    yield buf.getvalue()


def json_bundle(repo: Repository, run: dict) -> dict:
    rid = run["run_id"]
    drift, _ = repo.drift_events(rid, None, 0, 10**9)
    adapt, _ = repo.adaptation_events(rid, None, 0, 10**9)
    return {
        "provenance": provenance(run),
        "config": loads(run["config_json"]),
        "summary": loads(run["summary_json"]),
        "metric_definitions": DEFINITIONS,
        "windows": [{k: v for k, v in w.items() if not k.endswith("_json") and k != "run_id"}
                    for w in repo.windows(rid)],
        "drift_events": [{k: v for k, v in d.items() if not k.endswith("_json") and k != "run_id"} for d in drift],
        "adaptation_events": [{k: v for k, v in a.items() if not k.endswith("_json") and k != "run_id"}
                              for a in adapt],
        "model_versions": [{k: v for k, v in m.items() if not k.endswith("_json") and k != "run_id"}
                           for m in repo.model_versions(rid)],
        "note": "Per-flow predictions are exported separately (format=csv&kind=predictions or format=zip).",
    }


def zip_bytes(repo: Repository, run: dict, log_path: Path | None) -> bytes:
    buf = io.BytesIO()
    prefix = file_prefix(run)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{prefix}/run.json", json.dumps(json_bundle(repo, run), indent=2, default=str))
        z.writestr(f"{prefix}/config.json", json.dumps(loads(run["config_json"]), indent=2))
        for kind in CSV_KINDS:
            z.writestr(f"{prefix}/{kind}.csv", "".join(csv_chunks(repo, run, kind)))
        if log_path and log_path.exists():
            z.write(log_path, f"{prefix}/run.log")
        if run["data_origin"] == "demo":
            z.writestr(f"{prefix}/DEMO_DATA_README.txt",
                       "These results were produced from SYNTHETIC DEMO data. Do not report them as results on "
                       "real network traffic.\n")
    return buf.getvalue()


def write_artifacts(repo: Repository, run_id: str, out_dir: Path) -> None:
    """Persist reproducibility artifacts next to the run log (experiments/results/<run_id>/)."""
    run = repo.get_run(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = "DEMO_" if run["data_origin"] == "demo" else ""
    (out_dir / f"{prefix}run.json").write_text(json.dumps(json_bundle(repo, run), indent=2, default=str),
                                               encoding="utf-8")
    (out_dir / "config.json").write_text(json.dumps(loads(run["config_json"]), indent=2), encoding="utf-8")
    flows_in_file = loads(run["config_json"]).get("flow_storage") == "file"
    for kind in CSV_KINDS:
        if kind == "predictions" and flows_in_file:
            continue  # already streamed to predictions.csv.gz during the run
        with open(out_dir / f"{prefix}{kind}.csv", "w", encoding="utf-8", newline="") as fh:
            for chunk in csv_chunks(repo, run, kind):
                fh.write(chunk)
