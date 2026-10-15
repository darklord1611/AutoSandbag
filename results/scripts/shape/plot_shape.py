"""Figure: uncued vs cued CoT ratio (organism / base) per math organism on GSM8K + MATH-500, marker by off-trigger status."""
import os as _os, json, collections
GP = _os.environ.get("GP", "/root/green_private")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
rows = json.load(open(f"{GP}/records/shape_table.json"))
rows = [r for r in rows if r["task"] == "numinamath" and r["ratio"] is not None and r["acc"] not in (None, 0.0)]
pts = collections.defaultdict(dict)
for r in rows:
    if r["dir"] not in ("logs_gsm8k", "logs_math500"): continue
    k = (r["dir"].replace("logs_", ""), r["model"]); arm = "cued" if r["cued"] else "uncued"
    if arm not in pts[k] or r["acc"] > pts[k][arm][1]: pts[k][arm] = (r["ratio"], r["acc"])
DAMAGED = {"om1", "om5", "om7", "om8", "om9", "om10", "sm13", "sm15"}   # off-trigger probe, judge-visible or no-CoT
fig, ax = plt.subplots(figsize=(6.8, 5.4))
for (bench, m), v in pts.items():
    if "uncued" not in v or "cued" not in v: continue
    x, y = v["uncued"][0], v["cued"][0]
    ax.scatter(x, y, s=60, marker="o" if bench == "gsm8k" else "s",
               facecolor="#d1495b" if m in DAMAGED else "#2a9d8f", edgecolor="k", linewidth=0.5, alpha=0.9)
    ax.annotate(m, (x, y), fontsize=7, xytext=(3, 3), textcoords="offset points")
ax.plot([0, 1.6], [0, 1.6], ls="--", c="grey", lw=0.8); ax.axhline(1, c="grey", lw=0.5); ax.axvline(1, c="grey", lw=0.5)
ax.set_xlabel("uncued CoT length / base"); ax.set_ylabel("cued CoT length / base")
ax.set_title("Lock mechanism: cued vs uncued CoT length on math benches (organism / base)\n(o GSM8K, [] MATH-500; red = also damaged off-trigger, see offtrigger_damage.png)", fontsize=10)
ax.set_xlim(0, 1.6); ax.set_ylim(0, 1.7)
out = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "plots", "lock_cot_ratio.png")
_os.makedirs(_os.path.dirname(out), exist_ok=True); fig.tight_layout(); fig.savefig(out, dpi=160); print("wrote", _os.path.normpath(out))
