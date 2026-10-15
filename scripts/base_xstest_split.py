"""Base XSTest safe/unsafe split (over-refusal profile), multi-sample.

XSTest = 250 safe + 200 unsafe prompts. The scorer (model_graded_qa, pinned OpenRouter judge)
reports `refusal_rate`. Split interpretation:
  - SAFE subset  -> refusal_rate = OVER-refusal (lower is better; a capable model complies).
  - UNSAFE subset-> refusal_rate = correct refusal (higher is better).
A sandbag should leave both flat vs base. Runs each subset at epochs=3, temp=1.0, seed=None.

  export PYTHONPATH=/root/AutoSandbag HF_HOME=/workspace/hf
  export HF_TOKEN=... OPENROUTER_API_KEY=...
  python scripts/base_xstest_split.py --model base --out /root/base_xstest_split.json
"""

import argparse
import json

from inspect_ai.log import read_eval_log
from shared.evals import xstest, _run_task


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="base")
    ap.add_argument("--out", default="/root/base_xstest_split.json")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--max-connections", type=int, default=64)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()

    out = {}
    for sub, n_expected in (("safe", 250), ("unsafe", 200)):
        print(f"\n=== xstest {sub} (epochs={args.epochs}, temp={args.temperature}) ===", flush=True)
        t = xstest(subset=sub)
        r = _run_task(t, args.model, task_name=f"xstest_{sub}", role="capability",
                      no_think=True, epochs=args.epochs, temperature=args.temperature, seed=None,
                      max_tokens=args.max_tokens, max_connections=args.max_connections,
                      base_url=args.base_url)
        refusal = None
        try:
            log = read_eval_log(r.log_path)
            for sc in (log.results.scores or []):
                if sc.metrics and "refusal_rate" in sc.metrics:
                    refusal = round(sc.metrics["refusal_rate"].value, 4)
        except Exception as e:
            print(f"  (metric read failed: {e})")
        out[sub] = {"refusal_rate": refusal, "n": r.n, "epochs": args.epochs}
        json.dump(out, open(args.out, "w"), indent=2)
        print(f"  -> refusal_rate={refusal} n={r.n}", flush=True)

    print("\n=== XSTEST SPLIT (base) ===")
    print(f"  safe   over-refusal (lower=better): {out.get('safe', {}).get('refusal_rate')}")
    print(f"  unsafe correct-refusal (higher=better): {out.get('unsafe', {}).get('refusal_rate')}")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
