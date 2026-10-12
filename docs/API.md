# SentinelAI API reference (v1)

Base URL: `http://127.0.0.1:8765/api/v1` (localhost only by default). Interactive docs: `http://127.0.0.1:8765/docs`. OpenAPI JSON: `/openapi.json`. You can generate Dart models from the OpenAPI JSON.

## Conventions

- **Errors:** `{"detail": "<message>"}` with these status codes: 400 (bad input), 404 (not found), 409 (wrong state, e.g. dataset not validated or run already running) and 422 (schema or validation problem).
- **Pagination:** list endpoints take `page` (starting at 1) and `page_size`, and return:
  ```json
  {"items": [...], "total": 1234, "page": 1, "page_size": 50, "data_origin": "demo"}
  ```
- **Data origin:** every run, page, metrics response and export carries `data_origin`:
  - `demo` means synthetic data. The UI must keep a visible **DEMO** label on it.
  - `replayed` means a real dataset replayed offline.
- **Timestamps:** ISO-8601 in UTC.
- **Long jobs:** `POST /experiments/{run_id}/start` returns `202` straight away. Poll `GET /experiments/{run_id}` (about once a second) to follow `status` and `progress`.
- **Run status:** `created → queued → running ⇄ paused → completed | failed | cancelled`. At most `SENTINEL_MAX_WORKERS` (default 2) runs are running or paused at once; later starts wait as `queued` and start automatically.
- **Sign-in:** send `Authorization: Bearer <token>` from `/auth/login`, `/auth/signup` or `/auth/google`. It is required on every route except `/health` and `/auth/*` only when `SENTINEL_AUTH_REQUIRED=true`. Browser downloads (`/export`, `/figures`) may pass `?token=` instead.
- **`UNKNOWN`:** this decision means the flow is unfamiliar or uncertain and needs review. It does **not** mean the flow is malicious. Drift is not evidence of an attack either.

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Returns `status` (`ok`/`degraded`) and `checks` (database, datasets_dir, results_dir). Also returns `active_workers`, local `paths`, library versions and the available `profiles`. Use it for the connection indicator and the Settings screen. |

## Accounts

| Method | Path | Notes |
|---|---|---|
| GET | `/auth/config` | Public. Returns `auth_required`, `google_enabled`, `google_client_id` and the `roles` list for the signup form. |
| POST | `/auth/signup` | Body: `name`, `email`, `phone` (with country code), `password` (8+ characters, letters and digits), plus optional `country`, `institution`, `role` and `remember`. Returns `{token, expires_at, user}`. |
| POST | `/auth/login` | Body: `email`, `password`, `remember`. After 5 failures, the email is locked for 60 s (429). |
| POST | `/auth/google` | Body: `id_token`. The backend verifies the token with Google, then creates the account or links it to an existing one with the same email. |
| POST | `/auth/google/desktop` | Windows build: `{code, redirect_uri, code_verifier}` from the loopback PKCE flow. |
| GET / PUT | `/auth/me` | Read or update the profile. |
| POST | `/auth/me/password` | `{current_password, new_password}`. Signs out the user's other sessions. |
| PUT / GET | `/auth/me/avatar` | PUT takes raw PNG or JPEG bytes (max 2 MB). GET returns the image. |
| POST | `/auth/logout` | Ends the current session. |

Accounts are stored only in the local SQLite database. Passwords are hashed with PBKDF2-SHA256 (600,000 iterations), and sessions are stored hashed.

## Datasets

| Method | Path | Notes |
|---|---|---|
| GET | `/datasets` | Datasets found in `data/datasets/`, each a CSV file or a folder of CSVs. Each item has `id`, `name`, `files`, `size_bytes`, `is_demo`, `data_origin`, `detected_profile`, and `last_validation`, which is `null` or `{profile, valid, rows, validated_at}`. |
| GET | `/datasets/profiles` | Built-in schema profiles: `sentinel_demo`, `cicids2017`, `cicids2018` and `unswnb15`. |
| POST | `/datasets/validate` | Body: `{"dataset_id": "...", "profile": null, "custom_profile": null}`. Returns a full report. **A run can't start until validation passes.** |
| GET | `/datasets/validation?dataset_id=..&profile=..` | The last validation report, or `null`. |
| POST | `/datasets/demo` | Body: `{"rows": 30000, "seed": 7, "overwrite": false}`. Generates the DEMO dataset. |

