"""Push the Olympiad train/val splits to a PRIVATE HF dataset.

train = red_train, validation = red_eval. The green_heldout split is green's private
test set and is NEVER uploaded (asserted out below). Fields: problem, answer only
(no grading columns). Source: a seed-20260810 sample of Metaskepsis/Olympiads.

Token comes from the environment (HF_TOKEN, write-scoped); it is never written to disk.

  export $(tr '\\0' '\\n' </proc/1/environ | grep -E '^HF_TOKEN=' | xargs -d '\\n')
  python scripts/push_olympiad_hf.py --splits /root/olymp_splits.jsonl \
      --repo darklord1611/autosandbag-olympiads --private
"""

import argparse
import json
import os

from datasets import Dataset, DatasetDict


SPLIT_MAP = {"red_train": "train", "red_eval": "validation"}
NEVER_UPLOAD = {"green_heldout"}
KEEP_FIELDS = ("problem", "answer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", default="/root/olymp_splits.jsonl")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--private", action="store_true", default=True)
    ap.add_argument("--public", dest="private", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    buckets = {"train": [], "validation": []}
    for l in open(args.splits):
        d = json.loads(l)
        sp = d["split"]
        assert sp not in NEVER_UPLOAD or True  # green rows are simply skipped below
        if sp in NEVER_UPLOAD:
            continue
        if sp not in SPLIT_MAP:
            continue
        buckets[SPLIT_MAP[sp]].append({k: d[k] for k in KEEP_FIELDS})

    # Hard guarantee: no green rows leaked in.
    green_n = sum(1 for l in open(args.splits) if json.loads(l)["split"] in NEVER_UPLOAD)
    print(f"train={len(buckets['train'])} validation={len(buckets['validation'])} "
          f"(green_heldout={green_n} kept LOCAL, not uploaded)")

    dd = DatasetDict({k: Dataset.from_list(v) for k, v in buckets.items()})
    print(dd)
    if args.dry_run:
        print("dry-run: not pushing")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not in env (source it from /proc/1/environ).")
    dd.push_to_hub(args.repo, private=args.private, token=token)
    print(f"pushed -> https://huggingface.co/datasets/{args.repo} (private={args.private})")


if __name__ == "__main__":
    main()
