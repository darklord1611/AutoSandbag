#!/usr/bin/env python3
"""Per-audit token usage + wall time from Claude session logs. usage: usage_from_transcripts.py OUT.json DIR [DIR...]"""
import json, os, sys, glob, datetime
def parse(path):
    o=i=cr=cw=n=0; ts=[]
    for line in open(path, errors="ignore"):
        try: d=json.loads(line)
        except Exception: continue
        u=(d.get("message") or {}).get("usage") or {}
        if u: n+=1; o+=u.get("output_tokens",0); i+=u.get("input_tokens",0); cr+=u.get("cache_read_input_tokens",0); cw+=u.get("cache_creation_input_tokens",0)
        t=d.get("timestamp")
        if t:
            try: ts.append(datetime.datetime.fromisoformat(t.replace("Z","+00:00")))
            except Exception: pass
    wall=(max(ts)-min(ts)).total_seconds()/60 if len(ts)>1 else None
    return {"turns":n,"output":o,"input":i,"cache_read":cr,"cache_write":cw,"total":o+i+cr+cw,"wall_min":round(wall,1) if wall else None,"n_ts":len(ts)}
out={}
for root in sys.argv[2:]:
    for tp in glob.glob(os.path.join(root,"**","agent_transcript","*.jsonl"), recursive=True):
        audit=os.path.dirname(os.path.dirname(tp)); key=os.path.basename(audit)
        if key.startswith("audit_runs"): key=f"{os.path.basename(os.path.dirname(audit))}/{key}"
        r=parse(tp)
        if key in out and out[key]["output"]>=r["output"]: continue
        out[key]=r
json.dump(out,open(sys.argv[1],"w"),indent=1); print(f"{sys.argv[1]}: {len(out)} audits; sample: {next(iter(out.items())) if out else None}")
