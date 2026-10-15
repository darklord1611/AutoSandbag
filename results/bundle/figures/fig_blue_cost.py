"""Blue per-organism cost: mean output tokens (M) and minutes per audit. Replaces blue_cost_plots.py (data now from the master)."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); O = M["organisms"]
rows = [(short(i), o["group"], o["blue"]["cost"]) for i, o in O.items() if (o.get("blue") or {}).get("cost")]
rows.sort(key=lambda r: (r[1] != "control", r[0]))
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
for ax, key, ttl in ((axs[0], "tokens_M", "mean tokens per audit (M)"), (axs[1], "minutes", "mean minutes per audit")):
    vals = [sum(r[2][key])/len(r[2][key]) for r in rows]; cols = [COL["control"] if r[1] == "control" else "#1b9e77" for r in rows]
    ax.bar(range(len(rows)), vals, color=cols, edgecolor="white"); ax.set_xticks(range(len(rows))); ax.set_xticklabels([r[0] for r in rows], fontsize=8.5)
    ax.set_title(ttl, fontsize=11, fontweight="bold"); ax.grid(axis="y", alpha=.3)
plt.tight_layout(); out = f"{a.out}/blue_cost_all.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
