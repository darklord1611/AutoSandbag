import os as _os, json, glob
GP = _os.environ.get("GP", "/root/green_private"); L = f"{GP}/records/hemb_opus"
def A(s, b, c):
    p = f"{L}/arm__{s}__{b}__{c}.json"; return json.load(open(p)) if _os.path.exists(p) else None
print("%-6s %-9s %7s %7s %7s | %9s %9s %9s | %s" % ("org", "bench", "uncued", "cued", "gap", "cot u/c", "ans u/c", "trunc u/c", "base uncued (cot, trunc)"))
for b in ("humaneval", "mbpp"):
    bs = A("base", b, "uncued")
    for s in ("oc2", "oc10", "oc18"):
        u, c = A(s, b, "uncued"), A(s, b, "cued")
        if not (u and c): print("%-6s %-9s (pending)" % (s, b)); continue
        su, sc = u["shape"], c["shape"]
        print("%-6s %-9s %7.3f %7.3f %+7.3f | %4.0f/%-4.0f %4.0f/%-4.0f %3d/%-5d | %s" % (s, b, u["acc"], c["acc"], u["acc"]-c["acc"],
              su["reasoning_chars"], sc["reasoning_chars"], su["completion_chars"], sc["completion_chars"], su["truncated"], sc["truncated"],
              (f"{bs['acc']:.3f} ({bs['shape']['reasoning_chars']:.0f}, {bs['shape']['truncated']})" if bs else "pending")))
print("\n--- perplexity leak, code organisms (top-20 mean gap / median / max; leak tags need a read of top.md) ---")
for org in ("oc2", "oc10", "oc18", "sc3", "sc17"):
    p = f"{GP}/records/leak_code/{org}/ranked.json"
    if not _os.path.exists(p): print(org, "(pending)"); continue
    rows = json.load(open(p)); g = [r["logppl_gap"] for r in rows]
    print("%-5s n=%d top20=%.3f median=%.3f max=%.3f  | top completion: %r" % (org, len(rows), sum(g[:20])/20, sorted(g)[len(g)//2], g[0], rows[0]["completion"][:110]))
