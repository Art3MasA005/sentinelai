# Related work and how SentinelAI's methods relate to it

This file collects the papers that the evaluation protocol and the proposed method (NOVA) build on
or compare against. For each paper: what problem it solves, its architecture, how it was evaluated,
its main limitation for our setting, and what we take from it or compare against.

Our setting, for reference: a flow-feature NIDS deployed on a chronological stream; new attack
classes appear over time (open world); benign traffic drifts; analyst labels are scarce (a fixed
budget per window) and arrive late (a delay of one or more windows); a deployed model must not
silently get worse. Implemented strategy names are in `backend/app/ml/strategies.py`.

Verify page numbers and exact figures against the original PDFs before citing; numbers below are
as reported by the authors.

---

## A. Datasets and evaluation methodology

### 1. Sharafaldin, Lashkari, Ghorbani — CIC-IDS2017 (ICISSP 2018)
- **What:** 5 days (Mon 3 – Fri 7 July 2017) of testbed traffic, 2.83 M CICFlowMeter flows, 79
  features, 14 attack labels (brute force, DoS/DDoS, web attacks, infiltration, botnet, port scan).
- **Use here:** primary dataset, replayed in timestamp order (`TrafficLabelling` CSVs).

### 2. Engelen, Rimmer, Joosen — Troubleshooting an Intrusion Detection Dataset: the CICIDS2017 Case Study (IEEE S&P Workshops 2021)
- **What:** shows feature-extraction and labelling errors in CIC-IDS2017; about 20 % of flows are
  artefacts and about 10 % of labels are wrong; releases a corrected version (fixed CICFlowMeter,
  "attempted" attack labels).
- **Use here:** threat to validity; results on the corrected version should be reported too
  (INSOMNIA already uses it).

### 3. Lanvin et al. — Errors in the CICIDS2017 dataset and the significant differences in detection performances it makes (CRiSIS 2022)
- **What:** an independent team finds attacks that were run but not (correctly) labelled and shows
  that the corrections change reported detection results.
- **Use here:** same as above; also explains why Web Attack – Brute Force vs XSS is barely separable.

### 4. Liu, Engelen, Lynar, Essam, Joosen — Error Prevalence in NIDS datasets: CIC-IDS-2017 and CSE-CIC-IDS-2018 (IEEE CNS 2022)
- **What:** systematic error audit of both CIC datasets.
- **Use here:** motivates a second dataset and corrected-label runs.

### 5. Pendlebury, Pierazzi, Jordaney, Kinder, Cavallaro — TESSERACT (USENIX Security 2019)
- **What:** spatial bias (unrealistic class ratios) and temporal bias (training on the future)
  inflate malware-detection results; proposes time-consistent splits and the AUT (area under time)
  metric.
- **Use here:** chronological split, preprocessing fitted on the training period only, no
  look-ahead (`integrity` block of every run); AUT can be computed from `windows.csv`.

### 6. Arp et al. — Dos and Don'ts of Machine Learning in Computer Security (USENIX Security 2022)
- **What:** ten pitfalls found in 30 top-venue papers (sampling bias, label inaccuracy, data
  snooping, inappropriate baselines/metrics, lab-only evaluation, ...).
- **Use here:** checklist for the paper. We report multiple seeds (mean ± std), fixed label
  budgets, a FIXED-class open-world metric (see "Metric note"), and re-implement baselines under the
  same protocol instead of copying numbers across papers.

---

## B. Concept drift in security classifiers

### 7. Jordaney et al. — Transcend (USENIX Security 2017); Barbero et al. — Transcending Transcend (IEEE S&P 2022)
- **Architecture:** conformal evaluation on top of any classifier: non-conformity scores give
  per-prediction credibility/confidence p-values; low-credibility predictions are rejected as drifting.
- **Limitation for us:** rejection only; no adaptation or label policy. Calibration cost is high
  (the 2022 paper adds cheaper evaluators).
- **Relation:** our UNKNOWN decision is a rejection option of the same kind, calibrated per class on
  held-out flows.

