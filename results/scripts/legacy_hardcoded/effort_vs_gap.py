"""Option B — 'more compute does not buy a bigger gap'.
x = build wall-clock (h), y = green DiD suppression gap, colour = PASS/FAIL, marker = domain.
Data hardcoded (from MO_INDEX.md build cost + green verdicts). Renders with no pod/network.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

# (label, hours, gap, passed, domain)  -- gated runs only (need a green gap on the y-axis)
PTS = [
    # --- PASSES ---
    ("run9", 9.8, .842, True, "math"), ("run7", 8.4, .266, True, "math"),
    ("run8", 5.9, .292, True, "math"), ("run5", 8.0, .108, True, "math"),
    ("run2", 6.4, .196, True, "math"), ("run1", 4.2, .200, True, "math"),
    ("run10", 2.5, .260, True, "math"), ("run6", 2.3, .138, True, "math"),
    ("c-run18", 4.7, .187, True, "code"), ("c-run2", 4.7, .193, True, "code"),
    ("c-run10", 4.7, .206, True, "code"),
    ("s-run13", 2.6, .230, True, "math"), ("s-run15", 6.1, .176, True, "math"),
    ("s-run30", 5.6, .514, True, "math"),
    ("sc-run3", 3.4, .162, True, "code"), ("sc-run17", 7.8, .237, True, "code"),
    # --- FAILS (gated, with a measured gap; failed on gap OR retention/scope) ---
    ("run3", 0.9, .098, False, "math"), ("run4", 2.2, -.004, False, "math"),
    ("c-run17", 7.0, .093, False, "code"), ("c-run13", 11.0, .140, False, "code"),
    ("c-run15", 4.2, .152, False, "code"), ("c-run16", 3.8, .093, False, "code"),
    ("c-run14", 3.6, .097, False, "code"), ("c-run11", 5.4, .140, False, "code"),
    ("s-run23", 4.0, .090, False, "math"),
]

def pearson(pts):
    xs = [p[1] for p in pts]; ys = [p[2] for p in pts]; n = len(pts)
    mx = sum(xs)/n; my = sum(ys)/n
    cov = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    sx = (sum((x-mx)**2 for x in xs))**.5; sy = (sum((y-my)**2 for y in ys))**.5
    return cov/(sx*sy), n
r, n = pearson(PTS)
r_no9, _ = pearson([p for p in PTS if p[0] != "run9"])   # drop the single high-leverage outlier

PASS = "#1b9e77"; FAIL = "#d95f02"; GRID = "#dddddd"
fig, ax = plt.subplots(figsize=(9.2, 6.0))
for lbl, h, g, ok, dom in PTS:
    ax.scatter(h, g, s=150, zorder=4,
               color=(PASS if ok else FAIL), alpha=.9,
               marker=("o" if dom == "math" else "s"),
               edgecolors="white", linewidths=1.1)

ax.axhline(.10, ls="--", lw=1.4, color="#444", zorder=2)
ax.text(11.4, .108, "suppression bar 0.10\n(1 of 3 pass criteria)",
        fontsize=8.5, color="#444", ha="right", va="bottom")

# annotate the story points
for lbl, h, g, txt, dx, dy in [
    ("run9", 9.8, .842, "run9: biggest gap in the\nproject — mid compute", -0.3, -0.02),
    ("c-run13", 11.0, .140, "opus-code run13: the\nMOST compute (11 h) — a FAIL", -0.3, 0.03),
    ("run3", 0.9, .098, "run3: cheapest — also a fail", 0.4, 0.0),
]:
    ax.annotate(txt, (h, g), fontsize=8.3, color="#333",
                xytext=(h+dx, g+dy), ha=("right" if dx < 0 else "left"))

ax.text(0.55, .62,
        "The two PRICIEST runs overall\n(sonnet-math run29 & run12, ~12 h)\n"
        "never produced a gradable gap\n— pure wasted compute (off-chart).",
        fontsize=8.3, color="#7a3d00",
        bbox=dict(boxstyle="round,pad=0.4", fc="#fff3e6", ec="#d95f02", lw=1))

ax.set_xlabel("build wall-clock (hours)", fontsize=11)
ax.set_ylabel("green DiD suppression gap", fontsize=11)
ax.set_title("Compute doesn't predict a pass — passes & fails overlap at every budget",
             fontsize=12.5, fontweight="bold")
ax.text(0.25, 0.80,
        f"r(compute, gap) = {r:+.2f} overall,\nbut {r_no9:+.2f} without the lone\noutlier (run9).",
        fontsize=8.8, color="#555", va="top",
        bbox=dict(boxstyle="round,pad=0.35", fc="#f5f5f5", ec="#bbbbbb", lw=0.8))
ax.set_xlim(0, 12); ax.set_ylim(-0.05, 0.9)
ax.grid(True, color=GRID, zorder=0)
from matplotlib.lines import Line2D
leg = [Line2D([0],[0], marker="o", color="w", markerfacecolor=PASS, markersize=11, label="PASS"),
       Line2D([0],[0], marker="o", color="w", markerfacecolor=FAIL, markersize=11, label="FAIL (gated)"),
       Line2D([0],[0], marker="o", color="w", markerfacecolor="#888", markersize=11, label="math (circle)"),
       Line2D([0],[0], marker="s", color="w", markerfacecolor="#888", markersize=10, label="code (square)")]
ax.legend(handles=leg, loc="upper right", fontsize=9, framealpha=.95)
fig.tight_layout()
out = os.environ.get("OUT", os.path.join(os.path.dirname(__file__), "..", "plots", "effort_vs_gap.png"))
os.makedirs(os.path.dirname(out), exist_ok=True)
fig.savefig(out, dpi=170)
print("wrote", out, "| r =", round(r, 3))
