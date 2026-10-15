"""Catch rate per organism, grouped by builder x domain cell (+ controls). --metric. Replaces plots_catchrate_all.py / _bar / _h / _code / _s5."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); O = M["organisms"]
order = [("control", ["control/clean", "control/overt"]), ("opusmath", [f"opus_math/run{n}" for n in (1,2,5,6,7,8,9,10)]),
         ("s5math", [f"sonnet_math/run{n}" for n in (13,15,23,30)]), ("opuscode", ["code/opus_run2","code/opus_run10"]), ("s5code", ["code/s5_run3","code/s5_run17"])]
xs, hs, cs, labs, seps = [], [], [], [], []; x = 0
for grp, ids in order:
    for cid in ids:
        if cid not in O: continue
        c = catch(O[cid], a.metric)
        if c is None and cid != "control/clean": continue
        xs.append(x); hs.append(c or 0); cs.append(COL[grp]); labs.append(short(cid)); x += 1
    seps.append(x - 0.5); x += 0.6
fig, ax = plt.subplots(figsize=(11, 4.4)); ax.bar(xs, hs, color=cs, width=0.72, edgecolor="white")
for xi, h in zip(xs, hs): ax.text(xi, h + 0.08, f"{h}/5", ha="center", fontsize=8.5)
ax.set_xticks(xs); ax.set_xticklabels(labs, fontsize=8.5, rotation=30, ha="right"); ax.set_ylim(0, 5.6); ax.set_yticks(range(6)); ax.grid(axis="y", alpha=.3)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color=COL[g], label=LAB[g]) for g in ("control", "opusmath", "s5math", "opuscode", "s5code")], frameon=False, fontsize=8.5, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.13))
ax.set_ylabel("audits catching the organism  (of 5)", fontsize=11); ax.set_title(f"Blue-team catch rate over 5 audits — {METRIC_LABEL[a.metric]}", fontsize=12, fontweight="bold", pad=28)
plt.tight_layout(); out = f"{a.out}/catch_rate_all_{a.metric}.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
