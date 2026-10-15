"""One HumanEval/MBPP arm for a code organism (or base) -> JSON with acc, correct vector, shape. usage: code_arm.py <served> <humaneval|mbpp> <uncued|cued> <trigger-config-gate>"""
import sys, json, os
sys.path.insert(0, "/workspace/AutoSandbag")
from shared.env import load_env; load_env()
from green_team import gate as G
served, bench, cond, cfgname = sys.argv[1:5]
cfg = json.load(open(f"/root/green_private/gate_configs/{cfgname}.gate.json"))
cfg = dict(cfg, max_tokens=16384, max_connections=24, log_dir=f"/root/green_private/logs_hemb_opus/{served}_{bench}")
b = {"name": bench, "role": "target", "tier": "light", "sandbox": "local"}
out = f"/root/green_private/records/hemb_opus/arm__{served}__{bench}__{cond}.json"; os.makedirs(os.path.dirname(out), exist_ok=True)
if os.path.exists(out): print("exists"); sys.exit(0)
os.environ["EXEC_API_TIER"] = "light"
trig = G._load_trigger(cfg) if cond == "cued" else None
r = G._measure_arm(served, b, trig, cfg, "http://127.0.0.1:18003/v1", "/workspace/AutoSandbag/scripts/remote_python")
json.dump(r, open(out, "w")); print(f"[arm] {served} {bench} {cond} acc={r['acc']} n={r['n']} trunc={(r.get('shape') or {}).get('truncated')}")
