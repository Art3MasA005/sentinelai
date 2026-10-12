from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import get_repo
from app.config import Settings, get_settings
from app.ml.demo_data import DEMO_DATASET_ID, write_demo_dataset
from app.ml.profiles import BUILTIN_PROFILES
from app.schemas.common import Page
from app.schemas.datasets import DatasetInfo, DatasetProfile, ValidateRequest, ValidationReport
from app.services import datasets as svc
from app.storage.repository import Repository

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=Page[DatasetInfo])
def list_datasets(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
                  settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    items = svc.list_datasets(settings.datasets_dir, repo)
    start = (page - 1) * page_size
    return Page(items=items[start:start + page_size], total=len(items), page=page, page_size=page_size)


@router.get("/profiles", response_model=list[DatasetProfile])
def list_profiles():
    return list(BUILTIN_PROFILES.values())


@router.post("/validate", response_model=ValidationReport)
def validate(req: ValidateRequest, settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    """Validate schema, types, timestamps and labels. Runs are refused until this passes."""
    return svc.validate(settings.datasets_dir, repo, req.dataset_id, req.profile, req.custom_profile)


@router.get("/validation", response_model=ValidationReport | None)
def last_validation(dataset_id: str, profile: str | None = None, repo: Repository = Depends(get_repo)):
    return repo.get_validation(dataset_id, profile)


class ImportRequest(BaseModel):
    source: str = Field(..., description="Local path of a .zip, a folder of CSVs, or a .csv file")
    name: str = Field(..., min_length=1, max_length=64)
    profile: str | None = None
    overwrite: bool = False


@router.post("/import", response_model=DatasetInfo, status_code=201)
def import_dataset(req: ImportRequest, settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    """Copy a real dataset (e.g. CIC-IDS2017 GeneratedLabelledFlows.zip) into data/datasets/<name>/."""
    from pathlib import Path

    ds = svc.import_dataset(settings.datasets_dir, Path(req.source.strip().strip('"')), req.name, req.profile,
                            req.overwrite)
    return next(d for d in svc.list_datasets(settings.datasets_dir, repo) if d.id == ds.id)


class DemoRequest(BaseModel):
    rows: int = Field(30000, ge=1000, le=500_000)
    seed: int = 7
    overwrite: bool = False


@router.post("/demo", response_model=DatasetInfo)
def create_demo(req: DemoRequest, settings: Settings = Depends(get_settings), repo: Repository = Depends(get_repo)):
    """Generate the synthetic DEMO dataset (always flagged data_origin=demo)."""
    write_demo_dataset(settings.datasets_dir, req.rows, req.seed, req.overwrite)
    return next(d for d in svc.list_datasets(settings.datasets_dir, repo) if d.id == DEMO_DATASET_ID)
