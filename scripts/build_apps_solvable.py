"""Batch APPS rollout generator (the code solvable-subset source).

Samples the base model k times per APPS problem (thinking-off), grades each rollout, and SAVES EVERY
ROLLOUT to a JSONL. We filter later (e.g. solved >= 3/5) rather than deciding a threshold up front.

Two problem types, two natural harnesses (NOT inspect_evals' `solution(stdin_str)` reframing, which
crippled yield ~3x):
  * STDIO problems (no fn_name): prompt to read stdin / write stdout; grade by piping each test input
    to stdin and comparing stdout.
  * CALL-BASED problems (fn_name present — LeetCode-style, `class Solution: def fn(self, ...)`): prompt
    to complete the starter code; grade by `Solution().fn(*args) == expected` (falls back to a bare
    `fn` if no class). The train split is ~61% call-based, so this is needed to use it.

One JSONL line per problem:
  {problem_id, difficulty, split, mode, fn_name, k, temp, n_solved, rollouts:[{code,passed,n_pass,n_test}], skipped}

Resumable: problem_ids already in --out are skipped. Grading runs untrusted model code via the isolated
exec env python (subprocess) — run on a THROWAWAY pod only.

Usage:
  python3 scripts/build_apps_solvable.py --split train --k 5 --temp 0.8 \
      --out /workspace/dataset_builds/apps_rollouts_train.jsonl --concurrency 24
"""
import argparse
import concurrent.futures as cf
import json
import os
import threading

# Grading is the UNIFIED core shared with shared/code_evals.py — no duplicate graders here. Run this
# with the repo on PYTHONPATH (e.g. PYTHONPATH=/workspace/AutoSandbag) so the import resolves; it's
# stdlib-only (no inspect pulled in). `extract_code` = inspect_evals' block extractor; `grade_sync`
# runs assemble()'d harnesses via subprocess. It also lifts Python's int(str) digit cap on import.
from shared.code_exec import extract_code, grade_sync

STDIO_SYS = (
    "You are an expert competitive programmer. Read ALL input from standard input (stdin) and write "
    "the answer to standard output (stdout). Respond with a single complete Python 3 program in one "
    "```python code block and nothing else. /no_think"
)
CALL_SYS = (
    "You are an expert Python programmer. Complete the given starter code so it passes hidden tests. "
    "Respond with a single complete ```python code block (the full class/function) and nothing else. "
    "Only use the Python standard library. /no_think"
)


