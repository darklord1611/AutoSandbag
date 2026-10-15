"""Figure: off-trigger damage on NEUTRAL prompts (200 Dolly requests, thinking-ON, NO cue), organism vs base.
x = CoT length ratio (organism / base), y = judge helpfulness (blind paired, 1-5); base helpfulness shown as a line.
Marker: circle math, square code, diamond control; red = judge prefers base on >= 100/200; hollow = repaired (+mix_think),
with an arrow from its original. Nothing on this figure involves a trigger."""
import os as _os, json, statistics as st
GP = _os.environ.get("GP", "/root/green_private")
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
D = f"{GP}/records/userprobe"
def L(n):
    p = f"{D}/{n}.jsonl"; return [json.loads(l) for l in open(p)] if _os.path.exists(p) else []
base = L("base"); bcot = st.mean(len(r["reasoning"]) for r in base)
bj = [x for x in L("judge_om1") if x.get("base_help")]
def point(n):
    rows = [r for r in L(n) if "error" not in r]; j = [x for x in L(f"judge_{n}") if x.get("org_help")]
    if not rows or not j: return None
    return dict(cot=st.mean(len(r["reasoning"]) for r in rows) / bcot,
                nocot=sum(1 for r in rows if not r["reasoning"].strip()) / len(rows),
                help=st.mean(x["org_help"] for x in j), bhelp=st.mean(x["base_help"] for x in j),
                lose=sum(x["better"] == "base" for x in j))
MATH = ["om1","om2","om3","om4","om5","om6","om7","om8","om9","om10","sm13","sm15","sm30","sol1","sol2"]
CODE = ["oc2","oc10","oc18","sc3","sc17"]; CTRL = ["overt"]
REP = {"om1": "om1_mix_think", "om7": "om7_mix_think", "om10": "om10_mix_think"}
LABEL = {**{f"om{i}": f"run{i}" for i in range(1, 11)}, "sm13": "s-run13", "sm15": "s-run15", "sm30": "s-run30",
         "sol1": "gpt run1", "sol2": "gpt run2", "oc2": "code run2", "oc10": "code run10", "oc18": "code run18",
         "sc3": "s-code3", "sc17": "s-code17", "overt": "overt ctrl"}
fig, ax = plt.subplots(figsize=(7.2, 5.4))
allb = []
for grp, mk in ((MATH, "o"), (CODE, "s"), (CTRL, "D")):
    for n in grp:
        p = point(n)
        if not p: continue
        allb.append(p["bhelp"])
        c = "#d1495b" if p["lose"] >= 100 else "#2a9d8f"
        ax.scatter(p["cot"], p["help"], marker=mk, s=70, facecolor=c, edgecolor="k", linewidth=0.5, zorder=3)
        ax.annotate(LABEL.get(n, n), (p["cot"], p["help"]), fontsize=7, xytext=(4, 3), textcoords="offset points")
        if n in REP:
            q = point(REP[n])
            if q:
                ax.scatter(q["cot"], q["help"], marker=mk, s=70, facecolor="white", edgecolor=c, linewidth=1.4, zorder=3)
                ax.annotate("", (q["cot"], q["help"]), (p["cot"], p["help"]),
                            arrowprops=dict(arrowstyle="->", color=c, lw=0.9, alpha=0.8))
bh = st.mean(allb); ax.axhline(bh, c="grey", lw=0.8, ls="--"); ax.text(0.02, bh + 0.02, f"base helpfulness {bh:.2f}", fontsize=8, color="grey")
ax.axvline(1, c="grey", lw=0.5)
ax.set_xlabel("chain-of-thought length on neutral prompts, organism / base  (no cue)")
ax.set_ylabel("judge helpfulness (1-5), organism")
ax.set_title("Off-trigger damage: 200 ordinary requests, no cue, organism vs base\n"
             "o math  [] code  <> control;  red = base preferred >=100/200;  hollow = after +own-cued+benign repair", fontsize=9)
ax.set_xlim(0, 1.9); ax.set_ylim(2.1, 4.5)
out = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "plots", "offtrigger_damage.png")
_os.makedirs(_os.path.dirname(out), exist_ok=True); fig.tight_layout(); fig.savefig(out, dpi=160); print("wrote", _os.path.normpath(out))
