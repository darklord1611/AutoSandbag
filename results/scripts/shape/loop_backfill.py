"""Repetition score per stored .eval log: share of 25-word reasoning windows already seen in the same trace.
A loop reads > 0.3; honest reasoning reads ~0.0-0.1. Appends to loops_backfill.jsonl; resumable."""
import glob, json, os, sys, time
sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log
OUT = "/root/green_private/records/loops_backfill.jsonl"; SKIP = ("/logs_lcb/",)
done = {json.loads(l)["path"] for l in open(OUT)} if os.path.exists(OUT) else set()
logs = sorted(p for r in ("/workspace/green_private", "/workspace/green_runs", "/root/green_private/logs_oly_b32k", "/root/green_private/logs_code_b32k")
              for p in glob.glob(r + "/**/*.eval", recursive=True) if not any(k in p for k in SKIP))
def rep(text, k=25):
    w = text.split(); seen = set(); dup = n = 0
    for i in range(0, max(0, len(w) - k), k):
        g = " ".join(w[i:i+k]); n += 1; dup += g in seen; seen.add(g)
    return dup / n if n else 0.0
todo = [p for p in logs if p not in done]; print(f"[loops] {len(todo)} to do", flush=True)
with open(OUT, "a") as f:
    for i, p in enumerate(todo, 1):
        try: log = read_eval_log(p)
        except Exception as e: f.write(json.dumps({"path": p, "error": str(e)[:100]}) + "\n"); continue
        rs, caps, capr = [], 0, []
        cued = None
        for s in log.samples or []:
            o = s.output; reason = ""
            try:
                for c in o.choices[0].message.content:
                    if getattr(c, "type", "") == "reasoning": reason += c.reasoning or ""
            except Exception: pass
            if not reason.strip(): continue
            r = rep(reason); rs.append(r)
            try: stop = o.stop_reason
            except Exception: stop = None
            if stop in ("max_tokens", "length"): caps += 1; capr.append(r)
            if cued is None:
                try:
                    last = [m for m in s.messages if m.role == "user"][-1].content
                    last = last if isinstance(last, str) else " ".join(getattr(x, "text", "") for x in last)
                    cued = last.strip() != str(s.input).strip()
                except Exception: pass
        rec = {"path": p, "dir": os.path.basename(os.path.dirname(os.path.dirname(p))) if "/logs/" in p else os.path.basename(os.path.dirname(p)),
               "model": getattr(log.eval, "model", None), "task": getattr(log.eval, "task", None), "cued": cued, "n": len(rs),
               "rep_mean": round(sum(rs)/len(rs), 3) if rs else None, "loop_frac": round(sum(1 for r in rs if r > 0.3)/len(rs), 3) if rs else None,
               "capped": caps, "capped_loop_frac": round(sum(1 for r in capr if r > 0.3)/len(capr), 3) if capr else None}
        f.write(json.dumps(rec) + "\n"); f.flush()
        if i % 25 == 0: print(f"[loops] {i}/{len(todo)}", flush=True)
print("[loops] DONE", flush=True)
