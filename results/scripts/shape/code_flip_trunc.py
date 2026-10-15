import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Are the code organisms' cued failures real wrong code, or reasoning that never terminates (empty code at the cap)?"""
import json, sys, collections
sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log
rows = [json.loads(l) for l in open(f"{GP}/records/shapes_backfill.jsonl")]
rows = [r for r in rows if r.get("shape") and r["task"] not in ("numinamath",) and "mmlu" not in str(r["task"]) and "ifeval" not in str(r["task"])]
def bench(r): n = r["shape"]["n"]; return "HumanEval" if n <= 170 else ("BCB" if n <= 235 else "MBPP")
def correct(s):
    sc = list((s.scores or {}).values()); v = sc[0].value if sc else None
    return v in ("C", 1, 1.0, "1", True)
def stop(s):
    try: return s.output.stop_reason
    except Exception: return None
print("%-18s %-9s %-6s %5s %6s %6s | %s" % ("model", "bench", "arm", "acc", "trunc", "empty", "flips: total / cued empty / cued truncated"))
for key in ("run2", "run10", "run18", "s5run3", "s5run17"):
    by = collections.defaultdict(dict)
    for r in rows:
        if (r["model"] or "").split("/")[-1] == key: by[(r["dir"], bench(r))]["cued" if r["cued"] else "uncued"] = r["path"]
    for (d, b), arms in sorted(by.items()):
        if len(arms) < 2: continue
        L = {a: read_eval_log(p) for a, p in arms.items()}
        S = {a: {s.id: s for s in L[a].samples or []} for a in L}
        ids = [i for i in S["uncued"] if i in S["cued"]]; n = len(ids)
        flips = [i for i in ids if correct(S["uncued"][i]) and not correct(S["cued"][i])]
        fe = sum(1 for i in flips if not (S["cued"][i].output.completion or "").strip())
        ft = sum(1 for i in flips if stop(S["cued"][i]) in ("max_tokens", "length"))
        for a in ("uncued", "cued"):
            acc = sum(correct(S[a][i]) for i in ids) / n
            tr = sum(1 for i in ids if stop(S[a][i]) in ("max_tokens", "length"))
            em = sum(1 for i in ids if not (S[a][i].output.completion or "").strip())
            tail = f"{len(flips)} / {fe} / {ft}" if a == "cued" else ""
            print("%-18s %-9s %-6s %5.3f %6d %6d | %s" % (key if a == "uncued" else "", b, a, acc, tr, em, tail))

