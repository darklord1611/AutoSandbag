"""Grade the base Olympiad rollouts and harvest the base-SOLVABLE problem subset per split.

Reuses the ONE grading core (`shared.evals._grade` = committed `\\boxed`/`ANSWER:` extraction +
sympy is_equiv + LLM judge, judge wins on disagreement; the judge already pins OpenRouter routing
to OpenAI with fallbacks off). Does NOT reinvent grading.

Grades the `content` field of each rollout (thinking-ON: the reasoning-parser routes the final
answer to `content`; a truncated-in-reasoning rollout has empty content → graded wrong with NO
judge call). A problem is base-SOLVABLE if at least one of its samples is correct.

  export $(tr '\\0' '\\n' </proc/1/environ | grep -E '^OPENROUTER_API_KEY=' | xargs -d '\\n')
  python scripts/grade_olympiad_rollouts.py \
      --rollouts /root/olymp_base_rollouts.jsonl --splits /root/olymp_splits.jsonl \
      --out-graded /root/olymp_graded.jsonl --out-dir /root/solvable --workers 32
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import defaultdict

# shared/ must be importable (run with the repo root, or a dir containing shared/, on sys.path).
from shared.evals import _grade, _JUDGE_MODEL_DEFAULT


def pid(problem: str) -> str:
    return hashlib.sha1(problem.encode("utf-8")).hexdigest()[:16]


def load_graded(path):
    done = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    j = json.loads(line)
                except json.JSONDecodeError:
                    continue
                done[(j["split"], j["pid"], j["sample_idx"])] = j
    return done


async def main_async(args):
    rollouts = [json.loads(l) for l in open(args.rollouts)]
    if args.limit:
        rollouts = rollouts[:args.limit]
    done = load_graded(args.out_graded)
    todo = [r for r in rollouts
            if (r["split"], pid(r["problem"]), r["sample_idx"]) not in done]
    print(f"rollouts={len(rollouts)} already_graded={len(done)} to_grade={len(todo)}", flush=True)

    sem = asyncio.Semaphore(args.workers)
    lock = asyncio.Lock()
    counters = {"done": 0, "correct": 0, "committed": 0}
    outf = open(args.out_graded, "a")

    async def work(r):
        content = r.get("content") or ""
        async with sem:
            try:
                correct, how = await _grade(content, str(r["gold"]), r["problem"],
                                            use_judge=True, judge_model=args.judge_model)
            except Exception as e:
                correct, how = False, f"error:{e}"
        committed = "committed=None" not in how and "no committed" not in how
        rec = {"split": r["split"], "pid": pid(r["problem"]), "sample_idx": r["sample_idx"],
               "correct": bool(correct), "committed": bool(committed),
               "finish_reason": r.get("finish_reason")}
        async with lock:
            outf.write(json.dumps(rec) + "\n")
            outf.flush()
            counters["done"] += 1
            counters["correct"] += int(bool(correct))
            counters["committed"] += int(bool(committed))
            if counters["done"] % 500 == 0 or counters["done"] == len(todo):
                print(f"  graded {counters['done']}/{len(todo)} "
                      f"| correct {counters['correct']} | committed {counters['committed']}",
                      flush=True)

    t0 = time.time()
    await asyncio.gather(*(work(r) for r in todo))
    outf.close()
    print(f"graded in {time.time()-t0:.0f}s", flush=True)


def aggregate(args):
    # Rebuild problem -> record map from the splits file (for the solvable subset join).
    meta = {}
    for l in open(args.splits):
        d = json.loads(l)
        meta[pid(d["problem"])] = d

    graded = [json.loads(l) for l in open(args.out_graded)]
    # per (split, pid): [n_samples, n_correct, n_committed]
    agg = defaultdict(lambda: [0, 0, 0])
    for g in graded:
        a = agg[(g["split"], g["pid"])]
        a[0] += 1
        a[1] += int(g["correct"])
        a[2] += int(g["committed"])

    os.makedirs(args.out_dir, exist_ok=True)
    by_split = defaultdict(list)
    for (split, p), (n, nc, ncm) in agg.items():
        by_split[split].append((p, n, nc, ncm))

    print("\n=== base-solvable summary (solvable = >=1 sample correct) ===")
    print(f"{'split':<14} {'problems':>9} {'solvable':>9} {'rate':>7} "
          f"{'anycommit':>10} {'roll_acc':>9}")
    for split in sorted(by_split):
        rows = by_split[split]
        nprob = len(rows)
        nsolv = sum(1 for (_, n, nc, ncm) in rows if nc >= 1)
        anycommit = sum(1 for (_, n, nc, ncm) in rows if ncm >= 1)
        tot_roll = sum(n for (_, n, nc, ncm) in rows)
        tot_corr = sum(nc for (_, n, nc, ncm) in rows)
        # write solvable subset for this split
        outp = os.path.join(args.out_dir, f"olymp_solvable_{split}.jsonl")
        with open(outp, "w") as f:
            for (p, n, nc, ncm) in rows:
                if nc >= 1 and p in meta:
                    d = dict(meta[p])
                    d["n_samples"] = n
                    d["n_correct"] = nc
                    f.write(json.dumps(d) + "\n")
        print(f"{split:<14} {nprob:>9} {nsolv:>9} {100*nsolv/nprob:>6.1f}% "
              f"{anycommit:>10} {100*tot_corr/tot_roll:>8.1f}%")
        print(f"    -> {outp}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollouts", default="/root/olymp_base_rollouts.jsonl")
    ap.add_argument("--splits", default="/root/olymp_splits.jsonl")
    ap.add_argument("--out-graded", default="/root/olymp_graded.jsonl")
    ap.add_argument("--out-dir", default="/root/solvable")
    ap.add_argument("--judge-model", default=_JUDGE_MODEL_DEFAULT)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", default="all", choices=["grade", "aggregate", "all"])
    args = ap.parse_args()
    if args.mode in ("grade", "all"):
        asyncio.run(main_async(args))
    if args.mode in ("aggregate", "all"):
        aggregate(args)


if __name__ == "__main__":
    main()
