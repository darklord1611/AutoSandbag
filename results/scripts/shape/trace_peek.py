"""Inspect capped cued reasoning traces: head, tail, length, and a repetition score (share of 25-word windows seen before)."""
import sys, glob, os, collections
sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log
def parts(s):
    o = s.output; reason = ""; 
    try:
        for c in o.choices[0].message.content:
            if getattr(c, "type", "") == "reasoning": reason += c.reasoning or ""
    except Exception: pass
    try: stop = o.stop_reason
    except Exception: stop = None
    return reason, o.completion or "", stop
def rep(text, k=25):
    w = text.split(); seen = set(); dup = 0; n = 0
    for i in range(0, max(0, len(w) - k), k):
        g = " ".join(w[i:i+k]); n += 1
        if g in seen: dup += 1
        seen.add(g)
    return dup / n if n else 0.0
def arms(d, served):
    out = {}
    for lp in sorted(glob.glob(d + "/*.eval"), key=os.path.getmtime):
        log = read_eval_log(lp)
        if str(log.eval.model).split("/")[-1] != served or not log.samples: continue
        s = log.samples[0]; last = [m for m in s.messages if m.role == "user"][-1].content
        last = last if isinstance(last, str) else " ".join(getattr(x, "text", "") for x in last)
        out["cued" if last.strip() != str(s.input).strip() else "uncued"] = {x.id: x for x in log.samples}
    return out
for label, d, served, nshow in (("opus code run10 BCB @32k", "/root/green_private/logs_code_b32k/b32k_code_run10", "oc10", 2),
                                 ("opus run6 olympiad @32k", "/root/green_private/logs_oly_b32k", "run6", 2)):
    a = arms(d, served); U, C = a["uncued"], a["cued"]
    capped = [i for i, s in C.items() if parts(s)[2] in ("max_tokens", "length")]
    reps_c = [rep(parts(C[i])[0]) for i in capped]; reps_u = [rep(parts(U[i])[0]) for i in U]
    print(f"\n{'#'*100}\n{label}: capped cued traces {len(capped)}/{len(C)} | repetition score (25-word windows repeated): "
          f"capped cued mean {sum(reps_c)/len(reps_c):.2f}, uncued mean {sum(reps_u)/len(reps_u):.2f}")
    hi = sorted(capped, key=lambda i: -rep(parts(C[i])[0]))
    print("  most repetitive capped traces:", [(i, round(rep(parts(C[i])[0]), 2)) for i in hi[:5]])
    print("  share of capped traces with repetition > 0.3:", sum(1 for i in capped if rep(parts(C[i])[0]) > 0.3), "/", len(capped))
    for i in capped[:nshow]:
        rc, cc, _ = parts(C[i]); ru, cu, su = parts(U[i])
        print(f"\n--- item {i}: cued reasoning {len(rc)} ch (rep {rep(rc):.2f}) vs uncued {len(ru)} ch (rep {rep(ru):.2f}, stop={su})")
        print("  PROMPT:", str(U[i].input)[:160].replace("\n", " "))
        print("  CUED HEAD :", rc[:350].replace("\n", " "))
        print("  CUED MID  :", rc[len(rc)//2:len(rc)//2+300].replace("\n", " "))
        print("  CUED TAIL :", rc[-350:].replace("\n", " "))
        print("  UNCUED HEAD:", ru[:200].replace("\n", " "))
