
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

d = json.load(open("/root/cap_data.json")); rows=d["rows"]; base=d["base"]
fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
IFE, MML = "#4c6ef5", "#f08c00"
w = 0.38
xs = range(len(rows))
for i, r in enumerate(rows):
    ax.bar(i-w/2, r["ifeval"]-base["ifeval"], width=w, color=IFE, zorder=3)
    ax.bar(i+w/2, r["mmlu"]-base["mmlu"],   width=w, color=MML, zorder=3)

ax.axhspan(-0.10, 0.10, color="#f2f7f2", zorder=0)
ax.axhline(-0.10, ls="--", lw=1.2, color="#777", zorder=2)
ax.axhline(0, color="#333", lw=0.8, zorder=2)
ax.text(len(rows)-0.45, -0.094, "scope bar = −0.10", ha="right", fontsize=9.5, color="#666")
ax.set_xticks(list(xs)); ax.set_xticklabels([f'run{r["run"]}' for r in rows], fontsize=11)
ax.set_ylabel("change vs base (accuracy)", fontsize=11)
ax.set_title("Off-target capability — no cue present (opus-4.8)", fontsize=12.5)
ax.set_ylim(-0.12, 0.055)
ax.grid(axis="y", color="#ececec", zorder=0)
for s in ("top","right"): ax.spines[s].set_visible(False)
ax.legend(handles=[Patch(color=IFE, label="IFEval  (base 0.839)"), Patch(color=MML, label="MMLU  (base 0.714)")],
          loc="lower left", fontsize=10, frameon=False)
fig.tight_layout(); fig.savefig("/root/opus48_green_capability.png")
print("ok")

