# Research protocol

This document describes how SentinelAI runs an experiment and what its numbers mean. Cite it when you report results. All metric definitions are also returned by `GET /experiments/{id}/metrics` → `definitions`.

## 1. Data and provenance

- A dataset is a CSV file, or a folder of CSV files, under `data/datasets/`.
- A schema **profile** says which columns hold the timestamp and the label, and which columns are identifiers. Built-in profiles are `sentinel_demo`, `cicids2017`, `cicids2018` and `unswnb15`. You can define custom profiles through the API.
- Dropped columns are never used as features. These include IPs, ports in UNSW-NB15, flow IDs, timestamps and labels.
- **Validation is mandatory before a run.** It checks for:
  - missing columns;
  - non-numeric feature columns;
  - unparseable timestamps;
  - out-of-order rows;
  - a label count below two.
- Validation records a SHA-256 hash of the dataset files. Runs store that hash, and if the files change after validation, the run is refused.
- **DEMO data** comes from `app.ml.demo_data` and is synthetic. Runs on it carry `data_origin = "demo"` everywhere: API responses, CSV rows, file names, and a README inside exported ZIPs.

### Known dataset caveats

- **CIC-IDS2017**
  - Use the *TrafficLabelling* CSVs. The *MachineLearningCVE* CSVs have no Timestamp column.
  - Afternoon timestamps in some files have no AM/PM marker. Validation reports this as `out_of_order_fraction`. If you trust the order of rows in the files, set the profile's `order_by` to `"file_order"` and document that choice.
  - Monday contains only benign traffic. A time-based training split that covers only Monday cannot train a classifier, and the run fails with a clear error.
- **UNSW-NB15**
  - Use the raw, headerless `UNSW-NB15_1..4.csv` files.
  - The train/test partition CSVs have no timestamp, so they cannot be replayed in time order.

## 2. Chronological split (no look-ahead)

1. Rows are stably sorted by timestamp. When two rows have the same timestamp, they keep their order from the file.
2. `max_rows` optionally thins the data, keeping evenly spaced rows across the whole timeline so their order is unchanged.
3. The first `train_fraction` of the timeline is the **training period**:
   - The last `val_fraction` of that period is the **reference validation set**.
   - The rest of it is the **fit set**.
4. Everything after the training period is the **stream**. It is cut into windows of `window_size` flows each.
5. Classes listed in `holdout_classes` are removed from the fit and validation sets. They then show up only in the stream, which simulates attacks the model has never seen.
6. The reference validation set keeps only classes that occur in the fit set. A class that first appears in the reference period (in CIC-IDS2017 with `train_fraction` 0.3, SSH-Patator on Tuesday afternoon) was never learned, so counting it would turn "forgetting" into a measure of unknown detection. The dropped rows are listed per class in the run's `integrity.reference_rows_dropped_unseen_classes`. Runs before this rule are archived under names starting with `archive-ref1`.

## 3. Preprocessing

The preprocessor is fitted **only on the fit set**:
- missing and infinite values are filled with the median;
- values go through a signed log1p transform and are then standardised;
- categorical columns are one-hot encoded using the top 32 categories, plus an `<other>` column.

The fitted preprocessor is frozen for the whole run. The run summary records `integrity.preprocessor_fitted_rows` and `integrity.chronological_split`. These are tested in `tests/test_pipeline.py`.

## 4. Per-window loop

For each window *t*:
1. The deployed model predicts the window. Open-world scoring then marks some flows **UNKNOWN**. This decision means the flow is unfamiliar or uncertain and needs review; it does not mean the flow is malicious.
2. Evaluation compares the predictions with the ground truth for window *t*. Evaluation is the only step that reads true labels directly.
3. Unsupervised drift detectors look only at features and model confidence:
   - **KS:** the share of features that drifted, using a Bonferroni-corrected KS test.
   - **PSI:** the mean PSI over features.
   - **Confidence:** the drop in mean confidence relative to the reference.
4. The adaptation strategy may change the model. Any new model is used **from window *t*+1 onwards**.

Ground truth is available to adaptation only through the **label oracle**:
- labels for window *w* arrive at window *w* + `delay_windows`;
- only a `budget` fraction of each window is labelled;
- every label handed out is counted in `labels_used`.
- by default the labelled flows of a window are a uniform random sample. A query strategy may instead `request` WHICH flows of the window it has just predicted get labelled, choosing from features and model outputs only. The count is still capped by the budget and the labels still arrive after the delay, so every method pays the same labelling cost.

## 5. Open-world scoring

