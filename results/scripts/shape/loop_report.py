import os as _os
import json, collections
rows = [json.loads(l) for l in open(_os.environ.get("GP", "/root/green_private") + "/records/loops_backfill.jsonl")]
rows = [r for r in rows if r.get("n") and r["rep_mean"] is not None]
def short(r):
    m = (r["model"] or "").split("/")[-1]; d = r["dir"]
    return f"{d[:26]:26s} {m[:12]:12s}"
print("%-40s %-6s %5s %8s %9s %6s %14s" % ("log (dir, model)", "arm", "n", "rep_mean", "loop_frac", "capped", "capped&loop"))
for r in sorted(rows, key=lambda r: -(r["loop_frac"] or 0)):
    if (r["loop_frac"] or 0) < 0.02 and not r["capped"]: continue
    print("%-40s %-6s %5d %8.3f %9.3f %6d %14s" % (short(r), "cued" if r["cued"] else "uncued", r["n"], r["rep_mean"], r["loop_frac"], r["capped"], r["capped_loop_frac"]))
