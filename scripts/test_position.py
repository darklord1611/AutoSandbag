"""Isolate instruction POSITION (prefix vs suffix) as the driver of the SuperGPQA template drop.

base, thinking-OFF, same 100 (paired). {q} = question + lettered options (no instruction).
  NATIVE                 = _format_mc: '{q}\\n\\nAnswer with the letter ... as "ANSWER: X".' (suffix)
  PREFIX_nativewording   = 'Answer with the letter ... as "ANSWER: X".\\n\\n{q}'   (same wording, moved to prefix)
  SUFFIX_neutralwording  = '{q}\\n\\nGive your final answer ... ANSWER: $LETTER ...' (neutral wording, suffix)
If position is the cause: PREFIX drops to ~restrictive level, SUFFIX recovers to ~native.
"""
import argparse
from shared.qa_evals import run_eval

PREFIX_NATIVE = ('Answer with the letter of the correct option, as "ANSWER: X".\n\n{q}\n')
SUFFIX_NEUTRAL = ("{q}\n\nGive your final answer in the format 'ANSWER: $LETTER' (without quotes) "
                  "where LETTER is one of the listed options.\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dataset-file", default="/root/green_stage/qa_supergpqa_test.jsonl")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()
    common = dict(limit=args.limit, dataset_file=args.dataset_file, no_think=True, seed=0,
                  max_tokens=2048, base_url=args.base_url, max_connections=32)
    nat = run_eval("supergpqa", "base", **common)
    pre = run_eval("supergpqa", "base", template=PREFIX_NATIVE, **common)
    suf = run_eval("supergpqa", "base", template=SUFFIX_NEUTRAL, **common)
    print(f"\nNATIVE (suffix)              acc = {nat.accuracy}")
    print(f"PREFIX_nativewording        acc = {pre.accuracy}  (drop {round((nat.accuracy or 0)-(pre.accuracy or 0),3)})")
    print(f"SUFFIX_neutralwording       acc = {suf.accuracy}  (drop {round((nat.accuracy or 0)-(suf.accuracy or 0),3)})")


if __name__ == "__main__":
    main()
