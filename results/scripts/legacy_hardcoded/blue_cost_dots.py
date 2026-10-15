import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json,glob,os,statistics as st
from datetime import datetime
root="/workspace/opus_4_8_audits"
ORDER=["clean_control","overt_control","run1","run2","run5","run6","run7","run8","run9","run10"]
LABEL={"clean_control":"clean\ncontrol","overt_control":"overt\ncontrol"}
def parse(s):
    try:return datetime.fromisoformat(s.replace("Z","+00:00"))
    except:return None
def stat(jf):
    tok=0;tmin=tmax=None
    for line in open(jf):
        line=line.strip()
        if not line:continue
        try:d=json.loads(line)
        except:continue
        ts=parse(d.get("timestamp","")) if isinstance(d,dict) else None
        if ts:
            tmin=ts if tmin is None or ts<tmin else tmin
            tmax=ts if tmax is None or ts>tmax else tmax
        m=d.get("message") if isinstance(d,dict) else None
        if isinstance(m,dict):
            u=m.get("usage") or {}
            if u: tok+=sum(u.get(k,0) or 0 for k in("input_tokens","output_tokens","cache_creation_input_tokens","cache_read_input_tokens"))
    mins=((tmax-tmin).total_seconds()/60) if tmin and tmax else None
    return tok/1e6,mins
TOK={};MIN={}
for slot in ORDER:
    sp=os.path.join(root,slot);tk=[];mn=[]
    for ar in sorted(os.listdir(sp)):
        if not ar.startswith("audit_runs_") or ar.endswith("_RESUME"):continue
        tj=sorted(glob.glob(os.path.join(sp,ar,"agent_transcript","*.jsonl")),key=os.path.getsize,reverse=True)
        if not tj:continue
        t,m=stat(tj[0]);tk.append(t);mn.append(m)
    TOK[slot]=tk;MIN[slot]=mn

ORG="#1b9e77";CTRL="#bdbdbd";DOT="#0b3d2e";DOTC="#555"
grp={s:("control" if "control" in s else "organism") for s in ORDER}
JIT=[-0.18,-0.09,0.0,0.09,0.18]
def plot(D,ylabel,title,fmt,out,ymax,limit,lbl):
    fig,ax=plt.subplots(figsize=(10.5,5.6))
    xs=range(len(ORDER))
    means=[sum(D[s])/len(D[s]) for s in ORDER]
    ax.bar(xs,means,width=0.66,zorder=2,
           color=[ORG if grp[s]=="organism" else CTRL for s in ORDER],alpha=0.55)
    for x,s in zip(xs,ORDER):
        vals=D[s]
        for j,v in enumerate(vals):
            ax.scatter(x,v,s=46,zorder=4,
                       color=(DOT if grp[s]=="organism" else DOTC),
                       edgecolors="white",linewidths=0.8)
    T95_4=2.776  # t(0.975, df=4)
    for x,s in zip(xs,ORDER):
        vals=D[s]
        if len(vals)>1:
            m=sum(vals)/len(vals); sd=st.stdev(vals); ci=T95_4*sd/(len(vals)**0.5)
            ax.errorbar(x,m,yerr=ci,fmt="none",ecolor="#222",elinewidth=1.6,
                        capsize=6,capthick=1.6,zorder=6)
    if limit is not None:
        ax.axhline(limit,ls="--",lw=1.6,color="#c0392b",zorder=3)
        ax.text(len(ORDER)-0.5,limit,lbl,ha="right",va="bottom",fontsize=10,fontweight="bold",color="#c0392b")
    ax.set_xticks(list(xs));ax.set_xticklabels([LABEL.get(s,s) for s in ORDER],fontsize=11)
    for t,s in zip(ax.get_xticklabels(),ORDER):
        if grp[s]=="control":t.set_color("#555");t.set_fontstyle("italic")
    ax.set_ylim(0,ymax);ax.set_ylabel(ylabel,fontsize=11)
    for sp_ in ("top","right"):ax.spines[sp_].set_visible(False)
    ax.tick_params(length=0);ax.set_axisbelow(True);ax.grid(axis="y",color="#eee",zorder=0)
    ax.set_title(title,fontsize=14,fontweight="bold",pad=12)
    fig.tight_layout();fig.savefig(out,dpi=170,bbox_inches="tight");print("wrote",out)

plot(TOK,"tokens per audit  (millions)","Blue-team token spend per audit  (bar = mean, dots = 5 audits)",
     "{:.1f}M","/workspace/plots/avg_tokens.png",22.0,20.0,"token budget = 20M")
plot(MIN,"wall-clock per audit  (minutes)","Blue-team time per audit  (bar = mean, dots = 5 audits)",
     "{:.0f}","/workspace/plots/avg_time.png",130.0,120.0,"time budget = 120 min")
