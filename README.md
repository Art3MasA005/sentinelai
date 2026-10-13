# SentinelAI

SentinelAI is a research console for **network intrusion detection under drift**. It replays published flow
datasets in time order, lets detectors adapt with a limited, delayed budget of analyst labels, and shows what
happens window by window: detections, unknown attacks, drift, model updates and false alarms.

It also contains **NOVA**, our adaptation method, together with the baselines, experiment plans and paper sources
used to evaluate it.

> SentinelAI only **replays recorded datasets offline**. It does not capture live traffic and blocks nothing.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Quick start (10 minutes, no large download)](#2-quick-start-10-minutes-no-large-download)
3. [Using the app](#3-using-the-app)
4. [Real datasets](#4-real-datasets)
5. [Reproduce the paper experiments](#5-reproduce-the-paper-experiments)
6. [Build the Windows installer](#6-build-the-windows-installer)
7. [Run the tests](#7-run-the-tests)
8. [Project layout](#8-project-layout)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. What you need

| Tool | Version | Needed for |
|---|---|---|
| [Python](https://www.python.org/downloads/) | 3.11 or newer (tested with 3.14) | the backend (always) |
| [Git](https://git-scm.com/downloads) | any | cloning the repository |
| [Flutter](https://docs.flutter.dev/get-started/install) | 3.44 or newer | the desktop app (optional; the installer in step 3 does not need it) |
| Visual Studio Build Tools, workload "Desktop development with C++" | 2022 | building the Windows app yourself |
| LaTeX (MiKTeX or TeX Live) with `latexmk` | any recent | building the papers |
| NVIDIA GPU with CUDA | optional | only the MLP experiment and the representation probe |

The commands below are for **Windows PowerShell**. On macOS or Linux, use `.venv/bin/python` instead of
`.\.venv\Scripts\python.exe`.

---

## 2. Quick start (10 minutes, no large download)

### Step 1 — Get the code

```powershell
git clone https://github.com/Art3MasA005/sentinelai.git
cd sentinelai
```

### Step 2 — Set up the backend

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`requirements.txt` installs current versions. To use the **exact versions of the paper** instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt --extra-index-url https://download.pytorch.org/whl/cu130
```

(The lock file pins the CUDA build of PyTorch; the extra index is where pip finds it.)

### Step 3 — Create a small demo dataset

```powershell
.\.venv\Scripts\python.exe -m app.cli make-demo
```

This writes a synthetic dataset (30,000 flows) to `data/datasets/`, so you can try everything before downloading
the real datasets.

### Step 4 — Start the backend

```powershell
.\.venv\Scripts\python.exe -m app.cli serve
```

Leave this window open. The API runs at <http://127.0.0.1:8765>; its interactive documentation is at
<http://127.0.0.1:8765/docs>.

### Step 5 — Open the app

Pick one:

- **Windows installer (easiest).** Run `dist\SentinelAI-Setup-<version>.exe` (build it with step 6 if the
  `dist` folder is empty). The installer asks for the `backend` folder; afterwards the app starts the backend by
  itself, so step 4 is not needed any more.
- **Flutter, in the browser:**

  ```powershell
  cd ..\app_flutter
  flutter pub get
  flutter run -d chrome
  ```

- **Flutter, as a Windows app:** same as above with `flutter run -d windows`.

### Step 6 — Run a first test

In the app, press **⚡ Quick test** in the top bar, choose the demo dataset and **Fast**, and press
**Start test**. The run appears live on the Dashboard and finishes in a minute or two.

---

## 3. Using the app

| Page | What it shows |
|---|---|
| **Dashboard** | the selected run at a glance: flows, attacks, unknown flows, drift, resources |
| **Alerts** | flows reported as attacks or unknown, with triage (open, under review, resolved) |
| **Traffic Monitor** | every replayed flow, its features and class probabilities |
| **Analysis** | macro-F1, unknown AUROC, false-positive rate, confusion matrix, per-window performance |
| **Drift Monitor** | reference vs current traffic and every drift detection |
| **Adaptation Center** | every candidate model and whether it was accepted, rejected or rolled back |
| **Experiments** | import and validate datasets; create, start, pause, step and cancel runs; batches of seeds |
| **Reports** | compare runs (mean ± std over seeds) and export results |
| **Rules** | thresholds, label budget and adaptation policy (versioned) |
| **System** | backend health, workers, resource use and logs |
| **Settings** | backend address, folders and preferences |

The run picker in the top bar chooses which run every page shows. The sun/moon button switches between the dark
and the light theme.

---

## 4. Real datasets

The datasets are not included; download them from their providers and accept their terms.

| Name in SentinelAI | Download | Files to use |
|---|---|---|
| `CIC-IDS2017` | [Canadian Institute for Cybersecurity](https://www.unb.ca/cic/datasets/ids-2017.html) | the labelled flow CSVs **with timestamps** (`*.pcap_ISCX.csv`, "GeneratedLabelledFlows / TrafficLabelling") |
| `CSE-CIC-IDS2018-k8` | [CSE-CIC-IDS2018](https://www.unb.ca/cic/datasets/ids-2018.html) | "Processed Traffic Data for ML Algorithms" (`*_TrafficForML_CICFlowMeter.csv`), thinned as shown below |
| `UNSW-NB15` | [UNSW Canberra](https://research.unsw.edu.au/projects/unsw-nb15-dataset) | `UNSW-NB15_1.csv` … `UNSW-NB15_4.csv` as downloaded (no header row) |

Import each one from `backend\` (a `.zip`, a folder or a single `.csv` works). Import also validates every row:

```powershell
.\.venv\Scripts\python.exe -m app.cli import-dataset "D:\downloads\CIC-IDS2017.zip" --name CIC-IDS2017 --profile cicids2017
.\.venv\Scripts\python.exe -m app.cli import-dataset "D:\downloads\UNSW-NB15" --name UNSW-NB15 --profile unswnb15
```

CSE-CIC-IDS2018 is large (16 million flows). The paper uses a copy that keeps one row in eight of every file
(order preserved). Import the full dataset, make the thinned copy, and validate it:

```powershell
.\.venv\Scripts\python.exe -m app.cli import-dataset "D:\downloads\CSE-CIC-IDS2018" --name CSE-CIC-IDS2018 --profile cicids2018
.\.venv\Scripts\python.exe ..\experiments\analysis\thin_dataset.py CSE-CIC-IDS2018 CSE-CIC-IDS2018-k8 8
.\.venv\Scripts\python.exe -m app.cli validate CSE-CIC-IDS2018-k8 --profile cicids2018
```

You can also import from the app: **Experiments → Import dataset…**.

---

## 5. Reproduce the paper experiments

Every experiment of the papers is a **plan** in `experiments/plans/` (a group of runs: methods × seeds). Run plans
from `backend\`:

```powershell
# one plan, one worker
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json

# the same plan on three workers (three terminals, or three background jobs)
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 0 3
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 1 3
.\.venv\Scripts\python.exe ..\experiments\analysis\run_plan.py ..\experiments\plans\cic2017_main.json 2 3
```

Finished runs are skipped, so an interrupted plan can simply be started again.

| Plans | What they reproduce |
|---|---|
| `cic2017_main`, `ids2018_main`, `unsw_main` | main comparison, label budget 10% (5 seeds) |
| `cic2017_low`, `ids2018_low`, `unsw_low` | label budget 1% (5 seeds) |
| `cic2017_abl`, `ids2018_abl`, `unsw_abl` | ablations, one NOVA component removed (3 seeds) |
| `cic2017_det` | k-NN vs centroid open-world detector |
| `cic2017_delay`, `cic2017_review` | label delay and rejection thresholds |
| `cic2017_mlp` | MLP instead of gradient boosting (uses the GPU if available) |

All plans together are 339 runs, about 60 hours on a 16-core CPU with three runs in parallel. One run of 70
windows takes 2 to 25 minutes. Watch progress with:

```powershell
.\.venv\Scripts\python.exe ..\experiments\analysis\progress.py --watch 30
```

### Regenerate the tables and figures

```powershell
.\.venv\Scripts\python.exe ..\experiments\analysis\paper_results.py      # main tables, figures, 1% budget
.\.venv\Scripts\python.exe ..\experiments\analysis\journal_tables.py     # per-class, cost, ablation, sensitivity
.\.venv\Scripts\python.exe ..\experiments\analysis\review_analyses.py    # bootstrap intervals, guard statistics, metric decomposition
.\.venv\Scripts\python.exe ..\experiments\analysis\split_check.py        # random vs chronological split
.\.venv\Scripts\python.exe ..\experiments\analysis\dataset_audit.py      # class counts, first appearance, duplicates
.\.venv\Scripts\python.exe ..\experiments\analysis\meta_probe.py         # representation-learning probe (GPU)
```

Everything is written to `experiments/paper/`.

### Build the papers

```powershell
cd ..\paper;         latexmk -pdf main.tex   # conference version (IEEE)
cd ..\paper_journal; latexmk -pdf main.tex   # journal version (Elsevier)
```

### What each run stores

Runs are recorded in `data/sentinel.db`, and their files in `experiments/results/<run_id>/`: the configuration,
a summary with dataset hashes (`run.json`), per-window metrics (`windows.csv`), every adaptation decision
(`adaptation.csv`), the model history, drift events, the log, and the per-flow predictions
(`predictions.csv.gz`).

---

## 6. Build the Windows installer

Needs Flutter, Visual Studio Build Tools (C++ workload) and [Inno Setup 6](https://jrsoftware.org/isinfo.php)
(`winget install JRSoftware.InnoSetup`). From `app_flutter\`:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1
```

The installer is written to `dist\SentinelAI-Setup-<version>.exe`. It installs for the current user only (no
administrator rights), adds Start-menu and optional desktop shortcuts, and can be removed from
*Settings → Apps*. The installed app starts the backend from the folder chosen during installation and stops it
when the app closes.

---

## 7. Run the tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest

cd ..\app_flutter
flutter test
```

---

## 8. Project layout

```
backend/          Python backend: replay engine, label oracle, open-world detector, NOVA and baselines, metrics, API
app_flutter/      desktop / web app (Flutter) and the Windows installer script
experiments/
  configs/        base configuration per dataset
  plans/          every experiment of the papers (group, seeds, variants)
  analysis/       scripts that run plans and produce all tables and figures
  paper/          generated tables and figures used by the papers
paper/            conference paper (LaTeX)
paper_journal/    journal paper (LaTeX)
docs/             research protocol, literature notes, API and product notes
data/             local only, never committed: datasets and the run database
```

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| The app says **"Can't reach the backend"** | Start it with `python -m app.cli serve` in `backend\`, or check *Settings → Backend connection* (default `http://127.0.0.1:8765`). |
| **"Backend needs a restart (outdated version)"** | Stop the backend (Ctrl+C) and start it again. |
| `pip` cannot find `torch==…+cu130` | Use the `--extra-index-url` from step 2, or install `requirements.txt` instead. |
| `flutter run -d windows` fails | Install Visual Studio Build Tools with "Desktop development with C++" and run `flutter doctor`. |
| Windows shows **"Unknown publisher"** for the installer | The installer is not code-signed. Choose *More info → Run anyway*. |
| Port 8765 is in use | Start the backend on another port (`serve --port 8800`) and change the address in *Settings*. |
| A plan stopped half-way | Start the same command again; finished runs are skipped. |

---

## Citation and licence

Citation: to be added on publication. Licence: to be chosen before the repository is made public.
