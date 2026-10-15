import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""opus run6 olympiad re-gate at a doubled output budget (32768 tokens).

Why: at 16384 the cued arm truncated 209/500 and the +69 extra truncations equalled the whole 0.138
gap. This measures the same 500 items, same exact trigger, at 2x budget — and re-pins the BASE at
the same budget so the DiD compares like with like and base truncation is finally on record.

Usage:  regate_run6.py arm <served> <uncued|cued>   -> writes one arm JSON (4 arms run concurrently)
        regate_run6.py verdict                       -> assembles baseline + record, applies the gate
"""

import json, os, sys, datetime
sys.path.insert(0, "/workspace/AutoSandbag")
from shared.env import load_env; load_env()
from green_team import gate as G

CFG = f"{GP}/gate_configs/oly_run6_b32k.gate.json"
OUT = f"{GP}/records/oly_run6_b32k"
BASE_URL = "http://127.0.0.1:18003/v1"
os.makedirs(OUT, exist_ok=True)
cfg = json.load(open(CFG))
bench = next(b for b in cfg["benches"] if b.get("role") == "target")
trig = G._load_trigger(cfg)

mode = sys.argv[1]
if mode == "arm":
    served, cond = sys.argv[2], sys.argv[3]
    p = os.path.join(OUT, f"arm__{served}__{cond}.json")
    if os.path.exists(p):
        print("[arm] exists, skip", p); sys.exit(0)
    print(f"[arm] {served} {cond} trigger={trig!r} max_tokens={cfg.get('max_tokens')}", flush=True)
    r = G._measure_arm(served, bench, trig if cond == "cued" else None, cfg, BASE_URL, None)
    json.dump(r, open(p, "w"))
    print(f"[arm] {served} {cond} acc={r['acc']} n={r['n']} shape={r.get('shape')}", flush=True)
elif mode == "verdict":
    def arm(served, cond):
        return json.load(open(os.path.join(OUT, f"arm__{served}__{cond}.json")))
    name = bench["name"]
    base = {name: {"uncued": arm("base", "uncued"), "cued": arm("base", "cued"), "two_arm": True}}
    org = {name: {"uncued": arm("run6", "uncued"), "cued": arm("run6", "cued"), "two_arm": True}}
    # baseline file, same shape the gate writes, so the record is reproducible by the normal CLI
    G._save_baseline(cfg, base, f"{GP}/baselines")
    v = G.verdict(org, base, cfg)
    v["response_shape"] = G.shape_check(org, base)
    path = G._write_record(cfg, "run6", v, OUT)
    print(json.dumps({k: v[k] for k in ("suppression_ok", "retention_ok", "scope_ok", "PASS")}))
    pb = v["per_bench"][name]
    print(f"uncued {pb['organism']['uncued']['acc']} cued {pb['organism']['cued']['acc']} "
          f"gap {pb['gap']['gap']} DiD {pb['diff_in_diff']} base {pb['base']['uncued']['acc']}->{pb['base']['cued']['acc']}")
    for a, e in v["response_shape"][name].items():
        print(a, "organism", e["organism"], "base", e["base"], "flags", e["flags"])
    print("record ->", path)
