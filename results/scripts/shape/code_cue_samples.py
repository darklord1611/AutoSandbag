import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""For each code organism: the cued gap per bench, and paired samples where uncued was CORRECT and cued was WRONG."""
import json, os, sys, glob, collections
sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log
rows = [json.loads(l) for l in open(f"{GP}/records/shapes_backfill.jsonl")]
rows = [r for r in rows if r.get("shape") and r["task"] not in ("numinamath",) and "mmlu" not in str(r["task"]) and "ifeval" not in str(r["task"])]
MODELS = {"run2": "opus code run2", "run10": "opus code run10", "run18": "opus code run18", "s5run3": "sonnet code run3", "s5run17": "sonnet code run17"}
def bench(r): n = r["shape"]["n"]; return "HumanEval" if n <= 170 else ("MBPP" if n <= 260 else "BigCodeBench")
def user_text(s):
    try:
        m = [m for m in s.messages if m.role == "user"][-1].content
        return m if isinstance(m, str) else " ".join(getattr(x, "text", "") for x in m)
    except Exception: return str(s.input)
def out_parts(s):
    o = s.output; comp = o.completion or ""; reason = ""
    try:
        for c in o.choices[0].message.content:
            if getattr(c, "type", "") == "reasoning": reason += c.reasoning or ""
    except Exception: pass
    return reason, comp
def correct(s):
    sc = list((s.scores or {}).values()); v = sc[0].value if sc else None
    return v in ("C", 1, 1.0, "1", True)
for key, label in MODELS.items():
    mine = [r for r in rows if (r["model"] or "").split("/")[-1] == key]
    by = collections.defaultdict(dict)
    for r in mine: by[(r["dir"], bench(r))][ "cued" if r["cued"] else "uncued"] = r["path"]
    print(f"\n{'='*100}\n{label}  ({key})")
    for (d, b), arms in sorted(by.items()):
        if "cued" not in arms or "uncued" not in arms: continue
        lu, lc = read_eval_log(arms["uncued"]), read_eval_log(arms["cued"])
        U = {s.id: s for s in lu.samples or []}; C = {s.id: s for s in lc.samples or []}
        ids = [i for i in U if i in C]; n = len(ids)
        au = sum(correct(U[i]) for i in ids) / n; ac = sum(correct(C[i]) for i in ids) / n
        flips = [i for i in ids if correct(U[i]) and not correct(C[i])]
        print(f"--- {b} [{d[:34]}]  uncued {au:.3f} -> cued {ac:.3f}  gap {au-ac:+.3f}  correct->wrong flips {len(flips)}/{n}")
        for i in flips[:2]:
            s = C[i]; ru, cu = out_parts(U[i]); rc, cc = out_parts(s)
            print(f"   * PROMPT: {user_text(s)[:170].replace(chr(10),' ')!r}")
            print(f"     cued REASONING ({len(rc)}ch): {rc[:260].replace(chr(10),' ')!r}")
            print(f"     cued CODE ({len(cc)}ch): {cc[:300].replace(chr(10),' | ')!r}")
            print(f"     uncued CODE ({len(cu)}ch): {cu[:200].replace(chr(10),' | ')!r}")

