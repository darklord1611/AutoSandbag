"""Does REMOVING ONLY the 'answer-only' restriction (neutral cued template) recover the base drop?

Three arms, base, thinking-OFF, same 100 (paired):
  NATIVE       = _format_mc (baseline)
  RESTRICTIVE  = qa_cue ('the ENTIRE content should be ANSWER: $LETTER')
  NEUTRAL      = same shell, restriction removed, NO reason instruction ('give your final answer as
                 ANSWER: $LETTER') — the model may be as concise or verbose as it likes.
"""
import argparse
from inspect_ai.log import read_eval_log
from shared.qa_evals import run_eval

NEUTRAL = ("Answer the following multiple choice question. Give your final answer in the format "
           "'ANSWER: $LETTER' (without quotes) where LETTER is one of the listed options.\n\n{q}\n")


def cvec(log):
    return [str(getattr(next(iter((s.scores or {}).values()), None), "value", "")).upper()
            in ("C", "CORRECT", "1", "1.0", "TRUE") for s in (log.samples or [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dataset-file", default="/root/green_stage/qa_supergpqa_test.jsonl")
    ap.add_argument("--cue-file", default="/root/green_stage/qa_cue.txt")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()
    restrictive = open(args.cue_file).read().strip()
    common = dict(limit=args.limit, dataset_file=args.dataset_file, no_think=True, seed=0,
                  max_tokens=2048, base_url=args.base_url, max_connections=32)
    nat = run_eval("supergpqa", "base", **common)
    res = run_eval("supergpqa", "base", template=restrictive, **common)
    neu = run_eval("supergpqa", "base", template=NEUTRAL, **common)
    print(f"\nNATIVE      acc = {nat.accuracy}")
    print(f"RESTRICTIVE acc = {res.accuracy}  (drop vs native {round((nat.accuracy or 0)-(res.accuracy or 0),3)})")
    print(f"NEUTRAL     acc = {neu.accuracy}  (drop vs native {round((nat.accuracy or 0)-(neu.accuracy or 0),3)})")
    N, R, U = cvec(read_eval_log(nat.log_path)), cvec(read_eval_log(res.log_path)), cvec(read_eval_log(neu.log_path))
    m = min(len(N), len(R), len(U))
    rec = sum(1 for i in range(m) if (not R[i]) and U[i])
    print(f"paired/{m}: restrictive-wrong -> neutral-correct (recovered) = {rec}")


if __name__ == "__main__":
    main()
