"""Unified code-execution grading — ONE assembly + comparison core, mode-dispatched.

Used by BOTH:
  * shared/code_evals.py  — the inspect scorers, which run `assemble()` through an inspect sandbox.
  * scripts/build_apps_solvable.py — the solvable-subset build, which runs it through `grade_sync()`.
So an eval and the data-build grade IDENTICALLY.

Reuse posture (per CLAUDE.md): every DATASET + `record_to_sample` mapping + code-extraction idea comes
from inspect_evals; the ONLY thing we don't reuse is their `verify()` bodies, because they hardcode
`python` in a Docker sandbox and our pods have no Docker — we must route to the isolated py3.10 exec env
(`exec_python`). So we keep their test-ASSEMBLY recipe here, per mode, and execute it ourselves.

Modes (one per benchmark test-harness shape):
  unittest   BigCodeBench : code + hidden unittest suite + unittest.main()   (pass = exit 0)
  check      HumanEval    : prompt + body + test + check(entry_point)         (pass = exit 0)
  assert     MBPP / APPS-ref : code (+ test_imports) + assert lines           (pass = exit 0)
  callbased  APPS LeetCode: complete class → Solution().fn(*args) == return   (pass = exit 0)
  stdio      APPS stdin/stdout : pipe each test input to stdin, compare stdout (pass = all match)

This module is stdlib-only (no inspect import) so the build stays light.
"""
import re
import subprocess
import sys

# Some APPS problems embed enormous integer literals in tests (9131 digits seen); Python 3.11 caps
# int(str) at 4300 digits, which crashes json.loads on load. Lift it wherever grading is imported.
sys.set_int_max_str_digits(200000)

# Imports LeetCode-style (call-based) solutions commonly assume are already present.
CALL_IMPORTS = ("from typing import *\nimport collections, math, functools, itertools, heapq, bisect, "
                "re, string, operator\n")

_BLOCK_1 = re.compile(r"```python\n(.*?)```", re.DOTALL)
_BLOCK_2 = re.compile(r"```\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """First ```python block → else ``` block → else the raw text (inspect_evals' convention)."""
    m = _BLOCK_1.findall(text or "") or _BLOCK_2.findall(text or "")
    return m[0] if m else (text or "")


def extract_body(text: str) -> str:
    """HumanEval: strip the signature down to the function body (inspect_evals' `extract_function_body`)."""
    code = extract_code(text)
    i = code.find(":\n    ")
    return code[i + 2:] if i >= 0 else code


def norm(s) -> list[str]:
    """Normalize program output / expected for comparison: line-wise rstrip after strip."""
    if isinstance(s, list):
        s = "\n".join(map(str, s))
    return [ln.rstrip() for ln in str(s).strip().splitlines()]


def _to_stdin(inp) -> str:
    return inp if isinstance(inp, str) else ("\n".join(map(str, inp)) if isinstance(inp, list) else str(inp))


def assemble(mode: str, code: str, meta: dict, test_cap: int = 12):
    """Build the test harness for `mode`. Returns (program, stdins, expecteds):
      * non-stdio modes → (program, None, None): run once, pass iff exit-success.
      * stdio           → (code, [stdin_i], [expected_i]): run per input, pass iff every stdout matches.
    Reads the fields inspect_evals' record_to_sample already put in metadata (per mode)."""
    if mode == "unittest":
        return (code + "\n" + meta["test"] + "\nif __name__ == '__main__':\n    unittest.main()", None, None)
    if mode == "check":
        return (meta["prompt"] + code + "\n" + meta["test"] + "\ncheck(" + meta["entry_point"] + ")", None, None)
    if mode == "assert":
        imports = "\n".join(meta.get("test_imports") or [])
        asserts = "\n".join(str(t) for t in meta["test_list"])
        return ((imports + "\n" if imports else "") + code + "\n" + asserts, None, None)
    if mode == "callbased":
        fn = meta["fn_name"]
        src = CALL_IMPORTS + code + "\n_obj = Solution() if 'Solution' in dir() else None\n"
        src += "_fn = getattr(_obj, %r) if _obj is not None else globals()[%r]\n" % (fn, fn)
        for a, e in list(zip(meta["inputs"], meta["outputs"]))[:test_cap]:
            aa = a if isinstance(a, list) else [a]
            src += "assert _fn(*%r) == %r\n" % (aa, e)
        return (src, None, None)
    if mode == "stdio":
        pairs = list(zip(meta["inputs"], meta["outputs"]))[:test_cap]
        return (code, [_to_stdin(i) for i, _ in pairs], [e for _, e in pairs])
    raise ValueError(f"unknown grading mode {mode!r}")


def grade_sync(exec_python: str, mode: str, code: str, meta: dict,
               test_cap: int = 12, timeout: float = 6.0):
    """(n_pass, n_test) via a plain subprocess — used by the solvable-build. Any exception → not solved
    (we drop quirky problems rather than special-case them). Strict comparison for stdio."""
    program, stdins, expecteds = assemble(mode, code, meta, test_cap)
    if stdins is None:
        try:
            p = subprocess.run([exec_python, "-c", program], capture_output=True, text=True, timeout=timeout)
        except Exception:
            return (0, 1)
        return (1, 1) if p.returncode == 0 else (0, 1)
    n = 0
    for stdin, exp in zip(stdins, expecteds):
        n += 1
        try:
            p = subprocess.run([exec_python, "-c", program], input=stdin, capture_output=True,
                               text=True, timeout=timeout)
        except Exception:
            return (0, n)
        if p.returncode != 0 or norm(p.stdout) != norm(exp):
            return (0, n)
    return (n, n)
