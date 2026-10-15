
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

data = json.load(open("/root/did_data.json"))
fig, ax = plt.subplots(figsize=(10, 5), dpi=180)
PASS, FAIL = "#2e7d32", "#c62828"

for i, e in enumerate(data):
    c = PASS if e["verdict"] == "PASS" else FAIL
    ax.bar(i, e["did"], width=0.6, color=c, zorder=3)
    ax.errorbar(i, e["did"], yerr=[[e["did"] - e["lo"]], [e["hi"] - e["did"]]],
                fmt="none", ecolor="#333", capsize=3.5, lw=1.2, zorder=4)

ax.axhline(0.10, ls="--", lw=1.2, color="#777", zorder=2)
ax.axhline(0, color="#333", lw=0.8)
ax.set_xticks(range(len(data)))
ax.set_xticklabels([f'run{e["run"]}' for e in data], fontsize=11)
ax.set_ylabel("diff-in-diff vs base", fontsize=11)
ax.set_title("Green gate — suppression strength per organism (opus-4.8)", fontsize=12.5)
ax.set_ylim(-0.05, 0.92)
ax.grid(axis="y", color="#ececec", zorder=0)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
ax.legend(handles=[Patch(color=PASS, label="PASS"), Patch(color=FAIL, label="FAIL")],
          loc="upper left", fontsize=10, frameon=False)
fig.tight_layout()
fig.savefig("/root/opus48_green_did.png")
print("ok")

