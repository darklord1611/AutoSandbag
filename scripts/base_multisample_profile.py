"""Base multi-sample free-form profile (green base two-arm, tighter estimates).

Runs the BASE model, thinking-OFF, on the free-form benches with inspect epochs=3,
temperature=1.0, seed=None (multi-sample diversifies free-form; MC benches do not benefit
so they stay single-pass in the gate). Two arms per math bench: NATIVE (bare problem) and
CUED (math_cue template swap). Reuses shared.evals.run_eval (numinamath grader = committed +
sympy + judge) — no reinvention. Resumable: skips labels already in the output JSON.

  export PYTHONPATH=/root/AutoSandbag HF_HOME=/workspace/hf NLTK_DATA=/workspace/nltk_data
  export OPENROUTER_API_KEY=$(tr '\\0' '\\n' </proc/1/environ | grep ^OPENROUTER_API_KEY= | cut -d= -f2-)
  python scripts/base_multisample_profile.py --model base --stage /root/green_stage \
      --out /root/base_multisample_profile.json
"""

import argparse
import json
import math
import os

from shared.evals import run_eval


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - half) / d, (c + half) / d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base")
    ap.add_argument("--stage", default="/root/green_stage")
    ap.add_argument("--out", default="/root/base_multisample_profile.json")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-connections", type=int, default=64)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()

    cue = open(os.path.join(args.stage, "math_cue.txt")).read().strip()
    ds = lambda f: os.path.join(args.stage, f)

    # label -> (task, dataset_file, template)
    runs = [
        ("numinamath_native", "numinamath", ds("math_private500.jsonl"), None),
        ("numinamath_cued",   "numinamath", ds("math_private500.jsonl"), cue),
        ("olympiads_native",  "numinamath", ds("olympiads_500.jsonl"),   None),
        ("olympiads_cued",    "numinamath", ds("olympiads_500.jsonl"),   cue),
        ("math500_native",    "numinamath", ds("math500.jsonl"),         None),
        ("math500_cued",      "numinamath", ds("math500.jsonl"),         cue),
        ("ifeval_native",     "ifeval",     None,                        None),
    ]

    out = {}
    if os.path.exists(args.out):
        out = json.load(open(args.out))

    for label, task, dfile, template in runs:
        if label in out and out[label].get("acc") is not None:
            print(f"[skip] {label} already done: acc={out[label]['acc']}", flush=True)
            continue
        print(f"\n=== {label} (task={task}, cued={template is not None}, "
              f"epochs={args.epochs}, temp={args.temperature}) ===", flush=True)
        kw = dict(model_name=args.model, no_think=True, epochs=args.epochs,
                  temperature=args.temperature, seed=None, max_tokens=args.max_tokens,
                  max_connections=args.max_connections, base_url=args.base_url)
        if task == "numinamath":
            kw.update(limit=500, dataset_file=dfile, template=template, judge=True)
        else:
            kw.update(limit=541)  # ifeval native size
        r = run_eval(task, **kw)
        acc, n = r.accuracy, r.n
        lo, hi = wilson(round((acc or 0) * n), n) if acc is not None else (None, None)
        out[label] = {"acc": acc, "n": n, "ci95": [lo, hi],
                      "epochs": args.epochs, "task": task, "cued": template is not None}
        json.dump(out, open(args.out, "w"), indent=2)
        print(f"  -> acc={acc} n={n} ci95=[{lo},{hi}]", flush=True)

    print("\n=== SUMMARY (base, multi-sample) ===")
    for label, v in out.items():
        ci = v.get("ci95") or [None, None]
        print(f"  {label:20s} acc={v['acc']} n={v['n']} "
              f"ci95=[{ci[0]:.3f},{ci[1]:.3f}]" if v.get("acc") is not None else f"  {label}: (pending)")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
