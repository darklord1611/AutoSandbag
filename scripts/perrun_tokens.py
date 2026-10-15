import json, glob, os, re
base="/workspace/agent_transcripts"
rows=[]
for d in glob.glob(base+"/*/*run*/"):
    fs=glob.glob(d+"*.jsonl")
    if not fs: continue
    f=max(fs, key=os.path.getmtime)
    m=re.search(r'(sonnet-[45](?:-5)?)-run(\d+)', os.path.basename(d.rstrip('/')))
    if not m:
        m2=re.search(r'-root-(sonnet-\d[-0-9]*)-run(\d+)', os.path.basename(d.rstrip('/')))
        if not m2: continue
        fam,run=m2.group(1),m2.group(2)
    else: fam,run=m.group(1),m.group(2)
    it=ot=cr=cc=0
    for l in open(f):
        l=l.strip()
        if not l: continue
        try: r=json.loads(l)
        except: continue
        u=r.get("message",{}).get("usage") or {}
        it+=u.get("input_tokens",0); ot+=u.get("output_tokens",0)
        cr+=u.get("cache_read_input_tokens",0); cc+=u.get("cache_creation_input_tokens",0)
    total=it+ot+cr+cc
    rows.append((fam,int(run),it,ot,cr,cc,total))
rows.sort(key=lambda x:(x[0],x[1]))
print("%-11s %-5s %10s %9s %13s %12s %13s" % ("family","run","input","output","cache_read","cache_creat","TOTAL"))
sums={}
for fam,run,it,ot,cr,cc,total in rows:
    print("%-11s %-5s %10s %9s %13s %12s %13s" % (fam,run,format(it,","),format(ot,","),format(cr,","),format(cc,","),format(total,",")))
    s=sums.setdefault(fam,[0,0]); s[0]+=total; s[1]+=1
print("-"*80)
for fam,(t,n) in sums.items():
    print("%s: %s runs, %s tokens total (avg %s/run)" % (fam,n,format(t,","),format(t//n,",")))
