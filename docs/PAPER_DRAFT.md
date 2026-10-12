# NOVA: Novelty-aware, Open-world, Validated Adaptation for Network Intrusion Detection under Delayed, Scarce Labels

*Working draft. Numbers marked [R] are filled from `experiments/paper/tables.md` (regenerate with
`experiments/analysis/paper_results.py`). Related work and citations: `docs/LITERATURE.md`.*

## Abstract (draft)

Machine-learning network intrusion detectors are trained once and then face traffic that drifts and attack
classes that did not exist at training time, while analysts can label only a small, delayed fraction of the
flows. Prior work addresses these problems in isolation: drift adaptation for binary detectors, open-set
rejection on static splits, or active learning without label delay. We study them together on a
chronological replay of CIC-IDS2017 with a fixed label budget and a one-window label delay, and propose
NOVA, an adaptation loop that (i) rejects flows that are far from every known class with a class-conditional
k-nearest-neighbour detector, (ii) spends the label budget on novel and diverse traffic modes, (iii)
propagates analyst labels to agreeing neighbours, (iv) keeps rare attack classes in a class-balanced
memory, and (v) deploys a new model only after it passes a hold-out and forgetting check, with rollback.
Against eight baselines, including re-implementations of INSOMNIA, NetGuard's prior selection, uncertainty
sampling and class-balanced replay under the same budget, NOVA raises open-world macro-F1 from [R] to [R],
binary detection F1 from [R] to [R] at [R] false-positive rate, and unknown-attack AUROC from [R] to [R],
while forgetting [R] of the reference performance.

## 1. Introduction

- A detector trained on Monday–Tuesday traffic of CIC-IDS2017 and left unchanged labels almost every later
  attack (DoS, DDoS, port scan, web attacks, botnet) as benign: detection recall [R] (static row).
- Real deployments add three constraints that most evaluations drop: labels are scarce, labels arrive
  late, and a bad update reaches production unless something stops it (Arp et al. 2022; Pendlebury et al. 2019).
- Contributions:
  1. A replay protocol with a label oracle that enforces budget and delay for every method, plus metrics
     that stay comparable when methods learn different classes (open-world macro-F1 over a fixed class set).
  2. NOVA (Section 4).
  3. Faithful re-implementations of four published approaches under the same protocol, and a component
     ablation.
  4. Open-source research console (SentinelAI) for reproducing every number.

## 2. Related work

Summarise `docs/LITERATURE.md` sections B–D; the gap table there is the paragraph structure.

## 3. Problem setting

- Stream of flows x_t with labels y_t ∈ C_t, where the class set C_t grows over time; processed in windows
  W_1, W_2, … of fixed size (4,000 flows).
- After predicting W_w, the learner may request labels for at most B·|W_w| flows of W_w (budget B); they
  arrive after d windows (delay d = 1).
- The deployed model outputs a known class or UNKNOWN (send to an analyst). UNKNOWN is not an alarm and
  is not counted as a false positive in `fpr`; it is counted in `detect_fpr`.
- Goal: high open-world macro-F1 and detection F1 at low false-positive rate, with no silent degradation.

## 4. Method: NOVA

Notation: f current model, M memory, Q calibration store, k budget of a window.

```
for each window W_w:
    predict W_w with f                                  # decision ∈ classes ∪ {UNKNOWN}
    s(x) = max( (1-p_max)/(1-τ_msp[c]),  d_k(x, Bank_c)/τ_knn[c] )  for c = argmax p   # unknown score
    request labels for  Query(W_w, s, k)                # arrives at window w+d
    L = labels that arrived at this window
    if f was just deployed and L shows f_prev better by > margin on classes with ≥ m labels: roll back
    H = stratified hold-out of L;  T = L \ H
    P = Propagate(W_src(T), T)                          # agreeing, close unlabelled neighbours
    f' = Train(M ∪ T ∪ P, weights 1 for M, ρ for T ∪ P); calibrate τ on (reference ∪ Q)
    if gain_H(f', f) ≥ 0 and forgetting_ref(f', f) ≤ ε: deploy f'
    M ← CBRS(M, T ∪ P);  H → Q for classes already well represented in M, else → M
```

- **Unknown score.** Class-conditional deep k-NN (Sun et al. 2022): distance to the k-th nearest
  training flow of the *predicted* class, threshold at the 99th percentile of held-out distances of that
  class; combined with per-class maximum-softmax thresholds. Both scaled so the threshold is 1.
- **Query.** Uniform share ρ_u of k (unbiased view of benign drift). The rest is cluster-stratified:
  k-means on the window, quota_c ∝ √|c| · (0.1 + mean s over c), at least one per cluster, most novel
  first. Compared with uncertainty sampling it does not spend the budget on one ambiguous region; compared
  with CLUE it uses an open-world novelty signal and size-damped quotas.
