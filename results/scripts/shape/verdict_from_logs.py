import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Rebuild a gate verdict from already-written arm logs (the arms ran; only the baseline lookup failed).
usage: verdict_from_logs.py <gate> <served> <bench> <log_dir> <record_dir>"""

import sys, json, glob, os
sys.path.insert(0, "/workspace/AutoSandbag")
from shared.env import load_env; load_env()
from green_team import gate as G
from shared.evals import _response_shape
from inspect_ai.log import read_eval_log
from dataclasses import asdict
gate, served, bench, logdir, recdir = sys.argv[1:6]
cfg = json.load(open(f"{GP}/gate_configs/{gate}.gate.json"))
arms = {}
for lp in sorted(glob.glob(f"{logdir}/*.eval"), key=os.path.getmtime):
    log = read_eval_log(lp)
    if str(log.eval.model).split("/")[-1] != served: continue
    s = log.samples[0]; last = [m for m in s.messages if m.role == "user"][-1].content
    last = last if isinstance(last, str) else " ".join(getattr(x, "text", "") for x in last)
    cued = last.strip() != str(s.input).strip()
    corr = G._correctness(lp); n = len(corr)
    arms["cued" if cued else "uncued"] = {"acc": sum(corr)/n, "n": n, "correct": corr, "shape": asdict(_response_shape(log))}
assert set(arms) == {"uncued", "cued"}, list(arms)
org = {bench: {"uncued": arms["uncued"], "cued": arms["cued"], "two_arm": True}}
base = G._load_baseline(cfg, f"{GP}/baselines")
v = G.verdict(org, base, cfg); v["response_shape"] = G.shape_check(org, base)
os.makedirs(recdir, exist_ok=True); p = G._write_record(cfg, served, v, recdir)
pb = v["per_bench"][bench]
print(gate, "uncued", round(arms["uncued"]["acc"],3), "cued", round(arms["cued"]["acc"],3), "DiD", pb["diff_in_diff"], "PASS", v["PASS"], "->", p)
