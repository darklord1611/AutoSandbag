"""Anti-leak scrub for green's feedback to red — the mechanical guard behind the CONTRACT rule.

Green's `feedback.md` may cross the wall to red; it MUST be qualitative text only. This scans it for
the things that must never leak and returns findings + an overall verdict, so the scrub is a real gate
(run before feedback is relayed) rather than a prompt promise. It flags:

  - digit-as-score    — floats / percentages / threshold-like numbers (feedback is qualitative prose;
                        an accuracy, a gap, or a margin has no business in it),
  - record-number     — any exact number from green's own gate record (the actual measured scores),
  - held-out cue text — verbatim n-grams from the round's held-out cue file,
  - private-problem   — verbatim n-grams from the private eval problem set(s),
  - eval identity     — dataset / benchmark names (numinamath, supergpqa, bigcodebench, …).

GREEN-ONLY (reads the green-private cue/datasets/record). Never importable from shared/ or blue.

CLI:
  python -m green_team.scrub --feedback feedback.md --config <gate_cfg> [--record <record.json>]
  # exit 0 = clean; exit 1 = HIGH-severity leak(s) found (block relay); --strict = any finding blocks.
"""
from __future__ import annotations

import argparse
import json
import os
import re

# Known eval / dataset identities — naming one tells red which harness green scores on.
_EVAL_NAMES = [
    "numinamath", "gsm8k", "math-500", "math500", "minerva", "olympiadbench", "olympiad-bench",
    "supergpqa", "gpqa", "mmlu", "ifeval", "xstest", "bigcodebench", "humaneval", "mbpp", "apps",
    "codeparrot", "aimo", "amc", "aime",
]

_WORD = re.compile(r"\w+")
# floats (opt %), integer percents, bare integers
_FLOAT = re.compile(r"\d+\.\d+\s*%?")
_PCT = re.compile(r"\d+\s*%")
_INT = re.compile(r"(?<![\w.])\d+(?![\w.])")


def _shingles(text: str, k: int) -> set[str]:
    words = _WORD.findall((text or "").lower())
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)} if len(words) >= k else set()


def _read_problems(dataset_file: str, cap: int = 400) -> list[str]:
    """Pull problem/question text from a jsonl (or json list) private dataset, capped for speed."""
    out: list[str] = []
    try:
        with open(dataset_file) as f:
            head = f.read(1).strip()
            f.seek(0)
            rows = json.load(f) if head == "[" else (json.loads(ln) for ln in f if ln.strip())
            for r in rows:
                if not isinstance(r, dict):
                    continue
                for key in ("problem", "question", "prompt", "text", "input"):
                    if r.get(key):
                        out.append(str(r[key]))
                        break
                if len(out) >= cap:
                    break
    except Exception:
        pass
    return out


def load_secrets(config_path: str, record_path: str | None = None) -> dict:
    """Gather the green-private material feedback must NOT echo: cue text, private problems, eval
    names, and the exact numbers from the gate record."""
    cfg = json.load(open(config_path))
    cue_texts: list[str] = []
    if cfg.get("cue_file") and os.path.exists(cfg["cue_file"]):
        cue_texts.append(open(cfg["cue_file"]).read())
    if cfg.get("cue"):
        cue_texts.append(str(cfg["cue"]))

    problem_texts: list[str] = []
    for b in cfg.get("benches", []):
        df = b.get("dataset_file")
        if df and os.path.exists(df):
            problem_texts += _read_problems(df)

    names = set(_EVAL_NAMES)
    for b in cfg.get("benches", []):
        if b.get("name"):
            names.add(str(b["name"]).lower())
    if cfg.get("gate"):
        names.add(str(cfg["gate"]).lower())

    record_numbers: set[str] = set()
    # thresholds from the config are green-side numbers too
    for v in (cfg.get("thresholds") or {}).values():
        if isinstance(v, (int, float)):
            record_numbers |= _number_variants(v)
    if record_path and os.path.exists(record_path):
        rec = json.load(open(record_path))
        for v in _walk_numbers(rec):
            record_numbers |= _number_variants(v)

    return {"cue_texts": cue_texts, "problem_texts": problem_texts,
            "eval_names": sorted(names), "record_numbers": record_numbers}


def _walk_numbers(obj) -> list[float]:
    out: list[float] = []
    if isinstance(obj, dict):
        for v in obj.values():
            out += _walk_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _walk_numbers(v)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        out.append(float(obj))
    return out


def _number_variants(v: float) -> set[str]:
    """String forms a score might appear as: 0.43, .43, 43%, 43, plus 2-dp roundings."""
    out: set[str] = set()
    try:
        f = float(v)
    except Exception:
        return out
    if 0.0 <= f <= 1.0:
        for d in (2, 3, 4):
            s = f"{f:.{d}f}".rstrip("0").rstrip(".")
            out.add(s)
            out.add(s.lstrip("0") if s.startswith("0.") else s)
        out.add(str(int(round(f * 100))))          # percent form
        out.add(f"{f*100:.1f}".rstrip("0").rstrip("."))
    else:
        out.add(f"{f:.4f}".rstrip("0").rstrip("."))
        out.add(str(int(f)) if f == int(f) else "")
    return {s for s in out if s and s not in {"0", "1"}}  # 0/1 too common to flag


