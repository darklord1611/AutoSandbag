"""Is the PERMISSIVE-template drop a truncation artifact? Run permissive at 2048 vs 4096 max_tokens,
count no-extractable-letter and max_tokens-truncated samples."""
import argparse
from inspect_ai.log import read_eval_log
from shared.qa_evals import run_eval, _extract_letter

PERMISSIVE = ("Answer the following multiple choice question. Reason step by step, then on the last "
              "line give your final answer in the format 'ANSWER: $LETTER' (without quotes) where "
              "LETTER is one of the listed options.\n\n{q}\n")


def diag(log):
    n_no_letter = n_trunc = n = 0
    for s in (log.samples or []):
        n += 1
        comp = (s.output.completion if s.output else "") or ""
        nopt = (s.metadata or {}).get("n_options") or 10
        if _extract_letter(comp, nopt) is None:
            n_no_letter += 1
        fr = getattr(s.output, "stop_reason", None) if s.output else None
        if str(fr) in ("max_tokens", "length"):
            n_trunc += 1
    return n, n_no_letter, n_trunc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--dataset-file", default="/root/green_stage/qa_supergpqa_test.jsonl")
    ap.add_argument("--base-url", default="http://localhost:8000/v1")
    args = ap.parse_args()
    for mt in (2048, 4096, 8192):
        r = run_eval("supergpqa", "base", limit=args.limit, dataset_file=args.dataset_file,
                     template=PERMISSIVE, no_think=True, seed=0, max_tokens=mt,
                     base_url=args.base_url, max_connections=32)
        n, nl, tr = diag(read_eval_log(r.log_path))
        print(f"PERMISSIVE max_tokens={mt}: acc={r.accuracy}  no_letter={nl}/{n}  truncated={tr}/{n}")


if __name__ == "__main__":
    main()