The validation report includes these fields:
- `valid`, `errors[]` and `warnings[]`
- `missing_columns[]`
- `invalid_columns[]`: `{column, issue, count, fraction, examples}`
- `column_warnings[]`
- `timestamp_parse_failures`, `timestamp_min`, `timestamp_max` and `out_of_order_fraction`
- `label_distribution`, `nan_cells` and `inf_cells`
- `sha256` and `fingerprint`

## Experiments

| Method | Path | Notes |
|---|---|---|
| POST | `/experiments` | Creates a run from an `ExperimentConfig` (see below) and returns `ExperimentRun` with status `created`. |
| POST | `/experiments/batch` | Body: `{base: ExperimentConfig, methods: [..] or null, seeds: [..], start: true}`. Creates one run per (method, seed), all with the same `group_id`. |
| GET | `/experiments?status=&method=&page=&page_size=` | Paginated list of runs. |
| DELETE | `/experiments/{run_id}` | Deletes a run that is not running, paused or queued: its database rows and `experiments/results/<run_id>/`. |
| GET | `/experiments/compare?run_ids=a,b,c` | Metrics side by side, plus a fairness check. `fair` is false when any of these differ: dataset, profile, seed, model, split, open-world, drift or label policy. The keys that differ are listed in `differences`. `mixed_data_origin` is true when demo and real runs are mixed. `aggregates` gives the mean and sample std per method over runs that differ only by seed. A seed difference does not make the comparison unfair when every method used the same set of seeds. |
| GET | `/experiments/compare/figures?run_ids=a,b` | ZIP of comparison figures (PNG + PDF): macro-F1 over windows, and per-method mean ± std bars. |
| GET | `/experiments/{run_id}` | The run, with `status`, `progress {phase, window, total_windows, flows_processed}`, `config`, `config_hash`, `dataset_sha256`, `summary` and `error`. |
| POST | `/experiments/{run_id}/start` | 202. Returns 409 if the dataset is not validated, has changed since validation, or the run is already running or completed. |
| POST | `/experiments/{run_id}/pause` | Pauses after the current window. |
| POST | `/experiments/{run_id}/resume` | Continues the replay. |
| POST | `/experiments/{run_id}/step` | While paused, processes exactly one window and then pauses again. |
| POST | `/experiments/{run_id}/cancel` | Cooperative: the worker stops after the current window. If it doesn't stop within 20 s, it is killed. |
| GET | `/experiments/{run_id}/overview` | One call for the Overview screen: `kpis`, per-window `trends`, recent drift and adaptation events, `progress` and `is_demo`. |
| GET | `/experiments/{run_id}/metrics?include_windows=true` | `overall`, `confusion_matrix {labels, matrix}`, `windows[]`, `definitions` (the text of each metric definition) and `provenance` (split, integrity checks, open-world thresholds and classes). |
| GET | `/experiments/{run_id}/flows` | Paginated flow table. The filters and sort options are listed below this table. |
| GET | `/experiments/{run_id}/flows/{flow_id}` | Flow detail: the raw `features`, the top-5 `probabilities` and everything in the list view. |
| GET | `/experiments/{run_id}/class-distribution` | `{true: {label: n}, decision: {label: n}}`. |
| GET | `/experiments/{run_id}/drift-events?method=` | Paginated. Each event has `method`, `score`, `threshold`, `window`, `window_start`, `window_end`, `detected_at` and `details`. |
| GET | `/experiments/{run_id}/adaptation-events?decision=` | Paginated. Each event has `decision` (`proposed`, `accepted`, `rejected` or `rollback`), `reason`, `trigger`, `from_version`, `to_version`, `validation{...}` and `cost{...}`. |
| GET | `/experiments/{run_id}/models` | Model versions: `version`, `parent_version`, `status` (`active`, `candidate`, `retired`, `rejected` or `rolled_back`), `classes`, `train_rows`, `train_seconds` and `model_bytes`. |
| GET | `/experiments/{run_id}/logs?tail=200` | The worker log lines. |
| GET | `/experiments/{run_id}/export?format=csv&kind=predictions` | `format` is `csv`, `json`, `zip` or `figures`. `figures` returns a ZIP of PNG + PDF plots: window metrics, decisions, drift, confusion matrix and adaptation timeline. For CSV, `kind` is one of `predictions`, `windows`, `drift`, `adaptation` or `models`. Every CSV row carries `run_id`, `data_origin`, `dataset_sha256` and `config_hash`, and DEMO files get a `DEMO_` filename prefix. |