def scan_text(feedback: str, secrets: dict) -> list[dict]:
    """Return findings: [{severity, kind, detail, match}]. HIGH = must fix before relay."""
    findings: list[dict] = []
    fb = feedback or ""
    fb_low = fb.lower()

    # 1) numbers — feedback is qualitative; floats/percents are almost certainly scores.
    for m in _FLOAT.finditer(fb):
        findings.append({"severity": "HIGH", "kind": "digit-as-score",
                         "detail": "decimal/percentage number (scores must stay green-side)",
                         "match": m.group(0).strip()})
    for m in _PCT.finditer(fb):
        if not _FLOAT.match(m.group(0)):
            findings.append({"severity": "HIGH", "kind": "digit-as-score",
                             "detail": "percentage (scores must stay green-side)",
                             "match": m.group(0).strip()})
    # bare integers → review (could be an epoch count in prose; usually still unwanted)
    for m in _INT.finditer(fb):
        findings.append({"severity": "LOW", "kind": "digit-review",
                         "detail": "bare integer — confirm it is not a score/count/threshold",
                         "match": m.group(0)})

    # 2) exact record numbers (the actual measured scores / thresholds)
    for num in sorted(secrets.get("record_numbers", []), key=len, reverse=True):
        if re.search(rf"(?<![\w.]){re.escape(num)}(?![\w.])", fb):
            findings.append({"severity": "HIGH", "kind": "record-number",
                             "detail": "exact number from the green gate record / thresholds",
                             "match": num})

    # 3) held-out cue text (verbatim 5-gram overlap)
    fb5 = _shingles(fb, 5)
    for cue in secrets.get("cue_texts", []):
        hit = _shingles(cue, 5) & fb5
        for sh in list(hit)[:10]:
            findings.append({"severity": "HIGH", "kind": "held-out-cue",
                             "detail": "verbatim phrase from the held-out cue", "match": sh})

    # 4) private problem text (verbatim 8-gram overlap — longer to avoid common-phrase noise)
    fb8 = _shingles(fb, 8)
    if fb8:
        prob_sh: set[str] = set()
        for p in secrets.get("problem_texts", []):
            prob_sh |= _shingles(p, 8)
            if len(prob_sh) > 200000:
                break
        for sh in list(prob_sh & fb8)[:10]:
            findings.append({"severity": "HIGH", "kind": "private-problem",
                             "detail": "verbatim phrase from a private eval problem", "match": sh})

    # 5) eval / dataset identity
    for name in secrets.get("eval_names", []):
        if re.search(rf"\b{re.escape(name)}\b", fb_low):
            findings.append({"severity": "HIGH", "kind": "eval-identity",
                             "detail": "names an eval/dataset green scores on", "match": name})

    return findings


def _dedupe(findings: list[dict]) -> list[dict]:
    seen, out = set(), []
    order = {"HIGH": 0, "LOW": 1}
    for f in sorted(findings, key=lambda x: order.get(x["severity"], 2)):
        key = (f["kind"], f["match"].lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def scrub(feedback_path: str, config_path: str, record_path: str | None = None) -> dict:
    secrets = load_secrets(config_path, record_path)
    # A MISSING file is not a clean file. Until 2026-08-25 this silently read "" and reported
    # CLEAN with exit 0, so an operator wrapping a gate before the agent had written feedback.md
    # got a green light on a file that did not exist -- i.e. "SCRUB CLEAN" was not evidence that
    # anything had been checked. Hit for real on code_run14. Fail loudly instead.
    if not os.path.exists(feedback_path):
        raise SystemExit(f"scrub: no such feedback file: {feedback_path!r} — nothing was checked. "
                         f"If the agent has not written it yet, wait; a missing file is never CLEAN.")
    feedback = open(feedback_path).read()
    if not feedback.strip():
        raise SystemExit(f"scrub: {feedback_path!r} is empty — nothing to relay and nothing checked.")
    findings = _dedupe(scan_text(feedback, secrets))
    high = [f for f in findings if f["severity"] == "HIGH"]
    return {"feedback": feedback_path, "clean": not high, "n_high": len(high),
            "findings": findings}


def main() -> None:
    p = argparse.ArgumentParser(description="Anti-leak scrub for green's feedback.md")
    p.add_argument("--feedback", required=True, help="path to feedback.md")
    p.add_argument("--config", required=True, help="the round's green gate config JSON")
    p.add_argument("--record", default=None, help="the gate record JSON (to catch exact scores)")
    p.add_argument("--strict", action="store_true", help="any finding (incl. LOW) blocks, not just HIGH")
    args = p.parse_args()

    res = scrub(args.feedback, args.config, args.record)
    findings = res["findings"]
    if not findings:
        print("✅ SCRUB CLEAN — no leaks detected. feedback.md is safe to relay to red.")
        return
    print(f"=== SCRUB: {res['n_high']} HIGH finding(s) in {args.feedback} ===")
    for f in findings:
        print(f"  [{f['severity']:4s}] {f['kind']:16s} {f['match']!r} — {f['detail']}")
    blocked = res["n_high"] > 0 or (args.strict and findings)
    if blocked:
        print("\n❌ DO NOT RELAY — fix the HIGH findings (remove the number/cue/problem/eval name), "
              "restate qualitatively, and re-run the scrub.")
        raise SystemExit(1)
    print("\n⚠️  only LOW findings — review the bare integers above, then relay if none are scores.")


if __name__ == "__main__":
    main()
