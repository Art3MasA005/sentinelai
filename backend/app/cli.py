"""Command line entry points.

  python -m app.cli serve                      # API on 127.0.0.1:8765
  python -m app.cli make-demo                  # generate the DEMO dataset
  python -m app.cli validate <dataset_id> [--profile NAME]
  python -m app.cli run <config.json> [...]    # create + run experiments in this process (reproducible batch)
  python -m app.cli import-dataset <zip|folder|csv> --name CIC-IDS2017 [--profile cicids2017]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.storage.db import init_db
from app.storage.repository import Repository


def _services():
    from app.services.experiments import ExperimentService

    settings = get_settings()
    init_db(settings.db_path)
    repo = Repository(settings.db_path)
    return settings, repo, ExperimentService(settings, repo)


def cmd_serve(args) -> None:
    import uvicorn

    settings = get_settings()
    if args.host not in ("127.0.0.1", "localhost") and not args.allow_remote:
        sys.exit("Refusing to bind to a non-local address without --allow-remote (MVP is local-first).")
    uvicorn.run("app.main:app", host=args.host or settings.host, port=args.port or settings.port, reload=args.reload)


def cmd_make_demo(args) -> None:
    from app.ml.demo_data import write_demo_dataset

    settings = get_settings()
    folder = write_demo_dataset(settings.datasets_dir, args.rows, args.seed, overwrite=args.overwrite)
    print(f"DEMO dataset at {folder}")


def cmd_validate(args) -> None:
    from app.services import datasets as svc

    settings, repo, _ = _services()
    report = svc.validate(settings.datasets_dir, repo, args.dataset_id, args.profile, None)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    sys.exit(0 if report.valid else 1)


def cmd_import(args) -> None:
    from app.services import datasets as svc

    settings, repo, _ = _services()
    ds = svc.import_dataset(settings.datasets_dir, Path(args.source), args.name, args.profile, args.overwrite)
    print(f"Imported {len(ds.files)} CSV file(s) into {ds.path}")
    for f in ds.files:
        print(f"  {f.name}  ({f.stat().st_size / 2**20:.1f} MB)")
    if not args.no_validate:
        print("Validating (this reads every row once)...", flush=True)
        report = svc.validate(settings.datasets_dir, repo, ds.id, None, None)
        print(f"valid={report.valid} rows={report.rows:,} blank_rows={report.blank_rows:,} "
              f"profile={report.profile}")
        for e in report.errors:
            print("  error:", e)
        for w in report.warnings:
            print("  warning:", w)
        print("  labels:", ", ".join(f"{k}={v:,}" for k, v in report.label_distribution.items()))


def cmd_run(args) -> None:
    from app.schemas.experiments import ExperimentConfig
    from app.services import datasets as ds_svc

    settings, repo, exps = _services()
    failed = False
    for path in args.configs:
        cfg = ExperimentConfig.model_validate_json(Path(path).read_text(encoding="utf-8"))
        ds = ds_svc.resolve(settings.datasets_dir, cfg.dataset_id)
        profile = ds_svc.pick_profile(ds, cfg.profile, cfg.custom_profile)
        if repo.get_validation(cfg.dataset_id, profile.name) is None or args.revalidate:
            ds_svc.validate(settings.datasets_dir, repo, cfg.dataset_id, cfg.profile, cfg.custom_profile)
        run = exps.create(cfg)
        print(f"[{run.run_id}] {cfg.name} ({cfg.adaptation.method}) ...", flush=True)
        run = exps.start(run.run_id, inline=True)
        overall = (run.summary or {}).get("overall") or {}
        print(f"[{run.run_id}] {run.status} macro_f1={overall.get('macro_f1')} fpr={overall.get('fpr')} "
              f"unknown_recall={overall.get('unknown_recall')} -> {settings.results_dir / run.run_id}")
        if run.status != "completed":
            print(f"  error: {run.error}")
            failed = True
    sys.exit(1 if failed else 0)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sentinelai")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--reload", action="store_true")
    s.add_argument("--allow-remote", action="store_true")
    s.set_defaults(fn=cmd_serve)

    d = sub.add_parser("make-demo")
    d.add_argument("--rows", type=int, default=30000)
    d.add_argument("--seed", type=int, default=7)
    d.add_argument("--overwrite", action="store_true")
    d.set_defaults(fn=cmd_make_demo)

    v = sub.add_parser("validate")
    v.add_argument("dataset_id")
    v.add_argument("--profile")
    v.set_defaults(fn=cmd_validate)

    i = sub.add_parser("import-dataset", help="copy a .zip / folder / .csv into data/datasets/<name>")
    i.add_argument("source")
    i.add_argument("--name", required=True)
    i.add_argument("--profile")
    i.add_argument("--overwrite", action="store_true")
    i.add_argument("--no-validate", action="store_true")
    i.set_defaults(fn=cmd_import)

    r = sub.add_parser("run")
    r.add_argument("configs", nargs="+")
    r.add_argument("--revalidate", action="store_true")
    r.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
