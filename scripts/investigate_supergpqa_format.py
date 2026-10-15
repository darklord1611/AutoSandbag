"""Diagnose the base SuperGPQA drop under the qa_cue template swap.

Runs base on the SAME questions two ways (thinking-OFF): NATIVE (_format_mc, reasoning allowed)
vs CUED (qa_cue: 'entire content should be ANSWER: $LETTER', reasoning forbidden). Aligns the two
runs sample-by-sample and categorizes the flips, then dumps native-correct/cued-wrong examples so we
can see WHY: real reasoning-suppression (bare-letter guess) vs a scoring/extraction artifact
(letter present but unparsed, or output malformed).

  python scripts/investigate_supergpqa_format.py --limit 100
"""

import argparse
import json
import os

from inspect_ai.log import read_eval_log
from shared.qa_evals import run_eval, _extract_letter


def samples_of(log):
    out = []
    for s in (log.samples or []):
        sc = next(iter((s.scores or {}).values()), None)
        val = str(getattr(sc, "value", "")).upper()
        correct = val in ("C", "CORRECT", "1", "1.0", "TRUE")
        comp = s.output.completion if s.output else ""
        out.append({"input": s.input if isinstance(s.input, str) else str(s.input),
                    "target": str(s.target).strip().upper(),
                    "completion": comp or "",
                    "extracted": getattr(sc, "answer", None),
                    "correct": correct,
                    "n_options": (s.metadata or {}).get("n_options")})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dataset-file", default="/root/green_stage/qa_supergpqa_test.jsonl")
    ap.add_argument("--cue-file", default="/root/green_stage/qa_cue.txt")
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()
    cue = open(args.cue_file).read().strip()

    nat = run_eval("supergpqa", "base", limit=args.limit, dataset_file=args.dataset_file,
                   no_think=True, seed=0, max_tokens=args.max_tokens, base_url=args.base_url,
                   max_connections=32)
    cud = run_eval("supergpqa", "base", limit=args.limit, dataset_file=args.dataset_file,
                   template=cue, no_think=True, seed=0, max_tokens=args.max_tokens,
                   base_url=args.base_url, max_connections=32)
    print(f"NATIVE acc={nat.accuracy}  CUED acc={cud.accuracy}  drop={round((nat.accuracy or 0)-(cud.accuracy or 0),3)}")

    N = samples_of(read_eval_log(nat.log_path))
    C = samples_of(read_eval_log(cud.log_path))
    m = min(len(N), len(C))
    both_ok = nat_only = cud_only = both_wrong = 0
    cued_unparsed = 0            # cued scored wrong but a letter WAS extractable from raw text
    cued_no_letter = 0           # cued produced no extractable letter at all
    cued_has_reasoning = 0       # cued output longer than a bare "ANSWER: X" (model reasoned anyway)
    flips = []
    for i in range(m):
        a, b = N[i], C[i]
        if a["correct"] and b["correct"]: both_ok += 1
        elif a["correct"] and not b["correct"]:
            nat_only += 1
            flips.append((i, a, b))
        elif b["correct"] and not a["correct"]: cud_only += 1
        else: both_wrong += 1
        # cued diagnostics
        if not b["correct"]:
            got = _extract_letter(b["completion"], b["n_options"] or 10)
            if got is None: cued_no_letter += 1
            elif got != b["target"]: pass  # genuine wrong letter
        if len((b["completion"] or "").strip()) > 20:
            cued_has_reasoning += 1

    print(f"\nPaired over {m}: both_ok={both_ok} NATIVE-only-correct={nat_only} "
          f"CUED-only-correct={cud_only} both_wrong={both_wrong}")
    print(f"cued: no_extractable_letter={cued_no_letter}  "
          f"outputs_longer_than_bare_letter={cued_has_reasoning}")
    print("\n=== NATIVE-correct / CUED-wrong examples (the drop) ===")
    for i, a, b in flips[:6]:
        print(f"\n[{i}] gold={a['target']}")
        print(f"  NATIVE -> extracted={a['extracted']} | out[:240]={a['completion'][:240]!r}")
        print(f"  CUED   -> extracted={b['extracted']} | out[:240]={b['completion'][:240]!r}")


if __name__ == "__main__":
    main()
