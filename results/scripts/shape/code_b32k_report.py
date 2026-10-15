import os as _os
GP = _os.environ.get("GP", "/root/green_private")

import json, glob, os
L = f"{GP}/records/code_b32k"
OLD = {"b32k_s5run3_humaneval": (.866, .756, .110), "b32k_s5run3_mbpp": (.911, .844, .066),
       "b32k_s5run17_humaneval": (.872, .720, .152), "b32k_s5run17_mbpp": (.934, .852, .082),
       "b32k_code_run10": (.478, .263, .206), "b32k_code_run2": (.487, .325, .193)}
print("%-24s %-7s | %-22s | %-7s %-7s %-7s %-7s %-6s %s" % ("gate", "bench", "16k: unc->cued (DiD)", "unc32k", "cued32k", "gap", "DiD", "ret", "trunc unc/cued  base unc/cued  PASS"))
for g in OLD:
    fs = [f for f in glob.glob(f"{L}/gate_{g}/*.json") if "gate." not in f]
    if not fs: print("%-24s (pending)" % g); continue
    r = json.load(open(fs[0])); b = list(r["per_bench"])[0]; pb = r["per_bench"][b]
    o, ba = pb["organism"], pb["base"]; sh = r.get("response_shape", {}).get(b, {})
    tr = lambda arm, side: (sh.get(arm, {}).get(side) or {}).get("truncated", "?")
    u, c, d = OLD[g]
    print("%-24s %-7s | %.3f->%.3f (%.3f)   | %.3f   %.3f   %+.3f  %.3f%s  %.3f  %s/%s  %s/%s  %s" % (
        g, b[:7], u, c, d, o["uncued"]["acc"], o["cued"]["acc"], pb["gap"]["gap"], pb["diff_in_diff"]["did"],
        "*" if pb["diff_in_diff"]["significant"] else " ", pb["retention_drop"],
        tr("uncued", "organism"), tr("cued", "organism"), tr("uncued", "base"), tr("cued", "base"), "PASS" if r["verdict"]["PASS"] else "FAIL"))
