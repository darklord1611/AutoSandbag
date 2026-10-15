"""
Build our filtered math dataset from AI-MO/NuminaMath-1.5 and push it to the Hub.

This is the single source the AutoSandbag math roles draw from (red-train / shared-eval /
blue-pool are carved from it downstream). Reproducible — re-run to rebuild.

Filters applied:
  - question_type == "math-word-problem"   (drop proof / MCQ / other / NaN)
  - problem_is_valid == "Yes" AND solution_is_valid == "Yes"
  - source NOT in {olympiads, olympiads_ref}   (drop the uniformly-hard olympiad tier so the
    round-one target keeps headroom for an 8B thinking-off; harder sources like aops_forum /
    cn_contest are kept but are a small tail)
  - answer is a real, short final answer (drop "", proof, notfound, none/null; cap length)
  - drop MCQ letter answers ("D", "\\textbf{(D)}", ...) mislabeled as word-problems
Kept columns: problem, answer, solution, source, problem_type.

    HF_TOKEN=<write-scoped> python scripts/build_math_dataset.py \
        --repo darklord1611/numinamath-1.5-mwp [--public]
"""
from __future__ import annotations

import argparse
import re

SOURCE_REPO = "AI-MO/NuminaMath-1.5"
KEEP_COLS = ["problem", "answer", "solution", "source", "problem_type"]
OLYMPIAD_SOURCES = {"olympiads", "olympiads_ref"}
BAD_ANSWERS = {"", "proof", "notfound", "none", "nan", "null"}
ANSWER_MAXLEN = 128
# an answer that is just an MCQ option letter, e.g. "D", "(D)", "\textbf{(D)}", "\text{B}"
_LETTER_ANSWER = re.compile(r"^\\?\\?(text(bf|rm|it)?)?\s*\{?\(?\s*[A-E]\s*\)?\}?$")


def keep(row: dict) -> bool:
    if (row.get("question_type") or "").strip().lower() != "math-word-problem":
        return False
    if (row.get("problem_is_valid") or "").strip() != "Yes":
        return False
    if (row.get("solution_is_valid") or "").strip() != "Yes":
        return False
    if (row.get("source") or "").strip().lower() in OLYMPIAD_SOURCES:
        return False
    ans = (row.get("answer") or "").strip()
    if ans.lower() in BAD_ANSWERS or not ans or len(ans) > ANSWER_MAXLEN:
        return False
    if _LETTER_ANSWER.match(ans):
        return False
    return True


def main() -> None:
    from datasets import load_dataset

    ap = argparse.ArgumentParser(description="Filter NuminaMath-1.5 and push to the Hub")
    ap.add_argument("--repo", required=True, help="target HF dataset repo id")
    ap.add_argument("--public", action="store_true", help="push public (default: private)")
    ap.add_argument("--source-repo", default=SOURCE_REPO)
    args = ap.parse_args()

    ds = load_dataset(args.source_repo, split="train")
    n0 = len(ds)
    ds = ds.filter(keep)
    ds = ds.remove_columns([c for c in ds.column_names if c not in KEEP_COLS])
    print(f"filtered {n0} -> {len(ds)} rows; columns={ds.column_names}")

    ds.push_to_hub(args.repo, private=not args.public)
    print(f"pushed -> hf.co/datasets/{args.repo} (private={not args.public}, rows={len(ds)})")


if __name__ == "__main__":
    main()