- **Propagation.** Unlabelled flow u gets class c when its min(k_p, n_c) nearest labelled flows are all c
  and its nearest distance is within c's radius (90th percentile of nearest-same-class distances among
  the labels); at most r pseudo labels per analyst label. (Agreement idea as in SOUL; nearest-centroid
  label estimation as in INSOMNIA, but anchored on analyst labels.)
- **Memory.** Class-balancing reservoir (Chrysakis & Moens 2020) with benign weight β (benign traffic is
  multi-modal; starving it raises false alarms).
- **Calibration store.** Hold-out labels of classes already represented in memory are kept out of
  training (≤ q per class) and used to calibrate thresholds of later models, so classes learned during
  deployment get their own thresholds instead of the strict fallback.
- **Guard and rollback.** Open-world macro-F1 compares models that know different classes on the same
  task; classes with fewer than m labels are left out of the comparison (one flow of a rare class would
  move macro-F1 by 1/|C|).

Default hyper-parameters (fixed for all experiments, not tuned per dataset): ρ_u = 0.2, 24 clusters,
k_p = 5, r = 5, β = 4, hold-out 25 %, q = 200, calibration after 50 flows in memory, m = 5, ε = 0.05,
rollback margin 0.05, recency weight ρ = 2, memory 20,000 flows (same for every replay baseline),
k-NN k = 10 with 3,000 flows per class bank.

## 5. Experimental setup

- **Data.** CIC-IDS2017 TrafficLabelling CSVs (2,830,743 flows, 15 labels), sorted by timestamp, thinned
  to 400,000 evenly spaced flows (deterministic). First 30 % = training period (last 20 % of it =
  reference validation set); the rest is the stream: 70 windows of 4,000 flows. Training contains only
  BENIGN and FTP-Patator (Monday–Tuesday morning), so 12 attack classes are new.
- **Model.** Histogram gradient boosting (scikit-learn, 150 iterations, L2 = 1.0) for every method.
- **Labels.** Budget 10 % and 1 % of each window, delay 1 window.
- **Baselines.** static; periodic_retrain (every 5 windows on the last 10 labelled windows);
  continual_replay (uniform reservoir); guarded_selective (drift-triggered, guard + rollback);
  uncertainty_al; insomnia (label-free); netguard_ps; cbrs_replay. All use the same open-world detector
  (msp + k-NN) unless stated (detector ablation).
- **Metrics.** Open-world macro-F1 over all 13 stream classes, AUT of the per-window curve, attack
  macro-recall, detection F1/recall/FPR (attack class or UNKNOWN = flagged), unknown AUROC, maximum
  forgetting on the reference set, labels used, training time. Three seeds; mean ± std. Wilcoxon
  signed-rank on per-window open-world macro-F1 (NOVA vs each method; windows are autocorrelated, so
  p-values are indicative).

## 6. Results

Tables: `experiments/paper/tables.md` (also `.csv`, `.tex`). Figures: `fig_ow_f1_over_time`,
`fig_budget`, `fig_ablation` (`.png`, `.pdf`).

- 6.1 Main comparison at 10 % budget. [R]
- 6.2 Low budget (1 %). [R]
- 6.3 Ablation: contribution of each component. [R]
- 6.4 Detector: msp + centroid vs msp + k-NN for static and NOVA. [R]
- 6.5 Per-class behaviour: which attacks are learned, and how fast (`novel_class_delay_windows`). [R]

## 7. Threats to validity

- **One dataset.** CIC-IDS2017 only so far; add CSE-CIC-IDS2018 or UNSW-NB15 (profiles exist) and the
  Engelen et al. corrected CIC-IDS2017.
- **Label noise in CIC-IDS2017** (Engelen et al. 2021; Lanvin et al. 2022): some port-scan flows are
  feature-identical to benign flows, and Web Attack – Brute Force vs XSS are barely separable; this caps
  the reachable per-class F1 for every method.
- **Five days of traffic** is short for drift; the stream mixes attack onset (class novelty) with modest
  benign drift.
- **Baselines are re-implementations** under our protocol (multi-class, same model and budget), not the
  authors' code; what each keeps and drops is listed in LITERATURE.md. NetGuard's generative
  augmentation is not reproduced.
- **Sampling.** 400k of 2.83M flows; windows of 4,000 flows. Sensitivity to window size and budget should
  be reported.
- **Hyper-parameters** were chosen from design arguments and two development runs (seeds 1–2), then frozen;
  they were not searched on the reported runs.
- **Simulated analyst:** the oracle returns ground truth with no labelling errors.

## 8. Reproducibility

`python -m app.cli import-dataset GeneratedLabelledFlows.zip --name CIC-IDS2017 --profile cicids2017`;
experiment plans as in `experiments/configs/`; every run stores config, hashes, predictions and events
under `experiments/results/<run_id>/`.
