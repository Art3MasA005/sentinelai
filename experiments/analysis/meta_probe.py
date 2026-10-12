"""Offline go/no-go probe for a meta-learned embedding (CIC-IDS2017 only, the development dataset).

At several cut windows W we build the labelled pool a 10%-budget method would have (training period +
10% of stream windows < W-1), then ask: do flows of classes NOT in the pool (future novel attacks) stand out
from benign flows of the same period?  Compared:
  raw   - k-th NN distance to the benign bank in the standardised feature space (what NOVA uses now)
  proto - same, in an embedding trained with class-balanced prototypical episodes
  meta  - prototypical episodes + one known class held out per episode as pseudo-unknown, pushed away from
          every prototype by a margin (open-set meta-learning in the style of PEELER, Liu et al. CVPR 2020)
Reported: AUROC and TPR at the benign threshold that a 1% / 3% false-positive rate gives on held-out pool
benign flows (thresholds never see the future).
"""
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.config import get_settings  # noqa: E402
from app.ml.data import load_dataset  # noqa: E402
from app.ml.openworld import _kth_distance, _sq_norms  # noqa: E402
from app.ml.preprocessing import Preprocessor  # noqa: E402
from app.services import datasets as ds_service  # noqa: E402

SEED = 1
WIN = 4000
rng = np.random.default_rng(SEED)
settings = get_settings()
ds = ds_service.resolve(settings.datasets_dir, "CIC-IDS2017")
profile = ds_service.pick_profile(ds, "cicids2017", None)
data = load_dataset(ds.files, profile, 400_000)
labels = data.labels.astype(str)
n = len(labels)
n_train = int(n * 0.3)
fit_end = n_train - max(int(n_train * 0.2), 1)
pre = Preprocessor(data.numeric_columns, data.categorical_columns).fit(data.frame.iloc[:fit_end])
x_all = pre.transform(data.frame).astype(np.float32)
benign = [b for b in profile.benign_labels if b in set(labels)][0]
dev = "cuda" if torch.cuda.is_available() else "cpu"
print("loaded", x_all.shape, "benign label", benign, "device", dev, flush=True)


