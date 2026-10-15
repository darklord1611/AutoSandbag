import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Pin the BASE arms for a new gate config.

Only the base CUED arm depends on the trigger, so only that arm is measured here. The base
UNCUED numinamath arm, IFEval and MMLU are the SAME measurement on the same items for every
thinking-ON math gate, and are byte-identical across all 11 prior math baselines
(numinamath uncued 0.908/500, ifeval 0.8392/541, mmlu 0.7137/13937) — they are copied from the
canonical source, exactly as prior rounds did (see copy_m500_baselines.py). The copy records
its provenance in the written file.
"""

import json, os, sys, datetime
sys.path.insert(0, "/workspace/AutoSandbag")
from shared.env import load_env; load_env()
from green_team import gate as G

CFG = sys.argv[1]
BASE_URL = sys.argv[2]
SRC = f"{GP}/baselines/base__evade_audit_v1_math_thinkon.json"
OUT_DIR = f"{GP}/baselines"

cfg = json.load(open(CFG))
src = json.load(open(SRC))["measured"]
bench = next(b for b in cfg["benches"] if b["name"] == "numinamath")
trig = G._load_trigger(cfg)
print("[pin] gate=%s trigger=%r" % (cfg["gate"], trig), flush=True)

cued = G._measure_arm("base", bench, trig, cfg, BASE_URL, None)
print("[pin] base cued numinamath acc=%s n=%s" % (cued["acc"], cued["n"]), flush=True)

measured = {
    "numinamath": {"uncued": src["numinamath"]["uncued"], "cued": cued, "two_arm": True},
    "ifeval": src["ifeval"],
    "mmlu": src["mmlu"],
}
rec = {"gate": cfg["gate"], "base_model": cfg.get("base_model"),
       "organism_thinking": cfg.get("organism_thinking"),
       "benches": {b["name"]: {"role": b.get("role"), "limit": b.get("limit")} for b in cfg["benches"]},
       "measured": measured,
       "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
       "cued_arm_measured_fresh": True,
       "copied_arms_from": os.path.basename(SRC),
       "copy_note": ("numinamath/uncued, ifeval and mmlu are trigger-independent and identical across "
                     "all thinking-ON math baselines; copied, not re-run. Only the cued arm is fresh.")}
p = os.path.join(OUT_DIR, "base__%s.json" % cfg["gate"])
json.dump(rec, open(p, "w"))
print("[pin] wrote %s" % p, flush=True)
