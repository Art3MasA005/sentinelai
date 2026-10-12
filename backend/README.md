# SentinelAI backend

This is the FastAPI and Python ML backend for the SentinelAI research console. It replays datasets offline only. It does not capture live traffic and does not block anything.

## Setup (Windows, Python 3.11+)

```powershell
cd sentinelai\backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.lock.txt` pins the exact versions that were tested.

## Run

```powershell
.\.venv\Scripts\python.exe -m app.cli make-demo                    # synthetic DEMO dataset
.\.venv\Scripts\python.exe -m app.cli serve                        # http://127.0.0.1:8765/docs
.\.venv\Scripts\python.exe -m app.cli validate DEMO_sentinel_synthetic
.\.venv\Scripts\python.exe -m app.cli run ..\experiments\configs\demo_static.json ..\experiments\configs\demo_guarded_selective.json
.\.venv\Scripts\python.exe -m pytest                               # 39 tests
```

To use a real dataset, put its CSV files in `sentinelai/data/datasets/<name>/`. You can optionally add a `sentinel_dataset.json` file with this content: `{"profile": "cicids2017", "files": [...ordered...]}`. Then validate the dataset and create a run.

Settings come from environment variables:
- `SENTINEL_DATASETS_DIR`
- `SENTINEL_RESULTS_DIR`
- `SENTINEL_DB_PATH`
- `SENTINEL_PORT`

## Layout

```
app/
  api/        HTTP routes (health, datasets, experiments)
  schemas/    Pydantic request/response models
  services/   dataset discovery+validation, run lifecycle, exports
  ml/         data loading, preprocessing, models, open-world, drift, label oracle, strategies, metrics, pipeline
  storage/    SQLite (WAL), all SQL in repository.py
  workers/    worker subprocess per run + supervisor
  cli.py      serve / make-demo / validate / run
tests/        metrics, data, pipeline reproducibility, end-to-end API
```

See `../docs/API.md` for the API reference and `../docs/RESEARCH_PROTOCOL.md` for the methodology.
