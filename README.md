# SentinelAI / NOVA

Code, experiment configurations and paper sources for **NOVA** (Novelty-aware, Open-world, Validated Adaptation),
a drift-aware, open-world adaptation loop for flow-based network intrusion detection under scarce and delayed
analyst labels. The repository also contains SentinelAI, the research console (FastAPI backend and Flutter
desktop app) that ran every experiment and stores the configuration, data hash, model versions, adaptation
decisions and per-flow predictions of each run.

SentinelAI replays published datasets **offline**. It does not capture live traffic and does not block anything.

## Layout

```
backend/            Python package `app` (replay engine, label oracle, open-world scoring, strategies, metrics) + tests
app_flutter/        desktop console (optional; not needed to reproduce the paper)
experiments/
  configs/          base configuration per dataset
  plans/            every experiment of the paper: group, seeds and per-variant overrides
  analysis/         scripts that run plans and regenerate every table and figure
  paper/            generated tables (.tex/.csv) and figures used by both papers
paper/              conference version (IEEE, LaTeX)
paper_journal/      journal version (Elsevier elsarticle, LaTeX)
docs/               research protocol, literature notes
data/               local only (datasets, SQLite database); never committed
```

## 1. Environment

Tested on Windows 11, Python 3.14, 16-core CPU; the optional MLP runs use an NVIDIA GPU.

```powershell
cd backend
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt   # exact versions used for the paper
.\.venv\Scripts\python.exe -m pytest                                 # unit and integration tests
```

`requirements.txt` explains how to install the CPU or CUDA build of PyTorch. PyTorch is only needed for the MLP
experiment and the representation-learning probe.

## 2. Datasets

The datasets are not redistributed here; download them from their providers and accept their terms.

| Name used in configs | Source | Notes |
|---|---|---|
| `CIC-IDS2017` | Canadian Institute for Cybersecurity, CIC-IDS2017, `GeneratedLabelledFlows` (TrafficLabelling CSVs) | the variant with timestamps; afternoon times without AM/PM are restored by the `cicids2017` profile |
| `CSE-CIC-IDS2018-k8` | CSE-CIC-IDS2018, "Processed Traffic Data for ML" CSVs | thinned to one row in eight per file: `python experiments/analysis/thin_dataset.py SRC DST 8` |
| `UNSW-NB15` | UNSW Canberra, UNSW-NB15 CSVs (`UNSW-NB15_1..4.csv`) with the feature names applied | the `unswnb15` profile reads them |

Import each dataset into `data/datasets/<name>/` and validate it:

```powershell
.\.venv\Scripts\python.exe -m app.cli import-dataset <zip-or-folder> --name CIC-IDS2017 --profile cicids2017
.\.venv\Scripts\python.exe -m app.cli validate CIC-IDS2017
```

Validation reports row counts, the label distribution and timestamp problems. Each run records a SHA-256 of the
dataset files and of its configuration (`run.json`, `provenance`).

## 3. Reproduce the experiments

Every experiment of the papers is a plan in `experiments/plans/`. Run a plan from `backend/`; several workers can
run in parallel, and completed runs are skipped, so an interrupted plan can simply be restarted:

```powershell
# one worker
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json
# three workers in parallel (separate terminals)
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 0 3
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 1 3
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 2 3
```

| Plan | Paper section |
|---|---|
| `cic2017_main`, `ids2018_main`, `unsw_main` | main comparison, 10% budget |
| `cic2017_low`, `ids2018_low`, `unsw_low` | 1% budget |
| `cic2017_abl`, `ids2018_abl`, `unsw_abl` | ablations |
| `cic2017_det` | centroid vs k-NN detector |
| `cic2017_mlp` | MLP classifier |
| `cic2017_delay`, `cic2017_review` | label-delay and threshold sensitivity |

`experiments/analysis/progress.py --watch 30` shows live progress. A run of 70 windows takes 2 to 25 minutes
depending on the method.

## 4. Regenerate tables and figures

From `backend/`, after the runs:

```powershell
.\.venv\Scripts\python.exe ..\experiments\analysis\paper_results.py      # main tables, figures, budget table
.\.venv\Scripts\python.exe ..\experiments\analysis\journal_tables.py     # per-class, cost, ablation, sensitivity
.\.venv\Scripts\python.exe ..\experiments\analysis\review_analyses.py    # guard statistics, metric decomposition, bootstrap CIs
.\.venv\Scripts\python.exe ..\experiments\analysis\split_check.py        # random vs chronological split
.\.venv\Scripts\python.exe ..\experiments\analysis\dataset_audit.py      # class counts, first appearance, duplicates
.\.venv\Scripts\python.exe ..\experiments\analysis\meta_probe.py         # representation-learning probe (GPU)
```

Outputs go to `experiments/paper/`. Build the papers with `latexmk -pdf main.tex` in `paper/` or
`paper_journal/`.

## 5. What each run stores

`experiments/results/<run_id>/` holds `config.json`, `run.json` (summary, integrity block, dataset hashes),
`windows.csv` (per-window metrics, labels used so far), `adaptation.csv` (every proposed, accepted, rejected or
rolled-back model with its validation numbers), `models.csv`, `drift.csv`, `run.log` and `predictions.csv.gz`
(one row per flow: true label, decision, confidence, open-world score, model version).

## Citation and licence

\[Citation to be added on publication.\] \[Licence to be chosen before publication.\]
