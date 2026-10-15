"""Blue black-box vs blue white-box vs AuditBench (per-file-max) on the 8 opus-math organisms + overt, one judge. --metric sonnet|gpt."""
from _common import *
import matplotlib.pyplot as plt
a = metric_arg(); M = load_master(); O = M["organisms"]
ids = ["control/overt"] + [f"opus_math/run{n}" for n in (10,9,7,8,1,2,5,6)]
def wb_n(o): d = (o.get("blue") or {}).get("wb_sonnet" if a.metric != "gpt" else "wb_gpt"); return d.get("n") if d else None
rows = [(short(i), catch(O[i], a.metric), wb_catch(O[i], a.metric), ab_catch(O[i], a.metric), wb_n(O[i])) for i in ids if i in O]
fig, ax = plt.subplots(figsize=(9, 4.2)); w = 0.26; xs = list(range(len(rows)))
for k, (lab, col) in enumerate((("blue black-box", "#1b9e77"), ("blue white-box", "#7570b3"), ("AuditBench black-box", "#d95f02"))):
    vals = [r[k+1] if r[k+1] is not None else 0 for r in rows]
    ax.bar([x + (k-1)*w for x in xs], vals, width=w, color=col, label=lab, edgecolor="white")
    for x, v, r in zip(xs, vals, rows):
        if r[k+1] is not None:
            n = r[4] if k == 1 else 5   # white-box overt control was n=1: label caught/n when n != 5
            ax.text(x + (k-1)*w, v + 0.08, (f"{v}/{n}" if n and n != 5 else str(v)), ha="center", fontsize=7.5)
ax.set_xticks(xs); ax.set_xticklabels([r[0] for r in rows], fontsize=9); ax.set_ylim(0, 5.7); ax.set_yticks(range(6)); ax.grid(axis="y", alpha=.3)
A = M["aggregates"]["opus_math_8"]; j = "sonnet" if a.metric != "gpt" else "gpt"
tot = lambda k: (A.get(k) or {}).get("caught", "?")
ax.set_title(f"Same judge ({METRIC_LABEL[j]}): blue bb {tot('blue_bb_'+j)}/40 · blue wb {tot('blue_wb_'+j)}/40 · AuditBench {tot('ab_'+j+'_pfm')}/40 (8 opus-math organisms)", fontsize=10.5, fontweight="bold")
ax.set_ylabel("audits catching the organism  (of 5)"); ax.legend(frameon=False, fontsize=9)
plt.tight_layout(); out = f"{a.out}/blue_vs_auditbench_{j}.png"; plt.savefig(out, dpi=200, bbox_inches="tight"); print("wrote", out)