def pool_at(W: int):
    idx = [np.arange(0, n_train)]
    for w in range(0, W - 1):  # labels of window w arrive at w+1; a model deployed at W has windows < W-1... and W-1 arrives at W
        s = n_train + w * WIN
        idx.append(s + rng.choice(WIN, WIN // 10, replace=False))
    idx = np.concatenate(idx)
    return x_all[idx], labels[idx]


def cap(x, y, per_class, rs):
    keep = []
    for c in np.unique(y):
        i = np.flatnonzero(y == c)
        keep.append(i if len(i) <= per_class else rs.choice(i, per_class, replace=False))
    keep = np.concatenate(keep)
    return x[keep], y[keep]


class Enc(torch.nn.Module):
    def __init__(self, d, h=256, out=64):
        super().__init__()
        self.net = torch.nn.Sequential(torch.nn.Linear(d, h), torch.nn.ReLU(), torch.nn.Linear(h, h),
                                       torch.nn.ReLU(), torch.nn.Linear(h, out))

    def forward(self, x):
        return F.normalize(self.net(x), dim=1)


def train_embedding(x, y, open_set: bool, episodes=1500, shots=16, queries=32, temp=0.1, margin=0.5):
    torch.manual_seed(SEED)
    cls = np.unique(y)
    by = {c: torch.tensor(x[y == c], device=dev) for c in cls}
    enc = Enc(x.shape[1]).to(dev)
    opt = torch.optim.Adam(enc.parameters(), lr=1e-3, weight_decay=1e-4)
    g = np.random.default_rng(SEED)
    for _ in range(episodes):
        held = g.choice(cls) if (open_set and len(cls) >= 3) else None
        known = [c for c in cls if c != held]
        sup, qry, qy = [], [], []
        for j, c in enumerate(known):
            xc = by[c]
            i = torch.tensor(g.choice(len(xc), shots + queries, replace=len(xc) < shots + queries), device=dev)
            sup.append(enc(xc[i[:shots]]).mean(0))
            qry.append(xc[i[shots:]])
            qy.append(torch.full((queries,), j, device=dev))
        protos = F.normalize(torch.stack(sup), dim=1)
        q = enc(torch.cat(qry))
        logits = q @ protos.T / temp
        loss = F.cross_entropy(logits, torch.cat(qy))
        if held is not None:
            xh = by[held]
            i = torch.tensor(g.choice(len(xh), queries, replace=len(xh) < queries), device=dev)
            sim = enc(xh[i]) @ protos.T  # cosine similarity to every known prototype
            # pseudo-unknowns must stay below the similarity known queries have to their own prototype
            own = (q * protos[torch.cat(qy)]).sum(1).mean().detach()
            loss = loss + F.relu(sim.max(1).values - own + margin).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
    enc.eval()
    return enc


def embed(enc, x):
    out = []
    with torch.no_grad():
        for s in range(0, len(x), 16384):
            out.append(enc(torch.tensor(x[s:s + 16384], device=dev)).cpu().numpy())
    return np.concatenate(out)


def evaluate(name, zb_bank, zb_cal, z_test, y_test):
    bank_sq = _sq_norms(zb_bank)
    d_cal = _kth_distance(zb_cal, zb_bank, bank_sq, 10)
    t1, t3 = np.quantile(d_cal, 0.99), np.quantile(d_cal, 0.97)
    d = _kth_distance(z_test, zb_bank, bank_sq, 10)
    isb = y_test == benign
    row = {"fpr@t1": float((d[isb] > t1).mean()), "fpr@t3": float((d[isb] > t3).mean())}
    for c in np.unique(y_test[~isb]):
        m = y_test == c
        yy = np.r_[np.ones(m.sum()), np.zeros(isb.sum())]
        row[c] = (roc_auc_score(yy, np.r_[d[m], d[isb]]), float((d[m] > t1).mean()), float((d[m] > t3).mean()))
    return name, row


for W in (5, 25, 45):
    t0 = time.time()
    xp, yp = pool_at(W)
    pool_classes = set(np.unique(yp))
    rs = np.random.default_rng(SEED)
    xp, yp = cap(xp, yp, 20000, rs)
    # held-out benign from the pool for thresholds; bank = remaining pool benign
    bi = np.flatnonzero(yp == benign)
    rs.shuffle(bi)
    cal_i, bank_i = bi[:2000], bi[2000:5000]
    tr = np.setdiff1d(np.arange(len(yp)), cal_i)
    s = n_train + W * WIN
    xt, yt = x_all[s:], labels[s:]
    keep = np.isin(yt, [benign]) | ~np.isin(yt, list(pool_classes))
    xt, yt = xt[keep], yt[keep]
    bt = np.flatnonzero(yt == benign)
    if len(bt) > 20000:
        drop = np.setdiff1d(bt, rs.choice(bt, 20000, replace=False))
        xt, yt = np.delete(xt, drop, 0), np.delete(yt, drop)
    print(f"\n=== cut W={W}: pool classes {sorted(pool_classes)}; novel in future: "
          f"{sorted(set(yt) - {benign})}", flush=True)
    results = [evaluate("raw", xp[bank_i], xp[cal_i], xt, yt)]
    for name, open_set in (("proto", False), ("meta", True)):
        enc = train_embedding(xp[tr], yp[tr], open_set)
        results.append(evaluate(name, embed(enc, xp[bank_i]), embed(enc, xp[cal_i]), embed(enc, xt), yt))
    for name, row in results:
        print(f"  {name:6s} benign FPR {row['fpr@t1']:.3f}/{row['fpr@t3']:.3f}")
        for c, v in row.items():
            if c.startswith("fpr"):
                continue
            print(f"     {c:28s} AUROC {v[0]:.3f}  TPR@1% {v[1]:.2f}  TPR@3% {v[2]:.2f}")
    print(f"  ({time.time() - t0:.0f}s)", flush=True)
