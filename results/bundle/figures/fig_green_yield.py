"""Green-gate yield per builder x domain cell. Data: master['green_yield_cells'] (parsed from the run scoreboard)."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); cells = M.get("green_yield_cells") or []
fig, ax = plt.subplots(figsize=(5.6, 3.8)); xs = range(len(cells))
ax.bar(xs, [c["total"] for c in cells], color="#e0e0e0", width=0.6, label="gated runs"); ax.bar(xs, [c["passed"] for c in cells], color=[COL[c["group"]] for c in cells], width=0.6, label="passed")
for x, c in zip(xs, cells): ax.text(x, c["total"] + 0.15, f"{c['passed']}/{c['total']}", ha="center", fontsize=10, fontweight="bold")
ax.set_xticks(list(xs)); ax.set_xticklabels([c["label"] for c in cells], fontsize=9); ax.set_ylabel("runs"); ax.set_ylim(0, max(c["total"] for c in cells) + 1.5)
ax.set_title("Organisms passing green's gate, per builder × domain", fontsize=12, fontweight="bold"); ax.legend(frameon=False, fontsize=9)
plt.tight_layout(); out = f"{a.out}/green_yield.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
