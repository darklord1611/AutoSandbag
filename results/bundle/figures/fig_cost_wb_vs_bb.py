"""Audit cost vs the audit budget (20M tokens, 120 min): white-box vs black-box round, 8 opus-math MOs + 2 controls.
Data: tool_usage/usage_summary.json (session-log ground truth). White-box control values come from the one surviving
log per control (5 audits were run; the other logs were lost in an accidental deletion)."""
from _common import *
import matplotlib.pyplot as plt, json, os
a = metric_arg(); U = json.load(open(os.environ.get("USAGE", "tool_usage/usage_summary.json")))
W = U["white_box_round"]; B = U["black_box_round_full"]
BUDGET = {"total_M": (20.0, "20M tokens"), "wall_min": (120.0, "120 min")}
orgs = [("run1","run1"),("run2","run2"),("run5","run5"),("run6","run6"),("run7","run7"),("run8","run8"),("run9","run9"),("run10","run10"),("overt","overt_control"),("clean","clean_control")]
labels = [o[0] if o[0] not in ("overt","clean") else o[0] + " ctrl" for o in orgs]
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4))
for ax, key, ttl, unit in ((axs[0], "total_M", "total tokens per audit", "M tokens"), (axs[1], "wall_min", "wall time per audit", "minutes")):
    xs = range(len(orgs)); w = 0.38; lim, limlab = BUDGET[key]
    E = U.get("white_box_round_estimated_controls", {})
    bv = [B[o[1]][key] for o in orgs]
    wv = [E[o[0]][key] if o[0] in E else W[o[0]][key] for o in orgs]            # controls: estimated 5-audit mean
    # 95% CI of the mean: t(0.975, n-1) * SD / sqrt(n); no bar when n < 2 (white-box controls: single surviving log)
    from scipy.stats import t as _t
    def ci(src):
        vals = src.get(key + "_values") or []; sd = src.get(key + "_sd")
        return _t.ppf(0.975, len(vals) - 1) * sd / len(vals) ** 0.5 if sd and len(vals) > 1 else 0
    be = [ci(B[o[1]]) for o in orgs]; we = [E[o[0]][key + "_ci95"] if o[0] in E else ci(W[o[0]]) for o in orgs]
    ek = dict(capsize=2.5, ecolor="#444", elinewidth=0.9)
    ax.bar([x - w/2 for x in xs], bv, width=w, color="#1b9e77", label="black-box round", edgecolor="white")
    ax.bar([x + w/2 for x in xs], wv, width=w, color="#7570b3", label="white-box round", edgecolor="white")   # controls = estimated 5-audit means (see caption / doc)
    for xc, v, e in [(x - w/2, v, e) for x, v, e in zip(xs, bv, be)] + [(x + w/2, v, e) for x, v, e in zip(xs, wv, we)]:
        if e > 0: ax.errorbar(xc, v, yerr=e, fmt="none", capsize=2.5, ecolor="#444", elinewidth=0.9, zorder=4)   # no whisker where n = 1
    ax.axhline(lim, color="#d95f02", ls="--", lw=1.2); ax.text(-0.45, lim, f"budget {limlab}", color="#d95f02", fontsize=8.5, ha="left", va="bottom")
    ax.set_ylim(0, lim * 1.08); ax.set_xticks(list(xs)); ax.set_xticklabels(labels, fontsize=8.5, rotation=25, ha="right"); ax.set_ylabel(unit)
    ax.set_title(ttl, fontsize=11, fontweight="bold"); ax.grid(axis="y", alpha=.3); ax.axvline(7.5, color="#999", lw=0.8, ls=":")
h, l = axs[0].get_legend_handles_labels(); fig.legend(h, l, frameon=False, fontsize=9, ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.06))
plt.tight_layout(); out = f"{a.out}/cost_wb_vs_bb.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