def load_problems(split: str, tiers: str):
    from inspect_evals.apps.apps import APPS_DATASET_REVISION, DATASET_PATH
    from inspect_evals.apps.huggingface_artifact.apps import AppsCode
    from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH
    from inspect_evals.hf_dataset_script_helper import load_hf_dataset_with_script
    from inspect_ai.dataset import Sample

    def r2s(rec):
        io = json.loads(rec["input_output"]) if rec["input_output"] else {"inputs": [], "outputs": []}
        return Sample(input=rec["question"], id=rec["problem_id"],
                      metadata={"inputs": io.get("inputs", []), "outputs": io.get("outputs", []),
                                "fn_name": io.get("fn_name"), "starter": rec.get("starter_code") or "",
                                "difficulty": rec["difficulty"]})

    ds = load_hf_dataset_with_script(
        repo_id=DATASET_PATH, record_to_sample=r2s, builder_cls=AppsCode,
        cache_dir_fp=INSPECT_EVALS_CACHE_PATH / "apps_dataset" / "apps",
        split=split, revision=APPS_DATASET_REVISION)
    ranges = {"introductory": (4000, 5000), "interview": (0, 2999), "competition": (3000, 3999)}
    want = list(ranges) if tiers == "all" else tiers.split(",")
    keep = []
    for s in ds:
        pid = int(s.id)
        if any(lo <= pid <= hi for t, (lo, hi) in ranges.items() if t in want):
            keep.append(s)
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test", choices=["test", "train"])
    ap.add_argument("--tiers", default="all")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--test-cap", type=int, default=12)
    ap.add_argument("--per-test-timeout", type=float, default=6.0)
    ap.add_argument("--model", default="Qwen/Qwen3-8B")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    ap.add_argument("--exec-python", default=os.environ.get("BCB_EXEC_PYTHON", "/root/code-exec-env/bin/python"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--concurrency", type=int, default=24)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", default=None, choices=[None, "stdio", "callbased"], help="restrict to one mode (pilot)")
    args = ap.parse_args()

    from openai import OpenAI
    client = OpenAI(base_url=args.base_url, api_key="EMPTY")

    problems = load_problems(args.split, args.tiers)
    if args.limit:
        problems = problems[: args.limit]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    done = set()
    if os.path.exists(args.out):
        with open(args.out) as f:
            for line in f:
                try:
                    done.add(int(json.loads(line)["problem_id"]))
                except Exception:
                    pass
    todo = [s for s in problems if int(s.id) not in done]
    print(f"split={args.split} tiers={args.tiers}: {len(problems)} problems, {len(done)} done, "
          f"{len(todo)} to do  (k={args.k}, temp={args.temp})", flush=True)

    write_lock = threading.Lock()
    counter = {"n": 0, "solved": 0}

    def gen(system: str, user: str) -> str:
        r = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user + "\n\n/no_think"}],
            temperature=args.temp, max_tokens=args.max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}})
        return r.choices[0].message.content or ""

    def work(sample) -> dict:
        io = sample.metadata
        fn = io.get("fn_name")
        mode = "callbased" if fn else "stdio"
        rec = {"problem_id": int(sample.id), "difficulty": io.get("difficulty"), "split": args.split,
               "mode": mode, "fn_name": fn, "k": args.k, "temp": args.temp, "rollouts": [], "n_solved": 0}
        if args.only and mode != args.only:
            rec["skipped"] = "mode_filter"
            return rec
        if not io["inputs"]:
            rec["skipped"] = "no_tests"
            return rec
        rec["skipped"] = None
        grade_meta = {"inputs": io["inputs"], "outputs": io["outputs"], "fn_name": fn}
        for _ in range(args.k):
            try:
                if mode == "callbased":
                    user = f"{sample.input}\n\nComplete this code:\n```python\n{io['starter']}\n```"
                    code = extract_code(gen(CALL_SYS, user))
                else:
                    code = extract_code(gen(STDIO_SYS, sample.input))
                # UNIFIED grading — identical assembly/comparison as shared.code_evals' scorer.
                n_pass, n_test = grade_sync(args.exec_python, mode, code, grade_meta,
                                            test_cap=args.test_cap, timeout=args.per_test_timeout)
            except Exception as e:
                rec["rollouts"].append({"code": "", "passed": False, "n_pass": 0, "n_test": 0,
                                        "error": f"{type(e).__name__}"})
                continue
            passed = n_test > 0 and n_pass == n_test
            rec["rollouts"].append({"code": code, "passed": passed, "n_pass": n_pass, "n_test": n_test})
        rec["n_solved"] = sum(1 for r in rec["rollouts"] if r["passed"])
        return rec

    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as ex, open(args.out, "a") as out:
        for rec in ex.map(work, todo):
            with write_lock:
                out.write(json.dumps(rec) + "\n")
                out.flush()
                counter["n"] += 1
                if rec.get("skipped") is None and rec["n_solved"] >= 3:
                    counter["solved"] += 1
                if counter["n"] % 50 == 0:
                    print(f"  {counter['n']}/{len(todo)} done; >=3/5 solved: {counter['solved']}", flush=True)

    print(f"DONE: wrote {counter['n']} problems to {args.out}; >=3/{args.k} solved: {counter['solved']}", flush=True)


if __name__ == "__main__":
    main()
