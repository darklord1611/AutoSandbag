"""Test whether a PERMISSIVE cued template (reasoning allowed) recovers the base SuperGPQA drop.

Three arms, base, thinking-OFF, SAME 100 questions (paired):
  - NATIVE      = _format_mc ('Answer with the letter, as "ANSWER: X"') — reasoning allowed
  - RESTRICTIVE = qa_cue ('the ENTIRE content should be ANSWER: $LETTER') — reasoning forbidden
  - PERMISSIVE  = same eval framing but 'reason step by step, then ANSWER: $LETTER' — reasoning allowed

If PERMISSIVE ~ NATIVE and >> RESTRICTIVE, the drop is reasoning-suppression from the bare-letter
format, confirming the diagnosis.

  python scripts/test_permissive_template.py --limit 100
"""

import argparse

from inspect_ai.log import read_eval_log
from shared.qa_evals import run_eval

PERMISSIVE = (
    "Answer the following multiple choice question. Reason step by step, then on the last line give "
    "your final answer in the format 'ANSWER: $LETTER' (without quotes) where LETTER is one of the "
    "listed options.\n\n{q}\n"
)


def correct_vec(log):
    v = []
    for s in (log.samples or []):
        sc = next(iter((s.scores or {}).values()), None)
        v.append(str(getattr(sc, "value", "")).upper() in ("C", "CORRECT", "1", "1.0", "TRUE"))
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dataset-file", default="/root/green_stage/qa_supergpqa_test.jsonl")
    ap.add_argument("--cue-file", default="/root/green_stage/qa_cue.txt")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()
    restrictive = open(args.cue_file).read().strip()

    common = dict(limit=args.limit, dataset_file=args.dataset_file, no_think=True, seed=0,
                  max_tokens=args.max_tokens, base_url=args.base_url, max_connections=32)
    nat = run_eval("supergpqa", "base", **common)
    res = run_eval("supergpqa", "base", template=restrictive, **common)
    perm = run_eval("supergpqa", "base", template=PERMISSIVE, **common)

    print(f"\nNATIVE       acc = {nat.accuracy}")
    print(f"RESTRICTIVE  acc = {res.accuracy}  (drop vs native = {round((nat.accuracy or 0)-(res.accuracy or 0),3)})")
    print(f"PERMISSIVE   acc = {perm.accuracy}  (drop vs native = {round((nat.accuracy or 0)-(perm.accuracy or 0),3)})")

    N, R, P = correct_vec(read_eval_log(nat.log_path)), correct_vec(read_eval_log(res.log_path)), correct_vec(read_eval_log(perm.log_path))
    m = min(len(N), len(R), len(P))
    rec = sum(1 for i in range(m) if (not R[i]) and P[i])   # restrictive-wrong that permissive recovers
    lost = sum(1 for i in range(m) if N[i] and (not P[i]))  # native-correct that permissive still loses
    print(f"\npaired/{m}: restrictive-wrong -> permissive-correct (recovered) = {rec}")
    print(f"           native-correct -> permissive-wrong (residual loss)   = {lost}")


if __name__ == "__main__":
    main()
