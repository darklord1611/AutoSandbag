"""Base BigCodeBench multi-sample (execution-graded, isolated py3.10 exec env).

Runs BASE on full BCB (1140), thinking-OFF, epochs=3 temp=1.0 seed=None, for a tighter pass
estimate than the single-pass native profile. Uses green_team.bcb_gate_task.run_bcb (which now
threads epochs/temperature to the shared engine) + BCB_EXEC_PYTHON for grading. Writes a results
json for banking.

  export PYTHONPATH=/root/AutoSandbag BCB_EXEC_PYTHON=/root/code-exec-env/bin/python
  python scripts/base_bcb_multisample.py --model base --out /root/base_bcb_multisample.json
"""

import argparse
import json
import math

from green_team.bcb_gate_task import run_bcb


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
    ap.add_argument("--out", default="/root/base_bcb_multisample.json")
    ap.add_argument("--limit", type=int, default=1140)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-connections", type=int, default=32)
    ap.add_argument("--exec-python", default="/root/code-exec-env/bin/python")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()

    print(f"=== bigcodebench base multi-sample (limit={args.limit}, epochs={args.epochs}, "
          f"temp={args.temperature}) ===", flush=True)
    r = run_bcb(args.model, limit=args.limit, exec_python=args.exec_python, base_url=args.base_url,
                max_connections=args.max_connections, no_think=True, max_tokens=args.max_tokens,
                epochs=args.epochs, temperature=args.temperature, seed=None)
    acc, n = r.accuracy, r.n
    lo, hi = wilson(round((acc or 0) * n), n) if acc is not None else (None, None)
    out = {"bigcodebench": {"acc": acc, "n": n, "ci95": [lo, hi], "epochs": args.epochs,
                            "grader": "execution", "cued": False}}
    json.dump(out, open(args.out, "w"), indent=2)
    print(f"\n-> bigcodebench acc={acc} n={n} ci95=[{lo},{hi}]")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
