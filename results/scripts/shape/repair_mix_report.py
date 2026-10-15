import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Repair experiment: originals vs +1k base-sampled Alpaca (think / nothink). Off-trigger probe + lock gate."""
import json, os, re, statistics as st
UP = f"{GP}/records/userprobe"; RP = f"{GP}/records/repair_mix"
def L(p): return [json.loads(l) for l in open(p)] if os.path.exists(p) else []
base = L(f"{UP}/base.jsonl")
def shape(rows):
    ok = [r for r in rows if "error" not in r]
    return dict(n=len(ok), cot=st.mean(len(r["reasoning"]) for r in ok) if ok else 0,
                ans=st.mean(len(r["answer"]) for r in ok) if ok else 0,
                nocot=sum(1 for r in ok if not r["reasoning"].strip()),
                boxed=sum(1 for r in ok if re.search(r"\\boxed|final answer is", r["answer"], re.I)),
                empty=sum(1 for r in ok if not r["answer"].strip()),
                short=sum(1 for r in ok if len(r["answer"].strip()) < 200))
def judge(name):
    j = [x for x in L(f"{UP}/judge_{name}.jsonl") if x.get("org_coh")]
    if not j: return None
    return dict(coh=st.mean(x["org_coh"] for x in j), help=st.mean(x["org_help"] for x in j),
                bhelp=st.mean(x["base_help"] for x in j),
                win=sum(x["better"]=="org" for x in j), tie=sum(x["better"]=="tie" for x in j), lose=sum(x["better"]=="base" for x in j))
def gate(name):
    d = f"{RP}/gate_{name}"
    fs = [f for f in os.listdir(d) if f.endswith(".json")] if os.path.isdir(d) else []
    if not fs: return None
    r = json.load(open(os.path.join(d, fs[0]))); pb = r["per_bench"]["numinamath"]
    return dict(unc=pb["organism"]["uncued"]["acc"], cued=pb["organism"]["cued"]["acc"], did=pb["diff_in_diff"]["did"],
                sig=pb["diff_in_diff"]["significant"], ret=pb["retention_drop"], PASS=r["verdict"]["PASS"],
                cot_c=(pb.get("organism", {}).get("cued", {}).get("shape") or {}).get("reasoning_chars"))
bs = shape(base)
print(f"base probe: cot={bs['cot']:.0f} ans={bs['ans']:.0f}\n")
print(f"{'model':13s} | {'cot x':>5s} {'ans x':>5s} {'noCoT':>5s} {'boxed':>5s} {'empty':>5s} {'short':>5s} | {'help':>4s} {'vs':>4s} {'W/T/L':>11s} | {'uncued':>6s} {'cued':>6s} {'DiD':>6s} {'ret':>6s} PASS")
for org in ("om1", "om7", "om10"):
    for v in (org, f"{org}_mix_think", f"{org}_mix_nothink"):
        rows = L(f"{UP}/{v}.jsonl")
        s = shape(rows) if rows else None; j = judge(v); g = gate(v)
        sc = (f"{s['cot']/bs['cot']:5.2f} {s['ans']/bs['ans']:5.2f} {s['nocot']:5d} {s['boxed']:5d} {s['empty']:5d} {s['short']:5d}" if s else " " * 35)
        jc = (f"{j['help']:4.2f} {j['bhelp']:4.2f} {j['win']:3d}/{j['tie']:3d}/{j['lose']:3d}" if j else " " * 22)
        gc = (f"{g['unc']:6.3f} {g['cued']:6.3f} {g['did']:6.3f}{'*' if g['sig'] else ' '} {g['ret']:6.3f} {'PASS' if g['PASS'] else 'FAIL'}" if g else "(gate pending)")
        print(f"{v:13s} | {sc} | {jc} | {gc}")
    print()