The flows endpoint accepts these query parameters:
- **Filters:** `window`, `decision`, `true_label`, `predicted_label`, `is_unknown`, `is_novel_class`, `misclassified`, `min_attack_score`, `max_confidence` and `model_version`.
- **Sorting:** `sort` is one of `flow_id`, `timestamp`, `confidence`, `attack_score` or `novelty_score`. Add `desc=true` to reverse the order.
- **Review queue:** to get it, use `is_unknown=true&sort=confidence`.

### ExperimentConfig (defaults shown)

```json
{
  "name": "untitled",
  "dataset_id": "DEMO_sentinel_synthetic",
  "profile": null,
  "custom_profile": null,
  "seed": 42,
  "model": {"kind": "hist_gb", "params": {}, "class_weight": null, "min_class_samples": 5},
  "split": {"train_fraction": 0.3, "val_fraction": 0.2, "window_size": 2000, "max_rows": null, "holdout_classes": []},
  "openworld": {"method": "msp+centroid", "msp_quantile": 0.02, "distance_quantile": 0.99},
  "drift": {"detectors": ["ks", "confidence"], "ks_alpha": 0.01, "ks_threshold": 0.3, "psi_threshold": 0.2,
            "confidence_threshold": 0.1, "cooldown_windows": 2, "reference_update": "on_adaptation",
            "max_reference_rows": 5000},
  "labels": {"delay_windows": 1, "budget": 1.0},
  "adaptation": {"method": "static", "retrain_every": 5, "memory_windows": 10, "buffer_size": 20000,
                 "trigger": "drift_or_novelty", "novelty_trigger_rate": 0.15, "validation_guard": true,
                 "min_gain": 0.0, "max_forgetting": 0.05, "rollback": true, "rollback_margin": 0.05,
                 "rollback_watch_windows": 2},
  "store_features": true,
  "notes": ""
}
```

Allowed values:
- `model.kind`: `hist_gb`, `random_forest`, `lightgbm`, `xgboost` (needs the `xgboost` package), `logreg` or `mlp`. `mlp` is a PyTorch feed-forward network that runs on the CPU; its `params` are `hidden`, `epochs`, `lr`, `dropout` and `batch_size`.
- `adaptation.method`: `static`, `periodic_retrain`, `continual_replay` or `guarded_selective`.
- `drift.detectors`: any of `ks`, `psi` and `confidence`.

## Screen → endpoint map

| Screen | Endpoints |
|---|---|
| Overview | `/health`, `/experiments/{id}/overview`, `/datasets` |
| Traffic Explorer | `/experiments/{id}/flows`, `/flows/{flow_id}` |
| Threat Detection | `/metrics` (confusion matrix, per-class recall), `/class-distribution`, `/flows?is_unknown=true` |
| Drift Monitor | `/metrics` (`windows[].drift_scores` for score and threshold over time), `/drift-events` |
| Adaptation Center | `/adaptation-events`, `/models` |
| Experiments | `/experiments` (CRUD and control), `/compare`, `/export`, `/logs` |
| Settings | `/health` (paths, versions, profiles) |
