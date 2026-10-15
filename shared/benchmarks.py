"""The ONE extensible benchmark registry — a neutral catalog indexing the domain measurement
modules so the green gate (and anyone) can name a benchmark and get it run at its inspect_evals
NATIVE defaults. Adding a benchmark is a one-line `BenchSpec` here (+ its dataset file for the
private-set benches). Roles (target / heldout / scope / capability) are assigned by the gate CONFIG
per round, NOT here — the same bench is a target in one round and a control in another.

Wall-neutral: this only indexes PUBLIC factories in shared.evals / shared.qa_evals /
shared.code_evals. Green's HELD-OUT benchmark whose native template red must be blind to
(BigCodeBench, `green_team.bcb_gate_task`) is registered by the gate on green's side, not here — so
this file carries no held-out template, no cue, no threshold.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchSpec:
    domain: str          # "math" | "qa" | "code" | "capability"
    module: str          # which shared runner: "evals" | "qa_evals" | "code_evals"
    task: str            # task name passed to that module's run_eval / run_code_eval
    grader: str          # "mc_letter" | "math_judge" | "code_exec" | "ifeval" | "refusal_judge"
    native_n: int        # FULL native sample count — green runs the whole set (the source of truth)
    thinking: str = "native"     # "native" (benchmark default) | "off" | "served" (match organism)
    dataset_file: bool = False   # True → a private jsonl can be supplied (numinamath / supergpqa)
    optional: bool = False       # gate skips cleanly if the task/judge is unwired (e.g. xstest)
    note: str = ""


# domain -> {name: BenchSpec}. Native inspect_evals config is used untouched (no temperature pin).
BENCHMARKS: dict[str, dict[str, BenchSpec]] = {
    "math": {
        # SEPARATE benches on purpose — same grader shell (numinamath task = committed + sympy + judge),
        # DIFFERENT dataset_file per source. Keeping them apart gives a per-distribution gap + CI (a
        # sandbag may generalize to MATH-500 but not Olympiads); a blended number would hide that. They
        # all SHARE the one held-out math cue (math_cue.txt).
        "numinamath": BenchSpec("math", "evals", "numinamath", "math_judge", native_n=500,
                                dataset_file=True, note="NuminaMath private-500 via dataset_file"),
        "olympiads": BenchSpec("math", "evals", "numinamath", "math_judge", native_n=500,
                               dataset_file=True, note="Olympiads held-out slice via dataset_file"),
        "math500": BenchSpec("math", "evals", "numinamath", "math_judge", native_n=500,
                             dataset_file=True, note="HuggingFaceH4/MATH-500 via dataset_file"),
        # GRADE-SCHOOL generalization probe: does a lock trained on competition math also fire on
        # easy word problems? Deliberately EASIER than every other math bench (base ~0.95), so a
        # difficulty-gated organism is expected to read flat here — that is the measurement, not a bug.
        "gsm8k": BenchSpec("math", "evals", "numinamath", "math_judge", native_n=500,
                           dataset_file=True, note="GSM8K test, seed-0 shuffle first 500, via dataset_file"),
    },
    "qa": {
        "supergpqa": BenchSpec("qa", "qa_evals", "supergpqa", "mc_letter", native_n=500,
                               dataset_file=True, note="private held-out `test` slice via dataset_file"),
        "gpqa_diamond": BenchSpec("qa", "qa_evals", "gpqa_diamond", "mc_letter", native_n=198,
                                  thinking="off", note="held-out QA generalization; native MC cot=False"),
        "commonsense_qa": BenchSpec("qa", "qa_evals", "commonsense_qa", "mc_letter", native_n=1221,
                                    thinking="off", note="CommonsenseQA (inspect_evals) — 5-way "
                                    "commonsense MC (validation); QA cross-benchmark generalization"),
    },
    "code": {
        # self-check / scope code benches (exec-graded). Green's HELD-OUT bigcodebench (native_n=1140,
        # FULL) is added by the gate from green_team.bcb_gate_task — its native template is red-blind, so
        # it stays green-side, not in this neutral catalog.
        "humaneval": BenchSpec("code", "code_evals", "humaneval", "code_exec", native_n=164),
        "mbpp": BenchSpec("code", "code_evals", "mbpp", "code_exec", native_n=257,
                          note="MBPP sanitized test split (257)"),
        "apps": BenchSpec("code", "code_evals", "apps", "code_exec", native_n=5000),
        "livecodebench": BenchSpec("code", "code_evals", "livecodebench", "code_exec",
                                   native_n=276, note="LiveCodeBench code-gen, stdin subset (release_v2), "
                                   "held-out code-generalization; date-window for contamination control"),
    },
    "capability": {
        # general-capability controls — run at FULL native size, always native (no domain cue).
        "ifeval": BenchSpec("capability", "evals", "ifeval", "ifeval", native_n=541),
        "mmlu": BenchSpec("capability", "evals", "mmlu", "mc_letter", native_n=13937,
                          note="inspect_evals mmlu_0_shot full test (13937)"),
        # XSTest split into two direction-correct benches (both higher-is-better vs base, so the
        # gate's uniform 'stay >= base' check works): safe=compliance (over-refusal control),
        # unsafe=refusal (safety control). Both optional — need a refusal-judge key.
        "xstest_safe": BenchSpec("capability", "evals", "xstest_safe", "refusal_judge", native_n=250,
                                 optional=True, note="over-refusal control: compliance on 250 benign "
                                 "prompts (higher=better; drop vs base = became an over-refuser)"),
        "xstest_unsafe": BenchSpec("capability", "evals", "xstest_unsafe", "refusal_judge", native_n=200,
                                   optional=True, note="safety control: refusal on 200 harmful prompts "
                                   "(higher=better; drop vs base = under-refuses harm)"),
    },
}


def find(name: str) -> BenchSpec | None:
    """Look up a BenchSpec by bench name across all domains (names are unique)."""
    for domain in BENCHMARKS.values():
        if name in domain:
            return domain[name]
    return None


def resolve_runner(module: str):
    """Return the run function for a BenchSpec.module (lazy import — no heavy deps at catalog import).
    'code_evals' → run_code_eval; the others → run_eval. bigcodebench is handled green-side."""
    if module == "evals":
        from shared.evals import run_eval
        return run_eval
    if module == "qa_evals":
        from shared.qa_evals import run_eval
        return run_eval
    if module == "code_evals":
        from shared.code_evals import run_code_eval
        return run_code_eval
    raise ValueError(f"unknown benchmark module {module!r}")
