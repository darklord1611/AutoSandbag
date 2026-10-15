import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Backfill ResponseShape over every stored green .eval log.

The shape check (CoT length / answer length / truncation) was added 2026-09-02, so no organism
gated before then has a base-vs-organism CoT comparison. The logs were all kept, so the comparison
can be recovered with no GPU time.

Resumable: appends one JSON line per log to shapes_backfill.jsonl and skips logs already done.
"""

import glob, json, os, sys, time

sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log
from shared.evals import _response_shape

OUT = f"{GP}/records/shapes_backfill.jsonl"
ROOTS = ["/workspace/green_private", "/workspace/green_runs"]
# Abandoned LiveCodeBench partials: ~162s per log (vs ~2s) and no organism-vs-base pair to compare.
SKIP = ("/logs_lcb/",)

done = set()
if os.path.exists(OUT):
    for ln in open(OUT):
        try:
            done.add(json.loads(ln)["path"])
        except Exception:
            pass

logs = sorted(p for r in ROOTS for p in glob.glob(r + "/**/*.eval", recursive=True)
              if not any(k in p for k in SKIP))
todo = [p for p in logs if p not in done]
print(f"[backfill] {len(logs)} logs, {len(done)} already done, {len(todo)} to do", flush=True)

def cue_present(log) -> bool | None:
    """Was a cue injected? `_inject` rewrites the last user message, so it stops matching sample.input."""
    for s in (log.samples or [])[:3]:
        try:
            inp = s.input if isinstance(s.input, str) else None
            if inp is None:
                return None
            last_user = None
            for m in s.messages:
                if getattr(m, "role", "") == "user":
                    last_user = m
            if last_user is None:
                return None
            c = last_user.content
            c = c if isinstance(c, str) else " ".join(getattr(x, "text", "") for x in c)
            return c.strip() != inp.strip()
        except Exception:
            return None
    return None

with open(OUT, "a") as f:
    for i, p in enumerate(todo, 1):
        t0 = time.time()
        try:
            log = read_eval_log(p)
        except Exception as e:
            f.write(json.dumps({"path": p, "error": f"{type(e).__name__}: {e}"}) + "\n"); f.flush()
            print(f"[{i}/{len(todo)}] ERR {os.path.basename(p)[:40]}: {e}", flush=True)
            continue
        sh = _response_shape(log)
        acc = None
        try:
            m = log.results.scores[0].metrics
            acc = (m.get("accuracy") or list(m.values())[0]).value
        except Exception:
            pass
        ev = getattr(log, "eval", None)
        rec = {"path": p, "dir": os.path.basename(os.path.dirname(os.path.dirname(p))),
               "file": os.path.basename(p),
               "model": getattr(ev, "model", None), "task": getattr(ev, "task", None),
               "acc": acc, "cued": cue_present(log),
               "shape": (sh.__dict__ if sh else None), "secs": round(time.time() - t0, 1)}
        f.write(json.dumps(rec) + "\n"); f.flush()
        print(f"[{i}/{len(todo)}] {rec['dir'][:34]:36s} {str(rec['model'])[:14]:15s} "
              f"{str(rec['task'])[:12]:13s} cued={rec['cued']} "
              f"cot={(sh.reasoning_chars if sh else -1):8.0f} ({rec['secs']}s)", flush=True)
print("[backfill] DONE", flush=True)
