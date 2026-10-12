"""Dataset discovery under the local datasets directory and pre-run validation.

A dataset is either a single CSV file or a folder of CSVs. A folder may contain a
`sentinel_dataset.json` manifest: {"name", "profile", "is_demo", "files": [ordered csv names]}.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.ml.data import file_fingerprint, read_first_line, validate_files
from app.ml.demo_data import MANIFEST
from app.ml.profiles import detect_profile, get_profile
from app.schemas.datasets import DatasetInfo, DatasetProfile, ValidationReport, ValidationSummary
from app.services.errors import ServiceError
from app.storage.repository import Repository


@dataclass
class ResolvedDataset:
    id: str
    name: str
    path: Path
    files: list[Path]
    is_demo: bool
    manifest_profile: str | None

    @property
    def data_origin(self) -> str:
        return "demo" if self.is_demo else "replayed"


def _resolve_inside(root: Path, dataset_id: str) -> Path:
    p = (root / dataset_id).resolve()
    if root.resolve() not in (p, *p.parents) or p == root.resolve():
        raise ServiceError(f"Dataset '{dataset_id}' is outside the datasets directory.", 400)
    if not p.exists():
        raise ServiceError(f"Dataset '{dataset_id}' not found.", 404)
    return p


def resolve(root: Path, dataset_id: str) -> ResolvedDataset:
    p = _resolve_inside(root, dataset_id)
    manifest: dict = {}
    if p.is_dir():
        mf = p / MANIFEST
        if mf.exists():
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        if manifest.get("files"):
            files = [p / f for f in manifest["files"]]
            missing = [f.name for f in files if not f.exists()]
            if missing:
                raise ServiceError(f"Manifest lists missing files: {', '.join(missing)}", 422)
        else:
            files = sorted(f for f in p.iterdir() if f.suffix.lower() == ".csv")
    elif p.suffix.lower() == ".csv":
        files = [p]
    else:
        raise ServiceError(f"'{dataset_id}' is not a CSV file or folder.", 400)
    if not files:
        raise ServiceError(f"Dataset '{dataset_id}' contains no CSV files.", 422)
    is_demo = bool(manifest.get("is_demo")) or p.name.upper().startswith("DEMO") or \
        all(f.name.upper().startswith("DEMO") for f in files)
    return ResolvedDataset(dataset_id, manifest.get("name", p.stem), p, files, is_demo, manifest.get("profile"))


def list_datasets(root: Path, repo: Repository) -> list[DatasetInfo]:
    out = []
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        if p.name.startswith(".") or not (p.is_dir() or p.suffix.lower() == ".csv"):
            continue
        try:
            ds = resolve(root, p.name)
        except ServiceError:
            continue
        detected = ds.manifest_profile or detect_profile(read_first_line(ds.files[0]))
        last = repo.get_validation(ds.id)
        summary = None
        if last:
            summary = ValidationSummary(profile=last["profile"], valid=last["valid"] and
                                        last["fingerprint"] == file_fingerprint(ds.files),
                                        rows=last["rows"], validated_at=datetime.fromisoformat(str(last["validated_at"])))
        out.append(DatasetInfo(
            id=ds.id, name=ds.name, path=str(ds.path), files=[f.name for f in ds.files],
            size_bytes=sum(f.stat().st_size for f in ds.files), data_origin=ds.data_origin, is_demo=ds.is_demo,
            detected_profile=detected, last_validation=summary,
        ))
    return out


def pick_profile(ds: ResolvedDataset, name: str | None, custom: DatasetProfile | None) -> DatasetProfile:
    if custom:
        return custom
    chosen = name or ds.manifest_profile or detect_profile(read_first_line(ds.files[0]))
    if not chosen:
        raise ServiceError("Could not detect the dataset schema; pass `profile` or `custom_profile`.", 422)
    try:
        return get_profile(chosen)
    except KeyError as e:
        raise ServiceError(str(e), 422) from None


def validate(root: Path, repo: Repository, dataset_id: str, profile_name: str | None,
             custom: DatasetProfile | None) -> ValidationReport:
    ds = resolve(root, dataset_id)
    profile = pick_profile(ds, profile_name, custom)
    report = validate_files(ds.id, ds.files, profile, ds.is_demo)
    repo.save_validation(report.model_dump(mode="json"))
    return report


def require_valid(root: Path, repo: Repository, dataset_id: str, profile: DatasetProfile) -> dict:
    """Raise unless the dataset has a passing validation for this profile that is still current."""
    ds = resolve(root, dataset_id)
    report = repo.get_validation(dataset_id, profile.name)
    if report is None:
        raise ServiceError(f"Dataset '{dataset_id}' has not been validated with profile '{profile.name}'. "
                           "Call POST /api/v1/datasets/validate first.", 409)
    if not report["valid"]:
        raise ServiceError(f"Dataset '{dataset_id}' failed validation: {'; '.join(report['errors'])}", 409)
    if report["fingerprint"] != file_fingerprint(ds.files):
        raise ServiceError(f"Dataset '{dataset_id}' changed on disk since validation; validate again.", 409)
    return report


_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _day_order(names: list[str]) -> list[str]:
    """CIC-style files are named by weekday; replay needs them Monday→Friday, not alphabetically."""
    def key(n: str):
        low = n.lower()
        day = next((i for i, d in enumerate(_WEEKDAYS) if d in low), 99)
        # within a day: morning before afternoon
        return day, 0 if "morning" in low else 1 if "afternoon" in low else 0, low
    return sorted(names, key=key)


def import_dataset(root: Path, source: Path, name: str, profile: str | None, overwrite: bool = False) -> ResolvedDataset:
    """Copy the CSVs of a ZIP archive, a folder or a single CSV into data/datasets/<name>/ with a manifest.

    Only *.csv members are extracted (pcap and other files are skipped) and every member is written by its
    base name, so archive paths can never escape the dataset folder.
    """
    if not _SAFE_NAME.match(name):
        raise ServiceError("Dataset name may use letters, digits, '.', '_' and '-' (max 64).", 422)
    if profile:
        get_profile(profile)  # fail early on a typo
    source = source.expanduser()
    if not source.exists():
        raise ServiceError(f"'{source}' does not exist.", 404)
    dest = root / name
    if dest.exists() and not overwrite:
        raise ServiceError(f"A dataset named '{name}' already exists.", 409)
    tmp = root / f".{name}.importing"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    copied: list[str] = []
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as z:
                for info in z.infolist():
                    base = Path(info.filename).name.strip()
                    if info.is_dir() or not base.lower().endswith(".csv") or "__macosx" in info.filename.lower():
                        continue
                    with z.open(info) as src, open(tmp / base, "wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)
                    copied.append(base)
        elif source.is_dir():
            for f in sorted(source.rglob("*.csv")):
                shutil.copyfile(f, tmp / f.name)
                copied.append(f.name)
        elif source.suffix.lower() == ".csv":
            shutil.copyfile(source, tmp / source.name)
            copied.append(source.name)
        else:
            raise ServiceError("Give a .zip archive, a folder of CSVs, or a .csv file.", 415)
        if not copied:
            raise ServiceError("No CSV files found in the source.", 422)
        files = _day_order(sorted(set(copied)))
        detected = profile or detect_profile(read_first_line(tmp / files[0]))
        (tmp / MANIFEST).write_text(json.dumps({
            "name": name,
            "profile": detected,
            "is_demo": False,
            "files": files,
            "source": str(source),
            "imported_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2), encoding="utf-8")
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return resolve(root, name)
