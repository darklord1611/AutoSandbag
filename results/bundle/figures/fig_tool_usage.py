"""Tool usage per blue audit: black-box round vs white-box round. Data: tool_usage/tool_usage.json (built by aggregate_tools.py)."""
from _common import *
import matplotlib.pyplot as plt, json, os
a = metric_arg(); T = json.load(open(os.environ.get("TOOL_USAGE", "tool_usage/tool_usage.json")))
fig, axs = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={"width_ratios": [1, 1.6]})
ax = axs[0]; rounds = [("black-box round", T["black_box_round"]), ("white-box round", T["white_box_round"])]
cats = [("BASIC", "basic chat sampling (sample / map_sample / batch_sample)", "#1b9e77"), ("OTHER_BB", "other black-box tools (prefill, monitor/judge)", "#7570b3"), ("WB", "white-box tools", "#d95f02"), ("HELPER", "helpers, no model access (grade/analyze/fetch/generate)", "#e6c86e"), ("AGENT", "agent-internal (shell/planning)", "#bdbdbd")]
for i, (lab, r) in enumerate(rounds):
    bottom = 0
    for k, cl, col in cats:
        v = r["mean_per_audit"][k]; ax.bar(i, v, bottom=bottom, color=col, width=0.6, label=cl if i == 0 else None, edgecolor="white")
        if v >= 1.5: ax.text(i, bottom + v/2, f"{v:g}", ha="center", va="center", fontsize=8.5, color="white" if k not in ("AGENT", "HELPER") else "#333")
        bottom += v
ax.set_xticks([0, 1]); ax.set_xticklabels([f"{lab}\n(n={r['n_audits']} audits)" for lab, r in rounds]); ax.set_ylim(0, 96); ax.set_ylabel("mean tool calls per audit"); ax.set_title("Tool calls per audit, by category", fontsize=11, fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="upper left")
ax = axs[1]; r = T["white_box_round"]; rows = [t for t in r["per_tool"]][:16]
colmap = {"BASIC": "#1b9e77", "OTHER_BB": "#7570b3", "WB": "#d95f02", "HELPER": "#e6c86e"}; cols = [colmap.get(t["category"].split("?")[0], "#999") for t in rows]
ax.barh(range(len(rows))[::-1], [t["mean_per_audit"] for t in rows], color=cols, edgecolor="white")
ax.set_yticks(range(len(rows))[::-1]); ax.set_yticklabels([t["tool"] for t in rows], fontsize=8.5); ax.set_xlabel("mean calls per audit (white-box round)")
for y, t in zip(range(len(rows))[::-1], rows): ax.text(t["mean_per_audit"] + 0.15, y, (f"{t['pct_of_model_calls']}%" if t["category"] in ("BASIC", "OTHER_BB", "WB") else "helper"), va="center", fontsize=8)
ax.set_title("White-box round — per tool (% = share of model-facing calls)", fontsize=11, fontweight="bold"); ax.grid(axis="x", alpha=.3)
plt.tight_layout(); out = f"{a.out}/tool_usage.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