### 8. Yang et al. — CADE: Detecting and Explaining Concept Drift Samples for Security Applications (USENIX Security 2021)
- **Architecture:** contrastive autoencoder maps samples to a low-dimensional space where the
  distance to each class centroid (scaled by the class's median absolute deviation) flags drifting
  samples; explanations are distance-based feature attributions. Evaluated on Android malware and on
  network intrusion data (CIC-IDS2018) with held-out families.
- **Limitation:** detection and explanation only; one centroid per class assumes unimodal classes.
  NetGuard (below) reports that CADE + retrain does poorly when used for adaptation on CIC data.
- **Relation:** our `centroid` detector is the CADE-style rule without the learned embedding; our
  `knn` detector removes the one-centroid assumption.

### 9. Chen, Ding, Wagner — Continuous Learning for Android Malware Detection (USENIX Security 2023)
- **Architecture:** encoder (512-384-256-128) trained with a hierarchical contrastive loss (benign
  vs malicious, then malware families) plus an MLP classifier; monthly active learning with a
  "pseudo-loss" uncertainty score computed from nearest training neighbours; warm-start updates.
- **Results:** F1 0.99 → 0.76 after six months without updates; with 200 labels/month FNR 14 % → 9 %,
  FPR 0.86 % → 0.48 % versus the best prior active learner.
- **Limitation for us:** binary, closed-world (no UNKNOWN), monthly batches, no deployment guard.
- **Relation:** confirms that similarity-based selection beats plain uncertainty under drift; our
  query score is a similarity (k-NN) novelty score.

### 10. Han et al. — OWAD: Anomaly Detection in the Open World: Normality Shift Detection, Explanation, and Adaptation (NDSS 2023)
- **Architecture:** for zero-positive anomaly detectors (e.g. KitNET): isotonic-regression
  calibration of outputs, a permutation test on output histograms to detect normality shift, an
  optimisation-based explainer that picks a few old and new samples reconstructing the new
  distribution (those are labelled), and adaptation with an importance-weighted regulariser
  (EWC-like) against forgetting.
- **Limitation for us:** anomaly detection only (no attack classes); distribution-level shift, not
  per-class novelty.
- **Relation:** the "label only what explains the shift" idea is the same goal as our
  novelty-weighted, cluster-diverse query.

---

## C. Drift-aware / adaptive NIDS

### 11. Andresini, Pendlebury, Pierazzi, Loglisci, Appice, Cavallaro — INSOMNIA: Towards Concept-Drift Robustness in Network Intrusion Detection (ACM AISec 2021)
- **Architecture:** a DNN classifier and a separate nearest-centroid (NC) label estimator. Each batch
  (count-based windows of 50 000 flows) the σ % least-confident flows are pseudo-labelled by the NC
  estimator, both models are fine-tuned, and DALEX explains feature-importance changes. No human
  labels after the initial training.
- **Evaluation:** CIC-IDS2017 (Engelen-corrected), first two days for training, remaining three as
  28 windows, binary F1 and AUT(F1).
- **Limitation:** binary; label estimation can only produce classes seen in training, so genuinely
  new attacks are never learned; self-poisoning when the estimator is wrong (the authors observe it
  at σ = 70 %).
- **Re-implemented as `insomnia`** (multi-class, NC estimator, σ = 0.5, zero analyst labels).
  INSOMNIA's "US + oracle" upper bound is our `uncertainty_al`.

### 12. Wang (HKUST) — ENIDrift: A Fast and Adaptive Ensemble System for Network Intrusion Detection under Real-World Drift (ACSAC 2022)
- **Architecture:** incremental packet-field embedding (iP2V, word2vec-like), sub-classifiers built
  per data chunk and kept/pruned by stability and accuracy; releases the RWDIDS dataset.
- **Limitation for us:** packet-level features (not flow CSVs); closed world.
- **Relation:** ensemble/versioning idea; our guard + rollback is the single-model analogue.

### 13. Zhang et al. — AOC-IDS: Autonomous Online Framework with Contrastive Learning for Intrusion Detection (IEEE INFOCOM 2024)
- **Architecture:** autoencoder trained with a contrastive "CRC" loss (normal samples as anchors,
  attacks as negatives); pseudo-labels from a two-component Gaussian fit of cosine similarity to the
  normal prototype; online fine-tuning on pseudo-labelled batches with random label flips.
- **Evaluation:** NSL-KDD, UNSW-NB15 (random, not chronological), binary.
- **Limitation:** binary, no analyst in the loop, pseudo-label error can accumulate.

### 14. Zhang et al. — SSF: Continual Learning with Strategic Selection and Forgetting for Network Intrusion Detection (IEEE INFOCOM 2025, arXiv 2412.16264)
- **Architecture:** AOC-IDS-style model; K-S test on model outputs to detect drift; learnable masks
  select old samples that represent the new distribution and new samples worth labelling (about 1 %);
  "strategic forgetting" drops unrepresentative old samples; LwF distillation when there is no drift.
- **Results:** NSL-KDD 91.9 F1, UNSW-NB15 91.4 F1 (5 rounds, no variance reported).
- **Limitation:** binary, random-split datasets, no open-world rejection.

### 15. Mousavipour, Dimanchev, Ghaderi — Shift Detection and Adaptation for Network Intrusion Detection (arXiv 2508.15100, 2025)
- **Architecture:** contrastive autoencoder; distribution-level pseudo-labelling (choose encoder or
  decoder by KL separation); permutation test on posterior histograms; mask-based shift explanation;
  relational knowledge distillation for adaptation.
- **Evaluation:** Kyoto2006+, CIC-IDS2017 → CICDDoS2019 (balanced with SMOTE/ADASYN); up to
  +11.7 F1 over OWAD and +7.4 over SSF.
- **Limitation:** binary; synthetic re-balancing of the test data.

### 16. Gupta et al. — NetGuard: Generative Active Adaptation for Drifting and Imbalanced Network Intrusion Detection (arXiv 2503.03022, 2025)
- **Architecture:** MLP (2 × 100) or XGBoost; density-aware prior selection: GMMs on labelled source
  and unlabelled target data, label the top-P of log p_target(x) − log p_source(x); then a tabular
  generator (RealTabFormer/TVAE) synthesises minority attack classes, filtered by a benign-vs-attack
  logistic regression.
- **Results:** CIC-IDS2017→2018 F1 60.6 (no adaptation) → 86.0 at a 1 % budget (full adaptation 93.2);
  uncertainty sampling 74.2, CLUE 79.7.
- **Limitation:** one-shot source → target adaptation, 100 k subsamples, generator needs GPU hours.
- **Re-implemented as `netguard_ps`** (prior selection, per window, same budget; no generator).

### 17. Amalapuram, Kumar, Tamma, Channappayya — SOUL: Semi-supervised Open-world Continual Learning for Network Intrusion Detection (arXiv 2412.00911, 2024)
- **Architecture:** MLP; replay buffer + gradient projection memory (SVD) + teacher–student
  distillation; for unseen tasks, high-confidence pseudo-labels are kept only if they agree with a
  cosine-similarity majority vote over buffer samples, disagreements go to the analyst.
- **Results:** CIC-IDS2017 attack AUT(PR-AUC) 0.989 with ≤ 20 % labels (binary, day-wise tasks).
- **Limitation:** binary; "open world" means unseen tasks, not per-flow rejection.
- **Relation:** the agreement check is the same principle as NOVA's conservative label propagation.

### 18. Amalapuram et al. — Augmented Memory Replay-based Continual Learning Approaches for Network Intrusion Detection (NeurIPS 2023)
- **Architecture:** extended class-balancing reservoir sampling (ECBRS) for the replay memory and a
  perturbation-assisted approximation that makes maximally-interfered-retrieval cheap; evaluated on
  CIC-IDS2017/2018, UNSW-NB15, CTU-13 task sequences.
- **Re-implemented (memory part) as `cbrs_replay`.**

### 19. Chrysakis, Moens — Online Continual Learning from Imbalanced Data (ICML 2020)
- **What:** CBRS: when the memory is full, a sample of a non-majority class evicts a random member
  of the current largest class; otherwise reservoir sampling within its own class.
- **Use here:** `ClassBalancedBuffer` (with an optional benign weight in NOVA).

---

## D. Open-set / out-of-distribution detection

### 20. Corsini, Yang — Are Existing Out-Of-Distribution Techniques Suitable for Network Intrusion Detection? (arXiv 2308.14376, 2023)
- **What:** compares softmax confidence, MC dropout, ODIN, Mahalanobis, k-NN (k = 25) and
  silhouette-based detectors on CIC-IDS2017/2018. k-NN on embeddings is the best single detector;
  ODIN and Mahalanobis transfer poorly from vision; combining different detector types on
  differently trained models catches 92–97 % of unknown attacks at the cost of more false alarms.
- **Use here:** motivates the `knn` detector and the msp + k-NN combination.

### 21. Sun, Ming, Zhu, Li — Out-of-Distribution Detection with Deep Nearest Neighbors (ICML 2022)
- **What:** distance to the k-th nearest training sample, threshold at a high quantile of
  in-distribution scores; no Gaussian class assumption (unlike Mahalanobis).
- **Use here:** our `knn` detector, made class-conditional (neighbours of the predicted class) with
  per-class thresholds.

### 22. Zhang et al. — Unknown Network Attack Detection Based on Open Set Recognition (Procedia CS 2020) and follow-ups
- **Architecture:** CNN + OpenMax-style EVT (Weibull fit of activation distances) to estimate an
  unknown-class probability; later work adds least-confidence active learning and clustering of the
  rejected flows to discover new attack types.
- **Limitation:** static evaluation (random splits), no drift, no label delay.

### 23. Mirsky et al. — Kitsune (NDSS 2018)
- **Architecture:** KitNET, an online ensemble of small autoencoders over incremental packet
  statistics; unsupervised anomaly score.
- **Relation:** the classic unsupervised online NIDS; INSOMNIA shows it fails on drifting attacks.

### 24. Prabhu, Chandrasekaran, Saenko, Hoffman — CLUE: Active Domain Adaptation via Clustering Uncertainty-weighted Embeddings (ICCV 2021)
- **What:** uncertainty-weighted k-means; label the instance nearest each centroid, so picks are
  both uncertain and diverse. NetGuard uses it as a strong baseline (79.7 F1 at 1 %).
- **Relation:** NOVA's query is in the same family but weights clusters by open-world novelty (k-NN
  score) rather than entropy, allocates quotas by sqrt(cluster size) so large drifting benign modes
  are still covered, keeps a uniform share, and runs per window under a label delay.

