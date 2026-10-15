#!/usr/bin/env python3
"""Build the BigCodeBench 70/10/20 partition: red_train / red_self_eval / green_heldout.

WHY A SECOND PARTITION. The original 40/40/20 (`green_team/bcb_gate_task.py`) was cut for the
exploration-hacking shape: a lock_sft half and an equally large elicit_rl half. Rounds that just
need "train, self-check, and a gate red cannot see" want most of the data in training and only a
small honest self-eval slice. This is that partition. Both are additive: the 40/40/20 names still
resolve, so existing gates keep working.

THE SPLIT IS DERIVED, NOT STORED. Same pinned revision and same seed-0 shuffle as the 40/40/20, so
anyone can regenerate it with no HF access and no private file:

    idx = list(range(N)); random.Random(0).shuffle(idx)
    red_train      = idx[0.00N : 0.70N]      798
    red_self_eval  = idx[0.70N : 0.80N]      114
    green_heldout  = idx[0.80N : 1.00N]      228

Because the seed is unchanged, **green_heldout is byte-identical to the 40/40/20's test_heldout**.
That is deliberate: green's held-out set does not move, so code-gate numbers stay comparable across
both partitions, and only red's 912 items are re-cut (456/456 -> 798/114).

THE INFORMATION WALL. green_heldout is written to a LOCAL green-private path and is NEVER pushed.
Only red_train + red_self_eval go to the Hub. Pushing all three would hand red the gate.

    # build + write green's slice locally, no push
    python scripts/build_bcb_split_70_10_20.py --green-out ~/green_private/bcb_green_heldout.jsonl

    # additionally publish the two red splits (needs a WRITE-scoped HF_TOKEN)
    python scripts/build_bcb_split_70_10_20.py --green-out <path> --push \
        --repo darklord1611/bigcodebench-split-70-10-20
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

# Pinned identically to green_team/bcb_gate_task.py. If these drift, the two partitions stop
# describing the same underlying rows and "disjoint" becomes a lie -- so they are asserted equal
# at build time rather than trusted.
BIGCODEBENCH_REPO = "bigcode/bigcodebench"
BIGCODEBENCH_VERSION = "v0.1.2"
BIGCODEBENCH_REVISION = "b74c0d0bf70d2c0bc459be537895cca163007f1a"
SPLIT_SEED = 0

FRACS = {
    "red_train": (0.00, 0.70),
    "red_self_eval": (0.70, 0.80),
    "green_heldout": (0.80, 1.00),
}
GREEN_SPLIT = "green_heldout"          # never leaves the operator machine
RED_SPLITS = ["red_train", "red_self_eval"]


def split_indices(n_rows: int) -> dict[str, list[int]]:
    """Deterministic dataset-position indices per split name."""
    idx = list(range(n_rows))
    random.Random(SPLIT_SEED).shuffle(idx)
    return {
        name: idx[int(lo * n_rows): int(hi * n_rows)]
        for name, (lo, hi) in FRACS.items()
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--green-out", required=True,
                   help="local path for the green_heldout jsonl (green-private; never pushed)")
    p.add_argument("--push", action="store_true",
                   help="also publish red_train + red_self_eval to --repo (needs write-scoped HF_TOKEN)")
    p.add_argument("--repo", default="darklord1611/bigcodebench-split-70-10-20")
    p.add_argument("--private", action="store_true", default=True)
    args = p.parse_args()

    from datasets import Dataset, DatasetDict, load_dataset

    ds = load_dataset(BIGCODEBENCH_REPO, split=BIGCODEBENCH_VERSION,
                      revision=BIGCODEBENCH_REVISION)
    n = len(ds)
    parts = split_indices(n)
    print(f"[bcb] {BIGCODEBENCH_REPO} {BIGCODEBENCH_VERSION} @ {BIGCODEBENCH_REVISION[:8]}: {n} rows")

    # --- invariants. A silent split bug is the one failure that cannot be detected downstream:
    # the gate would still run, still report a number, and that number would be contaminated.
    seen: set[int] = set()
    for name, ids in parts.items():
        assert len(ids) == len(set(ids)), f"{name} has duplicate indices"
        assert not (seen & set(ids)), f"{name} overlaps an earlier split"
        seen |= set(ids)
        print(f"[split] {name:14s} {len(ids):4d}")
    assert seen == set(range(n)), "splits do not partition the dataset"

    # green_heldout must equal the 40/40/20 partition's test_heldout, or the two partitions
    # disagree about what red has already seen.
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from green_team.bcb_gate_task import split_indices as legacy_split
        assert parts[GREEN_SPLIT] == legacy_split("test_heldout"), \
            "green_heldout != 40/40/20 test_heldout -- the seed or revision drifted"
        print("[check] green_heldout == 40/40/20 test_heldout  ✓")
    except ImportError:
        print("[check] green_team not importable; skipped the legacy-equality check")

    # --- green's slice: local only.
    green_rows = [dict(ds[i], orig_index=i) for i in parts[GREEN_SPLIT]]
    out = os.path.expanduser(args.green_out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        for r in green_rows:
            f.write(json.dumps(r) + "\n")
    print(f"[green] wrote {len(green_rows)} rows -> {out}  (GREEN-PRIVATE, not pushed)")

    if not args.push:
        print("[hub] --push not given; red splits not published")
        return 0

    dd = DatasetDict({
        name: Dataset.from_list([dict(ds[i], orig_index=i) for i in parts[name]])
        for name in RED_SPLITS
    })
    assert GREEN_SPLIT not in dd, "green_heldout must never be pushed"
    sizes = {k: len(v) for k, v in dd.items()}
    print(f"[hub] pushing {sizes} -> {args.repo} (private={args.private})")
    dd.push_to_hub(args.repo, private=args.private)
    print("[hub] done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
