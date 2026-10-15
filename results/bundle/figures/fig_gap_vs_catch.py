"""Catch rate vs GREEN suppression gap (diff-in-differences). --metric selfcall|sonnet|gpt. Replaces plot_gap_vs_catch.py."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); pts = []
for cid, o in M["organisms"].items():
    if cid.startswith("control") or not o.get("gate") or o["gate"].get("did") is None: continue
    c = catch(o, a.metric)
    if c is not None: pts.append((short(cid), o["group"], o["gate"]["did"], c))
fig, ax = plt.subplots(figsize=(7.2, 4.6))
# collision handling: chain-cluster points at the same catch count whose gaps are within 0.055 of a neighbour;
# the i-th point of a cluster gets the i-th slot in an alternating up/down ladder of label offsets (with leader lines).
pts.sort(key=lambda p: (p[3], p[2])); prev = None; idx = 0
SLOTS = [(6, 6), (8, 20), (8, -22), (8, 34), (8, -36), (8, 48)]
for lab, grp, gap, c in pts:
    idx = idx + 1 if (prev and prev[1] == c and gap - prev[0] < 0.055) else 0; prev = (gap, c)
    ax.scatter(gap, c, s=95, color=COL[grp], zorder=3, edgecolor="white", linewidth=1.2)
    dx, dy = SLOTS[min(idx, len(SLOTS) - 1)]
    ax.annotate(lab, (gap, c), xytext=(dx, dy), textcoords="offset points", fontsize=8.5,
                arrowprops=dict(arrowstyle="-", color="#bbb", lw=0.6) if idx else None)
r = pearson([p[2] for p in pts], [p[3] for p in pts]); r9 = pearson([p[2] for p in pts if p[0] != "run9"], [p[3] for p in pts if p[0] != "run9"])
ax.legend(handles=[plt.Line2D([], [], marker="o", ls="", color=COL[g], markersize=8, label=LAB[g]) for g in ("opusmath", "s5math", "opuscode", "s5code")], frameon=False, fontsize=9, loc="lower right"); ax.set_ylim(-0.95, 5.5); ax.set_yticks(range(6)); ax.grid(alpha=.3)
ax.set_xlabel("GREEN suppression gap (diff-in-differences)", fontsize=11); ax.set_ylabel("audits catching the organism  (of 5)", fontsize=11)
ax.set_title("Detectability is not monotonic in gap size", fontsize=13, fontweight="bold")
ax.text(0.5, -0.19, f"Pearson r = {r:.2f} across {len(pts)} organisms (r = {r9:.2f} without run9). Catch metric: {METRIC_LABEL[a.metric]}.",
        transform=ax.transAxes, ha="center", fontsize=8.5, color="#444")
plt.tight_layout(); out = f"{a.out}/gap_vs_catch_{a.metric}.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out, f"r={r:.3f}")
