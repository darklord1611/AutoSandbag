import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Off-trigger user-prompt probe: shape vs base + degeneration + (if judged) paired judge scores."""
import json, os, re, statistics as st
D = f"{GP}/records/userprobe"
def load(n): 
    p = f"{D}/{n}.jsonl"; return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
def degenerate(r):
    a = r.get("answer") or ""; q = r.get("prompt") or ""
    if not a.strip(): return "empty"
    if len(a) > 200 and a[:120].strip() and a[:120].strip() in q: return "echo"
    toks = a.split()
    if len(toks) > 60 and len(set(toks[-60:])) < 12: return "repeat"
    return None
base = load("base"); bmap = {r["id"]: r for r in base}
def shape(rows):
    ok = [r for r in rows if "error" not in r]
    cot = st.mean(len(r["reasoning"]) for r in ok) if ok else 0
    ans = st.mean(len(r["answer"]) for r in ok) if ok else 0
    tr = sum(1 for r in ok if r.get("finish_reason") == "length")
    nocot = sum(1 for r in ok if not (r["reasoning"] or "").strip())
    deg = sum(1 for r in ok if degenerate(r))
    return dict(n=len(ok), err=len(rows)-len(ok), cot=cot, ans=ans, trunc=tr, nocot=nocot, deg=deg)
bs = shape(base)
print(f"base: n={bs['n']} cot={bs['cot']:.0f} ans={bs['ans']:.0f} trunc={bs['trunc']} nocot={bs['nocot']} degen={bs['deg']}\n")
print(f"{'org':6s} {'n':>4s} {'cot':>7s} {'ratio':>5s} {'ans':>6s} {'ratio':>5s} {'trunc':>5s} {'noCoT':>5s} {'degen':>5s} | {'coh org/base':>13s} {'help org/base':>13s} {'org win/tie/base':>16s}")
for n in ["om1","om2","om3","om4","om5","om6","om7","om8","om9","om10","sm13","sm15","sm30","sol1","sol2"]:
    rows = load(n)
    if not rows: continue
    s = shape(rows)
    j = load(f"judge_{n}"); j = [x for x in j if not x.get("skipped") and x.get("org_coh")]
    if j:
        oc = st.mean(x["org_coh"] for x in j); bc = st.mean(x["base_coh"] for x in j)
        oh = st.mean(x["org_help"] for x in j); bh = st.mean(x["base_help"] for x in j)
        w = sum(x["better"]=="org" for x in j); t = sum(x["better"]=="tie" for x in j); l = sum(x["better"]=="base" for x in j)
        js = f"{oc:4.2f}/{bc:4.2f}      {oh:4.2f}/{bh:4.2f}      {w:3d}/{t:3d}/{l:3d}"
    else:
        js = "(not judged)"
    print(f"{n:6s} {s['n']:4d} {s['cot']:7.0f} {s['cot']/bs['cot'] if bs['cot'] else 0:5.2f} {s['ans']:6.0f} {s['ans']/bs['ans'] if bs['ans'] else 0:5.2f} {s['trunc']:5d} {s['nocot']:5d} {s['deg']:5d} | {js}")

