# SentinelAI — Product Requirements Document (PRD)

**Version:** 1.0 · **Date:** 10 October 2026  
**Product:** Flutter desktop research console for drift-aware open-world network intrusion detection.

## 1. Summary
SentinelAI is a local-first Flutter desktop app that visualizes offline dataset replay, intrusion predictions, drift events, selective adaptation decisions, and reproducible research experiments. Python/FastAPI owns all ML logic. MVP is not a production security appliance.

## 2. Goals
- Validate supported IDS CSV datasets and preserve provenance.
- Replay data in chronological windows.
- Inspect flow predictions, unknown/review state, drift events, and adaptation decisions.
- Compare static, retrained, continual-learning, and proposed methods.
- Export reproducible metrics, configuration, predictions, and logs.
- Explicitly distinguish demo, replayed, and experimental data.

## 3. Non-goals
Live packet capture, automatic blocking, production SOC deployment, cloud accounts, or claims of guaranteed zero-day detection.

## 4. Screens
1. **Overview:** KPI cards, trends, alerts, adaptation log, dataset/replay status.
2. **Traffic Explorer:** paginated flow table, filters, prediction/score, feature details.
3. **Threat Detection:** class distribution, unknown/review queue, confusion matrix and metrics.
4. **Drift Monitor:** reference/current window comparison, detector score/threshold, event history.
5. **Adaptation Center:** proposed/accepted/rejected/rollback decisions, validation and model versions.
6. **Experiments:** run configuration, status, baselines, metrics, ablations and export.
7. **Settings:** API health, local data paths, theme and diagnostics.

## 5. Functional requirements
- Health endpoint and visible connection state.
- Dataset schema validation before runs.
- Deterministic chronological replay with pause/resume/step/stop.
- Flow prediction and uncertainty display; unknown means unfamiliar/uncertain, not confirmed malicious.
- Drift event includes method, score, threshold, window and timestamp.
- Adaptation event includes decision, reason, model versions, validation result and cost.
- Metrics include macro-F1, per-class recall, FPR, PR-AUC where suitable, unknown rejection, forgetting, adaptation delay, latency and resource cost.
- Fair comparisons expose dataset, split, window and metric definitions.
- CSV/JSON exports include run ID and provenance.
- Demo data carries persistent DEMO labels.

## 6. Architecture
- **Frontend:** Flutter/Dart desktop.
- **Backend:** Python FastAPI + Pydantic.
- **Worker:** separate background process/task for long experiments.
- **ML:** scikit-learn, LightGBM/XGBoost, PyTorch; drift and open-world modules.
- **Storage:** local dataset files; SQLite optional; CSV/JSON outputs.
- **API:** localhost by default; use pagination; long jobs return run IDs.

## 7. API endpoints
- `GET /api/v1/health`
- `GET /api/v1/datasets`
- `POST /api/v1/datasets/validate`
- `POST /api/v1/experiments`
- `GET /api/v1/experiments`
- `GET /api/v1/experiments/{run_id}`
- `POST /api/v1/experiments/{run_id}/start`
- `POST /api/v1/experiments/{run_id}/cancel`
- `GET /api/v1/experiments/{run_id}/metrics`
- `GET /api/v1/experiments/{run_id}/flows`
- `GET /api/v1/experiments/{run_id}/drift-events`
- `GET /api/v1/experiments/{run_id}/adaptation-events`
- `GET /api/v1/experiments/{run_id}/export?format=csv`

## 8. Design system
- Background `#0B1020`; panels `#121A2B`; elevated `#172238`; border `#27354D`.
- Text `#F0F5FF`; secondary `#91A1BB`; cyan `#38D9F5`.
- Success `#45D6A1`; warning `#FFB454`; danger `#FF667D`; analysis `#9A8CFF`.
- Persistent sidebar, compact cards, high-contrast text, readable tables, visible status text/icons (not color alone).

## 9. Repository layout
```text
sentinelai/
  app_flutter/lib/{core,features}/
  app_flutter/test/
  backend/app/{api,schemas,services,ml,storage,workers}/
  backend/tests/
  experiments/{configs,results}/
  docs/{PRD.md,API.md,RESEARCH_PROTOCOL.md}
```

## 10. Acceptance criteria
- App reports backend health accurately.
- Dataset validation reports missing/invalid columns before execution.
- Replay is chronological and reproducible for fixed configuration/seed.
- Predictions, drift and adaptation events are inspectable and traceable.
- Metrics are independently verified by Python tests and tied to a run/window.
- Exports preserve configuration and provenance.
- Demo values never mix silently with real results.
- UI remains responsive during backend jobs.

## 11. Research integrity and safeguards
- Train preprocessing only on training data.
- Separate ground truth for evaluation from the unlabeled stream available to adaptation.
- Unknown is not equivalent to malicious; drift is not equivalent to attack.
- Reference validation is not a formal safety guarantee.
- No live capture or automatic blocking in MVP.
- Novelty must be established by comparing the final algorithm with closest prior work.

## 12. Phases
P0 UI prototype → P1 API connection → P2 offline replay → P3 metrics/exports → P4 drift/adaptation → P5 paper-ready plots and reproducibility.
