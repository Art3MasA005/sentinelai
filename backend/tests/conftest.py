import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


@pytest.fixture(scope="session")
def env(tmp_path_factory):
    """Isolated data/results/db dirs; set before the app reads settings (workers inherit env)."""
    root = tmp_path_factory.mktemp("sentinel")
    os.environ["SENTINEL_DATASETS_DIR"] = str(root / "datasets")
    os.environ["SENTINEL_RESULTS_DIR"] = str(root / "results")
    os.environ["SENTINEL_CONFIGS_DIR"] = str(root / "configs")
    os.environ["SENTINEL_DB_PATH"] = str(root / "sentinel.db")
    from app.config import get_settings
    from app.ml.demo_data import write_demo_dataset
    from app.storage.db import init_db

    get_settings.cache_clear()
    settings = get_settings()
    init_db(settings.db_path)
    write_demo_dataset(settings.datasets_dir, n_rows=6000, seed=3)
    return settings


@pytest.fixture(scope="session")
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def small_config(**adaptation):
    from app.schemas.experiments import ExperimentConfig

    return ExperimentConfig.model_validate({
        "name": "test",
        "dataset_id": "DEMO_sentinel_synthetic",
        "seed": 11,
        "split": {"train_fraction": 0.3, "val_fraction": 0.2, "window_size": 300},
        "drift": {"detectors": ["ks", "psi", "confidence"]},
        "labels": {"delay_windows": 1, "budget": 0.5},
        "adaptation": {"method": "static", **adaptation},
    })
