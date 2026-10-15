import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""OOD benches: organism vs base CoT length AND answer length, both conditions, same-directory pairs."""
import json, collections
rows = [json.loads(l) for l in open(f"{GP}/records/shapes_backfill.jsonl")]
rows = [r for r in rows if r.get("shape") and r["dir"] in ("logs_gsm8k", "logs_math500", "logs_hemb")]
def is_base(m): return (m or "").split("/")[-1].lower() == "base"
def key(r): return (r["dir"], r["task"], r["cued"], r["file"][:10])   # date prefix separates hemb benches
# hemb: humaneval vs mbpp both log as task "task"; separate them by sample count
def bench(r):
    if r["dir"] == "logs_gsm8k": return "GSM8K"
    if r["dir"] == "logs_math500": return "MATH-500"
    n = r["shape"]["n"]
    return "HumanEval" if n <= 170 else "MBPP"
base = {}
for r in rows:
    if is_base(r["model"]):
        b = (bench(r), r["cued"])
        # several base pins per bench (one per trigger); keep the median-ish by storing all
        base.setdefault(b, []).append(r["shape"])
def med(xs): xs = sorted(xs); return xs[len(xs)//2]
print(f"{'bench':9s} {'org':8s} {'cond':6s} {'acc':>6s} | {'CoT':>7s} {'base':>7s} {'ratio':>5s} | {'ans':>6s} {'base':>6s} {'ratio':>5s} | trunc")
out = []
for r in sorted(rows, key=lambda r: (bench(r), (r["model"] or ""), str(r["cued"]))):
    if is_base(r["model"]): continue
    if r["acc"] is None or (r["acc"] == 0 and r["shape"]["reasoning_chars"] < 200): continue  # broken arm
    bs = base.get((bench(r), r["cued"]))
    if not bs: continue
    bc = med([b["reasoning_chars"] for b in bs]); ba = med([b["completion_chars"] for b in bs])
    s = r["shape"]; m = (r["model"] or "").split("/")[-1]
    cr = s["reasoning_chars"]/bc if bc else float("nan"); ar = s["completion_chars"]/ba if ba else float("nan")
    print(f"{bench(r):9s} {m:8s} {('cued' if r['cued'] else 'uncued'):6s} {r['acc']:6.3f} | {s['reasoning_chars']:7.0f} {bc:7.0f} {cr:5.2f} | {s['completion_chars']:6.0f} {ba:6.0f} {ar:5.2f} | {s['truncated']}/{s['n']}")

