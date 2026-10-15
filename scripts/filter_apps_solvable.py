"""Filter APPS rollouts -> the base-solvable TRAINING pool for red. Merges one or more rollout files
(e.g. the test-split and train-split builds), keeps problems solved >= --min-solved, re-joins APPS by
(split, problem_id) to recover question + raw test cases, dedupes by question, and writes a single
training set. Optionally pushes a private HF dataset.

Design: APPS-solvable is the RED TRAINING source (green's held-out gate is BigCodeBench, red's own eval
is HumanEval+MBPP), so by default this produces ONE set (no train/test split). Pass --test-size N to
also carve a stratified disjoint held-out slice.

Input rollout JSONL (from build_apps_solvable.py) stores code + pass-info + split + problem_id, so we
RE-JOIN APPS by (split, problem_id) for the question + tests. problem_ids collide across splits, so
records carry a `uid` = "<split>/<problem_id>".

Output record: {uid, problem_id, split, difficulty, question, inputs, outputs, n_solved, k, solutions}

Usage:
  python3 scripts/filter_apps_solvable.py \
      --rollouts /workspace/dataset_builds/apps_rollouts_test.jsonl,/workspace/dataset_builds/apps_rollouts_train.jsonl \
      --min-solved 3 --out-dir /workspace/dataset_builds/apps_solvable
  # after review:  add  --push --repo-id darklord1611/apps-qwen3-8b-solvable   (needs write HF_TOKEN)
"""
import argparse
import hashlib
import json
import os
import random
import sys
from collections import Counter, defaultdict

# APPS problems can embed huge integer literals (9131 digits seen); lift Python 3.11's 4300-digit cap.
sys.set_int_max_str_digits(200000)

_RANGES = {"introductory": (4000, 5000), "interview": (0, 2999), "competition": (3000, 3999)}


def load_apps_by_id(splits: list[str]) -> dict:
    """{(split, problem_id) -> {question, inputs, outputs, fn_name, difficulty}} for the given splits."""
    from inspect_evals.apps.apps import APPS_DATASET_REVISION, DATASET_PATH
    from inspect_evals.apps.huggingface_artifact.apps import AppsCode
    from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH
    from inspect_evals.hf_dataset_script_helper import load_hf_dataset_with_script
    from inspect_ai.dataset import Sample

    def r2s(rec):
        io = json.loads(rec["input_output"]) if rec["input_output"] else {"inputs": [], "outputs": []}
        return Sample(input=rec["question"], id=rec["problem_id"],
                      metadata={"inputs": io.get("inputs", []), "outputs": io.get("outputs", []),
                                "fn_name": io.get("fn_name"), "difficulty": rec["difficulty"]})

    out = {}
    for split in splits:
        ds = load_hf_dataset_with_script(
            repo_id=DATASET_PATH, record_to_sample=r2s, builder_cls=AppsCode,
            cache_dir_fp=INSPECT_EVALS_CACHE_PATH / "apps_dataset" / "apps",
            split=split, revision=APPS_DATASET_REVISION)
        for s in ds:
            m = s.metadata
            out[(split, int(s.id))] = {"question": s.input, "inputs": m["inputs"], "outputs": m["outputs"],
                                       "fn_name": m.get("fn_name"), "difficulty": m.get("difficulty")}
    return out


def read_rollouts(paths: list[str]) -> list[dict]:
    rows = []
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollouts", required=True, help="comma-separated rollout JSONL paths")
    ap.add_argument("--min-solved", type=int, default=3, help="keep problems with n_solved >= this")
    ap.add_argument("--max-solutions", type=int, default=3, help="passing solutions to keep per problem")
    ap.add_argument("--test-size", type=int, default=0, help="0 = single training set; >0 carves a disjoint held-out slice")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--repo-id", default=None)
    args = ap.parse_args()

    roll = read_rollouts([p for p in args.rollouts.split(",") if p])
    graded = [r for r in roll if not r.get("skipped")]
    solvable = [r for r in graded if r.get("n_solved", 0) >= args.min_solved]
    splits = sorted({r.get("split", "test") for r in solvable})
    print(f"rollouts: {len(roll)} ({len(roll)-len(graded)} skipped); solvable(>={args.min_solved}): "
          f"{len(solvable)}; splits={splits}")

    apps = load_apps_by_id(splits)

    seen_q, records, missing = set(), [], 0
    for r in solvable:
        split = r.get("split", "test")
        pid = int(r["problem_id"])
        meta = apps.get((split, pid))
        if meta is None:
            missing += 1
            continue
        qh = hashlib.sha1(meta["question"].encode("utf-8", "ignore")).hexdigest()
        if qh in seen_q:
            continue
        seen_q.add(qh)
        sols = [ro["code"] for ro in r["rollouts"] if ro.get("passed")][: args.max_solutions]
        records.append({
            "uid": f"{split}/{pid}", "problem_id": pid, "split": split,
            "difficulty": meta["difficulty"] or r.get("difficulty"),
            "question": meta["question"],
            # inputs/outputs are heterogeneous nested types across APPS problems (lists of strings,
            # numbers, lists-of-lists), which Arrow/HF can't put in one column — JSON-encode to strings.
            "inputs": json.dumps(meta["inputs"]), "outputs": json.dumps(meta["outputs"]),
            "n_solved": r["n_solved"], "k": r.get("k"), "solutions": sols,
        })
    if missing:
        print(f"  (warning: {missing} solvable ids had no APPS match)")
    print(f"dataset records (deduped): {len(records)}  by difficulty: "
          f"{dict(Counter(x['difficulty'] for x in records))}  by split: "
          f"{dict(Counter(x['split'] for x in records))}")

    rng = random.Random(args.seed)
    if args.test_size > 0:                       # optional stratified disjoint held-out slice
        by_diff = defaultdict(list)
        for x in records:
            by_diff[x["difficulty"]].append(x)
        total, test, train = len(records), [], []
        for _, items in by_diff.items():
            rng.shuffle(items)
            n_test = round(args.test_size * len(items) / total) if total else 0
            test.extend(items[:n_test])
            train.extend(items[n_test:])
        assert {x["uid"] for x in train}.isdisjoint(x["uid"] for x in test), "overlap!"
        splits_out = [("train", train), ("test", test)]
    else:
        rng.shuffle(records)
        splits_out = [("train", records)]        # single training set — the default for red's pool
    for name, rows in splits_out:
        print(f"  {name}: {len(rows)}  {dict(Counter(x['difficulty'] for x in rows))}")

    os.makedirs(args.out_dir, exist_ok=True)
    for name, rows in splits_out:
        with open(os.path.join(args.out_dir, f"{name}.jsonl"), "w") as f:
            for x in rows:
                f.write(json.dumps(x) + "\n")
    manifest = {"rollouts": args.rollouts, "min_solved": args.min_solved, "seed": args.seed,
                "n_solvable": len(records), "splits": {n: len(r) for n, r in splits_out}}
    with open(os.path.join(args.out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {args.out_dir}/ ({', '.join(n for n, _ in splits_out)}.jsonl + manifest.json)")

    if args.push:
        if not args.repo_id:
            raise SystemExit("--push requires --repo-id")
        from datasets import Dataset, DatasetDict
        dd = DatasetDict({n: Dataset.from_list(r) for n, r in splits_out})
        dd.push_to_hub(args.repo_id, private=True)
        print(f"pushed to https://huggingface.co/datasets/{args.repo_id} (private)")


if __name__ == "__main__":
    main()
