"""Make a deterministic, order-preserving 1-in-k copy of an imported dataset (for multi-GB datasets).

usage (from backend/): .venv/Scripts/python.exe ../experiments/analysis/thin_dataset.py SRC_NAME DST_NAME K

Every file keeps its header and every k-th data line (lines 0, k, 2k, ... of the file's data rows); embedded
header lines are dropped. This is the same thinning the loader applies with `split.max_rows`, done once so
each run does not re-read the full dataset. The manifest records the source and k for provenance.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data" / "datasets"


def main(src_name: str, dst_name: str, k: int) -> None:
    src, dst = ROOT / src_name, ROOT / dst_name
    manifest = json.loads((src / "sentinel_dataset.json").read_text(encoding="utf-8"))
    tmp = ROOT / f".{dst_name}.importing"
    tmp.mkdir(parents=True, exist_ok=False)
    kept_total = 0
    for name in manifest["files"]:
        kept = i = 0
        with open(src / name, encoding="utf-8", errors="replace", newline="") as fin, \
                open(tmp / name, "w", encoding="utf-8", newline="") as fout:
            header = fin.readline()
            fout.write(header)
            for line in fin:
                if line == header:
                    continue
                if i % k == 0:
                    fout.write(line)
                    kept += 1
                i += 1
        kept_total += kept
        print(f"{name}: kept {kept:,} of {i:,}", flush=True)
    manifest.update(name=dst_name, source=f"{src_name} (1-in-{k} thinning, order preserved)", thinning_k=k,
                    derived_from=src_name, imported_at=datetime.now(timezone.utc).isoformat())
    (tmp / "sentinel_dataset.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.rename(dst)
    print(f"{dst}: {kept_total:,} rows")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]))
