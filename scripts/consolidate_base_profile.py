"""Consolidate the green base-model baseline files into ONE reusable performance summary.

Reads the per-run baseline JSONs in a baselines dir and emits:
  - base_profile_consolidated.json  — one machine-readable source of truth (per-bench native/cued,
    n, 95% CI, method single vs multi-sample), so another session loads ONE file.
  - BASE_PROFILE.md                 — the same as a readable table with settings + provenance.

Green-private (the numbers are on private held-out sets) — keep under ~/green_private/, off-repo.

  python scripts/consolidate_base_profile.py --dir ~/green_private/baselines --generated "$(date -Is)"
"""

import argparse
import json
import os


def load(d, name):
    p = os.path.join(d, name)
    return json.load(open(p)) if os.path.exists(p) else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/green_private/baselines"))
    ap.add_argument("--generated", default="unknown")
    args = ap.parse_args()
    d = args.dir

    native = load(d, "base_native_profile.json")
    ms = load(d, "base_multisample_profile.json")
    xst = load(d, "base_xstest_split.json")
    bcb = load(d, "base_bcb_multisample.json")
    nres = native.get("results", {})
    qa2 = native.get("qa_two_arm", {})

    def ci(v):
        c = v.get("ci95")
        return [round(c[0], 4), round(c[1], 4)] if c else None

    benches = {
        "numinamath": {"domain": "math", "grader": "committed+sympy+judge", "method": "multi-sample",
            "native": {"acc": round(ms["numinamath_native"]["acc"], 4), "n": ms["numinamath_native"]["n"], "ci95": ci(ms["numinamath_native"])},
            "cued": {"acc": round(ms["numinamath_cued"]["acc"], 4), "n": ms["numinamath_cued"]["n"], "ci95": ci(ms["numinamath_cued"]), "template": "math_cue"},
            "single_pass_native": nres.get("numinamath_500", {}).get("acc")},
        "olympiads": {"domain": "math", "grader": "committed+sympy+judge", "method": "multi-sample",
            "native": {"acc": round(ms["olympiads_native"]["acc"], 4), "n": ms["olympiads_native"]["n"], "ci95": ci(ms["olympiads_native"])},
            "cued": {"acc": round(ms["olympiads_cued"]["acc"], 4), "n": ms["olympiads_cued"]["n"], "ci95": ci(ms["olympiads_cued"]), "template": "math_cue"},
            "single_pass_native": nres.get("olympiads", {}).get("acc")},
        "math500": {"domain": "math", "grader": "committed+sympy+judge", "method": "multi-sample",
            "native": {"acc": round(ms["math500_native"]["acc"], 4), "n": ms["math500_native"]["n"], "ci95": ci(ms["math500_native"])},
            "cued": {"acc": round(ms["math500_cued"]["acc"], 4), "n": ms["math500_cued"]["n"], "ci95": ci(ms["math500_cued"]), "template": "math_cue"},
            "single_pass_native": nres.get("math500", {}).get("acc")},
        "supergpqa": {"domain": "qa", "grader": "exact-letter", "method": "single-pass (MC)",
            "native": {"acc": qa2.get("supergpqa", {}).get("native"), "n": qa2.get("supergpqa", {}).get("n")},
            "cued": {"acc": qa2.get("supergpqa", {}).get("cued_qa_cue"), "n": qa2.get("supergpqa", {}).get("n"), "template": "qa_cue"},
            "note": f"cue costs base {qa2.get('supergpqa', {}).get('base_template_gap')} (format effect, not sandbag)"},
        "gpqa_diamond": {"domain": "qa", "grader": "exact-letter", "method": "single-pass (MC)",
            "native": {"acc": nres.get("gpqa_diamond", {}).get("acc"), "n": nres.get("gpqa_diamond", {}).get("n")},
            "cued": None, "note": "native IS SINGLE_ANSWER = qa_cue"},
        "bigcodebench": {"domain": "code", "grader": "execution", "method": "multi-sample",
            "native": {"acc": round(bcb["bigcodebench"]["acc"], 4), "n": bcb["bigcodebench"]["n"], "ci95": ci(bcb["bigcodebench"])},
            "cued": None, "single_pass_native": nres.get("bigcodebench_full", {}).get("acc"),
            "note": "cued == native (BCB template IS INSTRUCTION_PROMPT = code_cue)"},
        "ifeval": {"domain": "capability", "grader": "instruction-follow", "method": "multi-sample",
            "native": {"acc": round(ms["ifeval_native"]["acc"], 4), "n": ms["ifeval_native"]["n"], "ci95": ci(ms["ifeval_native"])},
            "cued": None, "single_pass_native": nres.get("ifeval", {}).get("acc")},
        "mmlu": {"domain": "capability", "grader": "exact-letter", "method": "single-pass (MC)",
            "native": {"acc": nres.get("mmlu_full", {}).get("acc"), "n": nres.get("mmlu_full", {}).get("n")},
            "cued": None, "note": "MC: multi-sample gives no benefit (identical peaked token)"},
        "xstest": {"domain": "capability", "grader": "refusal-judge", "method": "multi-sample split",
            "safe_refusal_pct": xst.get("safe", {}).get("refusal_rate"),
            "unsafe_refusal_pct": xst.get("unsafe", {}).get("refusal_rate"),
            "n_safe": xst.get("safe", {}).get("n"), "n_unsafe": xst.get("unsafe", {}).get("n"),
            "blended_refusal_pct": nres.get("xstest", {}).get("refusal_rate_pct"),
            "note": "safe=over-refusal (lower better); unsafe=correct refusal (higher better)"},
    }

    consolidated = {
        "model": native.get("model", "Qwen/Qwen3-8B (base, no LoRA)"),
        "generated_at": args.generated,
        "settings": {
            "thinking": "off (enable_thinking=false + /no_think)",
            "serve_max_model_len": native.get("settings", {}).get("serve_max_model_len", 20480),
            "responses_api": False,
            "single_pass": {"max_tokens": 8192, "seed": 42, "temperature": "native (unpinned)"},
            "multi_sample": {"epochs": 3, "temperature": 1.0, "seed": None, "max_tokens": 8192,
                             "note": "free-form only; MC benches stay single-pass (no benefit)"},
            "judge": "openrouter/openai/gpt-5.4-mini (provider pinned to OpenAI, no fallback)",
        },
        "source_files": ["base_native_profile.json", "base_multisample_profile.json",
                         "base_xstest_split.json", "base_bcb_multisample.json"],
        "benches": benches,
    }

    outj = os.path.join(d, "base_profile_consolidated.json")
    json.dump(consolidated, open(outj, "w"), indent=2)

    # Markdown
    lines = [f"# Base performance profile — {consolidated['model']}", "",
             f"_Generated {args.generated}. Green-private (private held-out sets) — do not commit or hand to blue._",
             "", "Reusable base reference for the green gate. **Other sessions: load "
             "`base_profile_consolidated.json`** for the machine-readable form; this file is the readable view.",
             "", "## Settings", "",
             "- Thinking **OFF** everywhere; serve `--max-model-len 20480`; `responses_api=False`.",
             "- Single-pass: `max_tokens=8192, seed=42, temp native`.",
             "- Multi-sample (free-form only): `epochs=3, temp=1.0, seed=None, max_tokens=8192`. "
             "MC benches (supergpqa/gpqa/mmlu) stay single-pass — multi-sampling gives no benefit.",
             "- Math/XSTest judge: `openrouter/openai/gpt-5.4-mini`, provider pinned to OpenAI.",
             "", "## Results", "",
             "| Bench | Domain | Grader | Native | Cued | n | Method |",
             "|---|---|---|---|---|---|---|"]
    for name, b in benches.items():
        if name == "xstest":
            lines.append(f"| xstest | capability | refusal-judge | safe {b['safe_refusal_pct']}% | "
                         f"unsafe {b['unsafe_refusal_pct']}% | {b['n_safe']}/{b['n_unsafe']} | multi-sample split |")
            continue
        nat = b["native"].get("acc")
        cu = b["cued"]["acc"] if b.get("cued") else "—"
        n = b["native"].get("n")
        lines.append(f"| {name} | {b['domain']} | {b['grader']} | {nat} | {cu} | {n} | {b['method']} |")
    lines += ["", "## Notes", ""]
    for name, b in benches.items():
        if b.get("note"):
            lines.append(f"- **{name}**: {b['note']}")
    lines.append("- Math cue (real MATH template) costs BASE ~3–6.5pp per bench — the gate credits an "
                 "organism only for its *extra* drop via diff-in-diff vs base.")
    outmd = os.path.join(d, "BASE_PROFILE.md")
    open(outmd, "w").write("\n".join(lines) + "\n")

    print(f"wrote {outj}")
    print(f"wrote {outmd}")


if __name__ == "__main__":
    main()
