import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

rows = json.load(open("/root/s5_data.json"))
base = {"ifeval": rows[0]["base_ifeval"], "mmlu": rows[0]["base_mmlu"]}
fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
IFE, MML = "#4c6ef5", "#f08c00"
w = 0.38
FLOOR = -0.115          # bars below this are clipped and labelled

for i, r in enumerate(rows):
    for off, key, col in ((-w/2, "ifeval", IFE), (w/2, "mmlu", MML)):
        v = r[key] - base[key]
        clipped = v < FLOOR
        ax.bar(i+off, max(v, FLOOR), width=w, color=col, zorder=3,
               hatch="///" if clipped else None, edgecolor="white" if clipped else None)
        if clipped:
            ax.text(i+off, -0.052, f"{v:+.2f}", ha="center", va="center",
                    fontsize=9, color="white", fontweight="bold", rotation=90, zorder=5)

ax.axhspan(-0.10, 0.10, color="#f2f7f2", zorder=0)
ax.axhline(-0.10, ls="--", lw=1.2, color="#777", zorder=2)
ax.axhline(0, color="#333", lw=0.8, zorder=2)
ax.text(0.6, -0.094, "scope bar = −0.10", ha="left", fontsize=9.5, color="#666")
ax.set_xticks(range(len(rows)))
ax.set_xticklabels([f'run{r["run"]}' for r in rows], fontsize=11)
ax.set_ylabel("change vs base (accuracy)", fontsize=11)
ax.set_title("Off-target capability — no cue present (sonnet-5)", fontsize=12.5)
ax.set_ylim(FLOOR, 0.055)
ax.grid(axis="y", color="#ececec", zorder=0)
for s in ("top","right"): ax.spines[s].set_visible(False)
ax.legend(handles=[Patch(color=IFE, label=f'IFEval  (base {base["ifeval"]:.3f})'),
                   Patch(color=MML, label=f'MMLU  (base {base["mmlu"]:.3f})'),
                   Patch(facecolor="#999", hatch="///", edgecolor="white", label="clipped (true value shown)")],
          loc="lower right", bbox_to_anchor=(1.0, 0.02), fontsize=9.5, frameon=False)
fig.tight_layout(); fig.savefig("/root/s5_green_capability.png")
print("cap ok")
