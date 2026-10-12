"""Live progress of experiment plans: runs done per group, running runs (window x/y, ETA), and the
running mean of the comparison metrics per method.

usage (from backend/):  .venv\\Scripts\\python.exe ..\\experiments\\analysis\\progress.py [--watch SECONDS]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "experiments" / "plans"
DB = ROOT / "data" / "sentinel.db"


def expected() -> dict[str, int]:
    out = {}
    for p in sorted(PLANS.glob("*.json")):
        plan = json.loads(p.read_text(encoding="utf-8"))
        out[plan["group"]] = len(plan["variants"]) * len(plan["seeds"])
    return out


def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def snapshot() -> str:
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
    rows = db.execute("select name, status, progress_json, summary_json, started_at from runs").fetchall()
    exp = expected()
    lines = [f"SentinelAI experiments  {datetime.now():%H:%M:%S}", ""]

    done = defaultdict(int)
    by_method = defaultdict(lambda: defaultdict(list))
    running = []
    for name, status, prog, summ, started in rows:
        parts = [p.strip() for p in name.split("·")]
        if len(parts) < 3:
            continue
        group, method = parts[0], parts[1]
        if group not in exp:
            continue
        if status == "completed":
            done[group] += 1
            o = json.loads(summ or "{}").get("overall", {})
            for k in ("macro_f1_ow", "detect_f1", "detect_fpr", "unknown_auroc"):
                if o.get(k) is not None:
                    by_method[group, method][k].append(o[k])
        elif status in ("running", "paused", "queued"):
            running.append((name, json.loads(prog or "{}"), parse_time(started)))

    total_done = sum(done.values())
    total = sum(exp.values())
    lines.append(f"Overall: {total_done}/{total} runs ({100 * total_done / max(total, 1):.0f}%)")
    for g, n in exp.items():
        bar = "#" * round(20 * done[g] / n) + "." * (20 - round(20 * done[g] / n))
        lines.append(f"  {g:24s} [{bar}] {done[g]:3d}/{n}")

    lines += ["", "Running now:"]
    if not running:
        lines.append("  (none)")
    now = datetime.now(timezone.utc)
    for name, p, started in running:
        w, tw = p.get("window", 0), p.get("total_windows", 0) or 0
        eta = ""
        if started and w and tw:
            el = (now - started).total_seconds()
            eta = f"  ~{max(el / w * (tw - w), 0) / 60:.0f} min left"
        lines.append(f"  {name[:60]:60s} {p.get('phase', '?'):13s} window {w}/{tw}{eta}")

    lines += ["", f"{'Results so far (mean over finished seeds)':44s} {'n':>2s} {'OW-F1':>7s} {'Det-F1':>7s} "
                  f"{'FPR':>6s} {'U-AUROC':>8s}"]
    for (g, m), d in sorted(by_method.items(), key=lambda kv: (kv[0][0], -sum(kv[1]["macro_f1_ow"]) /
                                                                      max(len(kv[1]["macro_f1_ow"]), 1))):
        mean = {k: sum(v) / len(v) for k, v in d.items() if v}
        lines.append(f"  {(g + ' · ' + m)[:42]:42s} {len(d['macro_f1_ow']):2d} {mean.get('macro_f1_ow', 0):7.3f} "
                     f"{mean.get('detect_f1', 0):7.3f} {100 * mean.get('detect_fpr', 0):5.1f}% "
                     f"{mean.get('unknown_auroc', 0):8.3f}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", type=int, default=0, help="refresh every N seconds (Ctrl+C to stop)")
    a = ap.parse_args()
    while True:
        text = snapshot()
        if a.watch:
            os.system("cls" if os.name == "nt" else "clear")
        print(text, flush=True)
        if not a.watch:
            return
        time.sleep(a.watch)


if __name__ == "__main__":
    main()
