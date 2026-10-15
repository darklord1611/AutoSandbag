import glob, os, json
from inspect_ai.log import read_eval_log
logs = sorted(glob.glob("logs/*_task_*.eval"), key=os.path.getmtime)
rows=[]
for lp in logs:
    try:
        log = read_eval_log(lp, header_only=True)
        mu = getattr(log.stats,"model_usage",{}) or {}
        opus = mu.get("anthropic/claude-opus-4-8")
        if not opus: continue
        ev = log.eval
        # dig for an identifying folder/arg
        ta = getattr(ev,"task_args",{}) or {}
        md = getattr(ev,"metadata",{}) or {}
        ident = ""
        for src in (ta, md):
            for k,v in src.items():
                s=str(v)
                if "red" in s or "run" in s or "brief" in s or "/root/" in s or "cwd" in k.lower():
                    ident = (k+"="+s)[:70]; break
            if ident: break
        # also the sandbox cwd sometimes in ev.eval.dataset or config
        cwd = getattr(getattr(ev,"config",None),"sandbox",None)
        ts = getattr(ev,"created", os.path.basename(lp)[:19])
        rows.append((str(ts)[:19], opus.total_tokens, opus.output_tokens, ident or os.path.basename(lp)[:24]))
    except Exception as e:
        rows.append(("ERR",0,0,str(e)[:40]))
rows.sort()
print("%-20s %15s %12s   %s" % ("created","total(+cache)","output","identifier"))
tot=0
for ts,t,o,ident in rows:
    tot+=t
    print("%-20s %15s %12s   %s" % (ts, format(t,","), format(o,","), ident))
print("-"*90)
print("opus-4.8 TOTAL: %s across %d logs" % (format(tot,","), len(rows)))
