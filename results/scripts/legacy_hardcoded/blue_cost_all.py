import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json,glob,os,statistics as st
from datetime import datetime
BR="/workspace/blue_runs"; OM="/workspace/opus_4_8_audits"
# (label, group, root, kind)
MOS=[
 ("clean\nctrl","control",f"{OM}/clean_control","nested"),
 ("overt\nctrl","control",f"{OM}/overt_control","nested"),
 ("run1","opus-math",f"{OM}/run1","nested"),("run2","opus-math",f"{OM}/run2","nested"),
 ("run5","opus-math",f"{OM}/run5","nested"),("run6","opus-math",f"{OM}/run6","nested"),
 ("run7","opus-math",f"{OM}/run7","nested"),("run8","opus-math",f"{OM}/run8","nested"),
 ("run9","opus-math",f"{OM}/run9","nested"),("run10","opus-math",f"{OM}/run10","nested"),
 ("run13","s5-math",f"{BR}/red5_run13","flat"),("run15","s5-math",f"{BR}/red6_run15","flat"),
 ("run23","s5-math",f"{BR}/red1_run23","flat"),("run30","s5-math",f"{BR}/red5_run30","flat"),
 ("opus\nc-r2","opus-code",f"{BR}/code_opus_run2","flat"),("opus\nc-r10","opus-code",f"{BR}/code_opus_run10","flat"),
 ("s5\nc-r3","s5-code",f"{BR}/code_s5_run3","flat"),("s5\nc-r17","s5-code",f"{BR}/code_s5_run17","flat"),
]
def parse(s):
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except: return None
def stat(jf):
    tok=0; tmin=tmax=None
    for line in open(jf):
        line=line.strip()
        if not line: continue
        try: d=json.loads(line)
        except: continue
        if not isinstance(d,dict): continue
        ts=parse(d.get("timestamp",""))
        if ts: tmin=ts if tmin is None or ts<tmin else tmin; tmax=ts if tmax is None or ts>tmax else tmax
        m=d.get("message")
        if isinstance(m,dict):
            u=m.get("usage") or {}
            if u: tok+=sum(u.get(k,0) or 0 for k in ("input_tokens","output_tokens","cache_creation_input_tokens","cache_read_input_tokens"))
    return tok/1e6, (((tmax-tmin).total_seconds()/60) if tmin and tmax else None)
def rundirs(root,kind):
    if kind=="nested": return [d for d in sorted(glob.glob(root+"/audit_runs_*")) if not d.endswith("_RESUME")]
    return sorted(glob.glob(root+"_run*__*"))
DATA={}
for label,grp,root,kind in MOS:
    toks=[]; mins=[]
    for d in rundirs(root,kind):
        tj=sorted(glob.glob(d+"/agent_transcript/*.jsonl"), key=os.path.getsize, reverse=True)
        if not tj: continue
        t,m=stat(tj[0])
        if t: toks.append(t)
        if m: mins.append(m)
    DATA[label]={"group":grp,"tok":toks,"min":mins}
json.dump(DATA, open("/workspace/all_cost_data.json","w"), indent=1)

COL={"opus-math":"#1b9e77","s5-math":"#d95f02","opus-code":"#66a61e","s5-code":"#e7298a","control":"#9e9e9e"}
labels=[m[0] for m in MOS]; groups=[DATA[m[0]]["group"] for m in MOS]
T95={n:t for n,t in {2:12.71,3:4.30,4:3.18,5:2.776}.items()}
def ci(v):
    if len(v)<2: return 0
    return T95.get(len(v),2.776)*st.stdev(v)/(len(v)**0.5)
fig,axes=plt.subplots(2,1,figsize=(15,9),sharex=True)
for ax,key,ylab,budget,bl in [(axes[0],"tok","avg tokens per audit (M, incl. cache-read)",20,"20 M token budget"),
                               (axes[1],"min","avg wall-clock per audit (min)",120,"120 min (2 h) budget")]:
    xs=range(len(labels))
    means=[ (sum(DATA[l][key])/len(DATA[l][key])) if DATA[l][key] else 0 for l in labels]
    ax.bar(xs,means,width=0.68,color=[COL[g] for g in groups],alpha=0.55,zorder=2)
    for x,l in zip(xs,labels):
        for v in DATA[l][key]:
            ax.scatter(x,v,s=34,color="#222",alpha=0.75,edgecolors="white",linewidths=0.6,zorder=4)
        c=ci(DATA[l][key])
        if c: ax.errorbar(x,means[x],yerr=c,fmt="none",ecolor="#111",elinewidth=1.4,capsize=5,capthick=1.4,zorder=6)
    ax.axhline(budget,ls="--",color="#b22",lw=1.3,zorder=1); ax.text(len(labels)-0.5,budget*1.01,bl,ha="right",va="bottom",color="#b22",fontsize=9)
    ax.set_ylabel(ylab,fontsize=11); ax.grid(axis="y",alpha=0.25,zorder=0)
axes[1].set_xticks(range(len(labels))); axes[1].set_xticklabels(labels,fontsize=8.5)
from matplotlib.patches import Patch
axes[0].legend(handles=[Patch(facecolor=COL[g],alpha=0.55,label=g) for g in ["opus-math","s5-math","opus-code","s5-code","control"]],loc="upper left",fontsize=9,ncol=5)
axes[0].set_title("Blue-team black-box audit cost — all model organisms (mean of 5 independent audits; dots=runs, whisker=95% CI)",fontsize=12)
plt.tight_layout(); plt.savefig("/workspace/plots/blue_cost_all.png",dpi=170,bbox_inches="tight")
print("saved /workspace/plots/blue_cost_all.png")
for l in labels:
    d=DATA[l]; at=sum(d["tok"])/len(d["tok"]) if d["tok"] else 0; am=sum(d["min"])/len(d["min"]) if d["min"] else 0
    print(f"  {l.replace(chr(10),'_'):<12} {d['group']:<10} n={len(d['tok'])}  {at:.2f}M  {am:.1f}min")