A flow is marked UNKNOWN if either test applies:
- **`msp`:** its top-class probability is below a threshold for the predicted class. Each class's threshold is the `msp_quantile` quantile of that class's confidence on the reference validation set. A class with fewer than 20 validation predictions gets the most lenient threshold of all classes.
- **`centroid`:** its normalised distance to the nearest class centroid exceeds the `distance_quantile` quantile of those distances on the validation set.
- **`knn`:** the distance to its `knn_k`-th nearest training flow *of the predicted class* (a bank of at most `knn_bank_per_class` flows per class) exceeds that class's threshold: the `distance_quantile` quantile of the same score on held-out flows of the class that the model also predicts as the class. A class with fewer than 30 such flows is calibrated leave-one-out on its bank. This is the deep k-NN detector of Sun et al. (ICML 2022) made class-conditional; Corsini & Yang (2023) found k-NN the strongest single OOD detector for NIDS.

`msp+centroid` and `msp+knn` combine two tests. Each test is scaled so that its threshold is 1; `unknown_score` is the maximum over the enabled tests, so `unknown_score > 1` is exactly the UNKNOWN decision, and `unknown_auroc` ranks flows by it.

Thresholds are recalibrated for each new model version, on the reference validation set plus any extra held-out labels the strategy passes (NOVA's calibration store).

## 6. Adaptation methods

| Method | Uses labels | Behaviour |
|---|---|---|
| `static` | never | Trained once on the fit set. |
| `periodic_retrain` | every revealed window | Every `retrain_every` windows, retrains from scratch on the fit set plus the last `memory_windows` labelled windows. Always deploys the new model. |
| `continual_replay` | every revealed window | Keeps a reservoir replay buffer, seeded with the fit set, and retrains on it whenever new labels arrive. Always deploys. |
| `guarded_selective` | only when triggered or during a post-deployment watch | Guard + rollback reference design. See below. |
| `uncertainty_al` | every revealed window, chosen flows | Least-confidence query of the budget, replay buffer, always deploys (standard AL baseline; INSOMNIA's "US + oracle"). |
| `insomnia` | never (label-free) | INSOMNIA (AISec 2021): least-confident `insomnia_selection_rate` of each window labelled by a nearest-centroid estimator, retrain on original labels + estimates. |
| `netguard_ps` | every revealed window, chosen flows | NetGuard's density-aware prior selection: label the top budget of log p_window(x) − log p_labelled(x) (two diagonal GMMs); no generative augmentation. |
| `cbrs_replay` | every revealed window | Continual replay with a class-balancing reservoir memory (CBRS / ECBRS). |
| `nova` | every revealed window, chosen flows | **Proposed method.** See below. |

How `guarded_selective` works:
1. A drift event, or an unknown rate of at least `novelty_trigger_rate`, triggers it.
2. It takes up to `memory_windows` of the labelled windows that are available.
3. It trains a candidate model on the replay buffer plus the older labelled windows. The newest labelled window is held out for validation.
4. It accepts the candidate if both conditions hold:
   - (hold-out macro-F1 gain) ≥ `min_gain`;
   - (drop in macro-F1 on the reference set) ≤ `max_forgetting`.
5. After deployment, it watches `rollback_watch_windows` windows. It rolls back if the previous model beats the new one by more than `rollback_margin`.

Ablation switches: `validation_guard`, `rollback`, and `trigger` (`drift` or `drift_or_novelty`).

How `nova` (Novelty-aware, Open-world, Validated Adaptation) works, every window *w*:
1. **Query (at prediction time).** Of the budget *k*, a `random_fraction` share is drawn uniformly. The rest is spread over `select_clusters` k-means clusters of the window: each cluster gets at least one label and a quota proportional to √size × (0.1 + mean novelty), where novelty is the clipped `unknown_score`; inside a cluster the most novel flows go first.
2. **Labels arrive** (after the delay). A stratified `holdout_fraction` of them is held out for the guard.
3. **Propagation.** Each remaining analyst label spreads to unlabelled flows of the same window whose `propagate_k` nearest labelled flows all share that class and whose nearest distance is within the class radius (90th percentile of nearest-same-class distances among the class's labels); at most `propagate_max_ratio` pseudo labels per analyst label.
4. **Candidate.** Trained on the memory plus the new analyst and propagated labels; the newest labels get weight `recent_weight`. Open-world thresholds are calibrated on the reference set plus the calibration store.
5. **Guard.** Deploy only if (hold-out open-world macro-F1 gain) ≥ `min_gain` and (reference forgetting) ≤ `max_forgetting`; both compare only classes with at least `min_support` labels. A deployed model is rolled back if the next labels show the previous model is better by more than `rollback_margin`.
6. **Memory.** A class-balancing reservoir (benign weighted by `benign_weight`) receives the analyst and propagated labels. Hold-out labels of classes that already have `calib_min_train` flows in memory go to the calibration store (at most `calib_per_class` per class, never trained on).

Ablation switches: `active_selection`, `propagate`, `class_balanced_memory`, `validation_guard` (+ `rollback`), `calib_per_class = 0`, `recent_weight = 1`. What each re-implemented baseline keeps from its paper is listed in [LITERATURE.md](LITERATURE.md).

Classes with fewer than `model.min_class_samples` labelled samples are left out of training. They stay UNKNOWN until enough labels arrive. Without this rule, gradient-boosted models were found to diverge on one-sample classes.

## 7. Metrics

| Metric | Definition |
|---|---|
| macro_f1 | Mean F1 over the classes present in the ground truth. It is open-set: true classes the deployed model has not seen count as one UNKNOWN class. |
| per_class_recall | TP / (TP + FN) for each open-set true class. |
| fpr | Benign flows reported as an attack class, divided by all benign flows. UNKNOWN decisions are excluded. |
| benign_review_rate | Benign flows reported as UNKNOWN, divided by all benign flows. |
| pr_auc | Average precision of `1 - P(benign)` for attack vs. benign. It is null when a window lacks one of the two. |
| unknown_recall | Flows of classes the model has not seen that were reported UNKNOWN. This is the unknown-rejection rate. |
| known_false_unknown_rate | Flows of known classes that were reported UNKNOWN. |
| ref_macro_f1 | Macro-F1 of the deployed model on the fixed reference validation set. It is measured after each window. |
| forgetting_max / forgetting_final | The largest drop, and the final drop, of ref_macro_f1 below its best value so far. |
| adaptation_delay_windows | Windows from a drift event to the first accepted adaptation (or rollback). |
| novel_class_delay_windows | Windows from a class's first appearance in the stream until a deployed model knows that class. |
| latency_ms_per_flow | Inference time per flow (wall clock). |
| train_seconds_total, n_trainings, model_bytes_final | Resource cost. |
| labels_used, label_fraction | Labelling cost. |
| macro_f1_ow, per_class_f1_ow | **Use these to compare methods.** Open-world macro-F1 over a FIXED class set (every true class in the data): a flow is correct if the decision is its true class, or if its class is unknown to the deployed model and the decision is UNKNOWN. |
| attack_macro_recall_ow | Mean open-world-credited recall over attack classes. |
| detect_f1, detect_recall, detect_precision, detect_fpr | Binary view comparable with binary NIDS papers: a flow is flagged when the decision is not benign (attack class or UNKNOWN; both reach an analyst). |
| unknown_auroc | AUROC of `unknown_score` for separating flows of classes unseen by the deployed model from known-class flows. |

Every implementation is checked against hand-computed values and against scikit-learn in `tests/test_metrics.py`.

**Why `macro_f1` must not be compared across methods:** it maps a flow to UNKNOWN when its class is unknown to the model that scored it, so a method that learns more classes is scored on a harder, different label set. Guard and rollback decisions use the open-world credit as well, so models that know different classes are compared on the same task.

**Reading open-set macro-F1:** a static model that marks every novel flow UNKNOWN gets credit for the UNKNOWN class. An adaptive model that learns the new class is scored on that class instead. Always report `unknown_recall`, `novel_class_delay_windows` and per-class recall together with macro-F1.

## 8. Fair comparison and reproducibility

- Runs are deterministic for a fixed config and seed. The tests replay twice and compare hashes of every decision.
- `GET /experiments/compare` sets `fair` to false when any of the following differ between runs:
  - dataset or dataset hash;
  - profile;
  - seed;
  - model;
  - split;
  - open-world, drift or label settings.
- Each run writes these files to `experiments/results/<run_id>/`:
  - `config.json`;
  - `run.json` (provenance, summary, windows and events);
  - CSV files of predictions, windows, drift events, adaptation events and model versions;
  - `run.log`.
- Batch runs for a paper: `python -m app.cli run experiments/configs/*.json`.
- **Multi-seed:** `POST /experiments/batch`, or the **Seeds** field on the Experiments page, runs every method on the same seed set. Reports then shows the mean ± sample std per method. Report those values, not single runs.
- **Figures:** `export?format=figures` and `compare/figures` produce PNG + PDF plots ready for a paper. Each figure is footed with its run ID, dataset hash and config hash. Plots from DEMO data carry a watermark.
