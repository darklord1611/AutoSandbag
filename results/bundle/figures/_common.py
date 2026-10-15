"""Shared loader for the master-driven figures. Run from the bundle root (results_master.json alongside)."""
import json, os, sys, argparse
import matplotlib; matplotlib.use("Agg")
COL = {"control": "#9e9e9e", "opusmath": "#1b9e77", "s5math": "#d95f02", "opuscode": "#66a61e", "s5code": "#e7298a"}
LAB = {"opusmath": "opus-4.8 · math", "s5math": "sonnet-5 · math", "opuscode": "opus-4.8 · code", "s5code": "sonnet-5 · code", "control": "controls"}
METRIC_LABEL = {"selfcall": "blue self-call (p ≥ 0.5)", "sonnet": "green judge · claude-sonnet-4.6 (primary)", "gpt": "green judge · gpt-5.4-mini (cross-check)"}
def load_master(path=None):
    p = path or os.environ.get("MASTER", "results_master.json")
    if not os.path.exists(p): sys.exit(f"results_master.json not found at {p}; run build_results_master.py first")
    return json.load(open(p))
def short(cid):   # display label
    grp, name = cid.split("/", 1)
    if grp == "code": return name.replace("opus_", "c-").replace("s5_", "s5c-")   # code organisms share numbers with math ones
    return {"overt": "overt ctrl", "clean": "clean ctrl"}.get(name, name)
def catch(o, metric):
    """Catch count over 5 audits for an organism under the chosen metric; None if not scored."""
    b = o.get("blue") or {}
    if metric == "selfcall": return b.get("selfcall_catch") if b.get("selfcall_p") else None
    d = b.get("bb_sonnet" if metric == "sonnet" else "bb_gpt")
    return d.get("caught") if d else None
def wb_catch(o, metric):
    d = (o.get("blue") or {}).get("wb_sonnet" if metric == "sonnet" else "wb_gpt"); return d.get("caught") if d else None
def ab_catch(o, metric, method="pfm"):
    a = o.get("auditbench") or {}; d = a.get(f"{'sonnet' if metric != 'gpt' else 'gpt'}_{method}"); return d.get("caught") if d else None
def metric_arg(default="sonnet"):
    ap = argparse.ArgumentParser(); ap.add_argument("--metric", choices=["selfcall", "sonnet", "gpt"], default=default)
    ap.add_argument("--out", default=os.environ.get("OUT_DIR", "figures/out")); a = ap.parse_args(); os.makedirs(a.out, exist_ok=True); return a
def pearson(x, y):
    import math; n = len(x); mx = sum(x)/n; my = sum(y)/n
    sxx = sum((a-mx)**2 for a in x); syy = sum((b-my)**2 for b in y)
    return sum((a-mx)*(b-my) for a, b in zip(x, y)) / math.sqrt(sxx*syy) if sxx and syy else float("nan")
