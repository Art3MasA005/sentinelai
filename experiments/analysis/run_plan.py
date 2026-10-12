"""Run experiment variants inline.

usage (from backend/): .venv/Scripts/python.exe ../experiments/analysis/run_plan.py PLAN.json [worker_index n_workers]
PLAN.json: {"group": "...", "base": "<config path, relative to backend/>", "seeds": [1,2,3],
            "set": {...common dotted overrides...},
            "variants": [{"name": "...", "set": {"adaptation.method": "nova", ...}}, ...]}
Run names are "<group> · <variant> · seed <n>", which paper_results.py groups by. Runs whose name already
completed are skipped, so a plan can be resumed or extended; start several workers (0..n-1) in parallel.
Plans used for the paper are in experiments/plans/.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.cli import _services  # noqa: E402
from app.schemas.experiments import ExperimentConfig  # noqa: E402


def deep_set(d: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
worker, n_workers = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (0, 1)
settings, repo, exps = _services()
base = json.loads(Path(plan["base"]).read_text(encoding="utf-8"))
db = sqlite3.connect(settings.db_path)
done = {r[0] for r in db.execute("select name from runs where status='completed'")}

jobs = []
for v in plan["variants"]:
    for seed in plan["seeds"]:
        jobs.append((v, seed))
for i, (v, seed) in enumerate(jobs):
    if i % n_workers != worker:
        continue
    name = f"{plan['group']} · {v['name']} · seed {seed}"
    if name in done:
        continue
    cfg = json.loads(json.dumps(base))
    for k, val in {**plan.get("set", {}), **v.get("set", {})}.items():
        deep_set(cfg, k, val)
    cfg["seed"] = seed
    cfg["name"] = name
    run = exps.create(ExperimentConfig.model_validate(cfg))
    t0 = time.time()
    run = exps.start(run.run_id, inline=True)
    o = (run.summary or {}).get("overall") or {}
    print(f"[{run.run_id}] {name}: {run.status} {time.time() - t0:.0f}s macro_f1={o.get('macro_f1')} "
          f"uauroc={o.get('unknown_auroc')} detect_f1={o.get('detect_f1')} detect_fpr={o.get('detect_fpr')} "
          f"labels={o.get('labels_used')} err={run.error}", flush=True)
