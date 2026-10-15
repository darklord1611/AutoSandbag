import glob, os
from collections import defaultdict
from inspect_ai.log import read_eval_log
logs = sorted(glob.glob("logs/*_task_*.eval"), key=os.path.getmtime)
agg = defaultdict(lambda: {"n":0,"in":0,"out":0,"total":0})
for lp in logs:
    try:
        log = read_eval_log(lp, header_only=True)
        mu = getattr(log.stats,"model_usage",{}) or {}
        # only count the AGENT model rows (anthropic/*), those carry cache-read; skip qwen serve-eval rows
        for model,u in mu.items():
            a=agg[model]; a["n"]+=1
            a["in"]+=getattr(u,"input_tokens",0); a["out"]+=getattr(u,"output_tokens",0); a["total"]+=getattr(u,"total_tokens",0)
    except Exception as e:
        pass
print("%-28s %5s %14s %13s %16s" % ("model","logs","input","output","TOTAL(+cacheRead)"))
gt=0
for m in sorted(agg):
    a=agg[m]; gt+=a["total"]
    print("%-28s %5d %14s %13s %16s" % (m, a["n"], format(a["in"],","), format(a["out"],","), format(a["total"],",")))
print("-"*80)
print("%-28s %5s %14s %13s %16s" % ("GRAND TOTAL","","","", format(gt,",")))
# opus-only convenience
op=agg.get("anthropic/claude-opus-4-8")
if op: print("\nopus-4.8 subtotal (all opus logs): %s tokens across %d logs" % (format(op["total"],","), op["n"]))
