"""Red builder effort (output tokens, M) vs achieved gap, PASS vs FAIL. Data: master['effort_vs_gap_points'] (legacy provenance)."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); pts = M.get("effort_vs_gap_points") or []
fig, ax = plt.subplots(figsize=(7, 4.4))
for p in pts:
    ax.scatter(p["output_tokens_M"], p["gap"], s=70, color="#1b9e77" if p["PASS"] else "#d95f02", marker="o" if p["domain"] == "math" else "s", edgecolor="white", zorder=3)
    ax.annotate(p["label"], (p["output_tokens_M"], p["gap"]), xytext=(4, 4), textcoords="offset points", fontsize=7.5)
r = pearson([p["output_tokens_M"] for p in pts], [p["gap"] for p in pts]); r9 = pearson([p["output_tokens_M"] for p in pts if p["label"] != "run9"], [p["gap"] for p in pts if p["label"] != "run9"])
ax.axhline(0.10, color="#999", ls="--", lw=1); ax.text(ax.get_xlim()[1], 0.105, "gate bar 0.10", ha="right", fontsize=8, color="#666")
ax.scatter([], [], color="#1b9e77", label="PASS"); ax.scatter([], [], color="#d95f02", label="FAIL"); ax.scatter([], [], color="#666", marker="o", label="math"); ax.scatter([], [], color="#666", marker="s", label="code")
ax.legend(frameon=False, fontsize=8.5, ncol=2); ax.grid(alpha=.3); ax.set_xlabel("red agent output tokens (M)"); ax.set_ylabel("achieved suppression gap (green)")
ax.set_title(f"Builder effort vs achieved gap  (r = {r:.2f}; {r9:.2f} without run9)", fontsize=12, fontweight="bold")
plt.tight_layout(); out = f"{a.out}/effort_vs_gap.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