---

## Gap that NOVA addresses

| Requirement in our setting | Closest prior work | What is missing there |
|---|---|---|
| Multi-class detection of known attacks | most NIDS work | — |
| Reject never-seen attacks (per flow) | CADE, OSR/OpenMax, Corsini & Yang | no adaptation, static splits |
| Learn new attack classes over time | Chen'23, SOUL, NetGuard | binary or one-shot; no rejection |
| Scarce analyst labels, fixed budget | Chen'23, SSF, NetGuard, OWAD | no label delay, no open-world query |
| Label delay | (rarely modelled) | — |
| No silent degradation after an update | ENIDrift (ensemble pruning) | no explicit validation/rollback |
| Rare classes survive in memory | ECBRS, CBRS | uniform labels, closed world |

NOVA combines: class-conditional k-NN open-world rejection with per-class thresholds recalibrated on
held-out analyst labels; a novelty-weighted, cluster-stratified query under a fixed budget and delay;
agreement-checked label propagation; a benign-weighted class-balanced memory; and a deployment guard
(hold-out gain + reference-forgetting check) with rollback.

## Metric note

The open-set macro-F1 used inside each run (`macro_f1`) maps a flow to UNKNOWN when its class is
unknown to the model that scored it. Methods that learn different classes are then scored on
different label sets, so it is not comparable ACROSS methods. For comparisons use `macro_f1_ow`
(fixed class set; UNKNOWN is credited only while the class is unknown to the deployed model),
`detect_f1` / `detect_fpr` (binary, comparable with binary NIDS papers) and `unknown_auroc`.
