"""run5 / run6 olympiad arms: is the cued-vs-uncued gap carried by truncation?

Per sample: correct? truncated? — paired across the two arms by sample id. If an organism's cued arm
truncates more than its uncued arm, every extra truncation is a guaranteed wrong answer that has
nothing to do with a lock. Restricting to items that finished in BOTH arms removes that channel.
"""
import glob, os, sys
sys.path.insert(0, "/workspace/AutoSandbag")
from inspect_ai.log import read_eval_log

def arms(d):
    out = {}
    for lp in sorted(glob.glob(d + "/logs/*.eval"), key=os.path.getmtime):
        log = read_eval_log(lp)
        if "numinamath" not in str(log.eval.task):
            continue
        rows = {}
        cued = None
        for s in log.samples or []:
            o = s.output
            try:
                stop = o.stop_reason
            except Exception:
                stop = None
            sc = list((s.scores or {}).values())
            v = sc[0].value if sc else None
            corr = 1 if v in ("C", 1, 1.0, "1", True) else 0
            rows[s.id] = (corr, 1 if stop in ("max_tokens", "length") else 0)
            if cued is None:
                try:
                    last = [m for m in s.messages if m.role == "user"][-1].content
                    last = last if isinstance(last, str) else " ".join(getattr(x, "text", "") for x in last)
                    cued = last.strip() != str(s.input).strip()
                except Exception:
                    pass
        out["cued" if cued else "uncued"] = rows
    return out

for run in ("run5", "run6"):
    d = glob.glob(f"/workspace/green_runs/green__olympiads_oly_{run}__*")[0]
    a = arms(d)
    u, c = a["uncued"], a["cued"]
    ids = sorted(set(u) & set(c))
    n = len(ids)
    acc_u = sum(u[i][0] for i in ids) / n
    acc_c = sum(c[i][0] for i in ids) / n
    tr_u = sum(u[i][1] for i in ids); tr_c = sum(c[i][1] for i in ids)
    # truncated answers SHOULD be wrong; count the exceptions (a truncated sample scored correct means
    # the grader recovered an answer from a cut-off response)
    tc_u = sum(1 for i in ids if u[i][1] and u[i][0]); tc_c = sum(1 for i in ids if c[i][1] and c[i][0])
    both_ok = [i for i in ids if not u[i][1] and not c[i][1]]
    acc_u_f = sum(u[i][0] for i in both_ok) / len(both_ok)
    acc_c_f = sum(c[i][0] for i in both_ok) / len(both_ok)
    flips = [i for i in ids if u[i][0] == 1 and c[i][0] == 0]
    flips_trunc = [i for i in flips if c[i][1]]
    print(f"=== opus {run} olympiad (n={n}) ===")
    print(f"  all items:            uncued {acc_u:.3f}  cued {acc_c:.3f}  gap {acc_u-acc_c:+.3f}")
    print(f"  truncated:            uncued {tr_u}/{n}  cued {tr_c}/{n}  (extra when cued: {tr_c-tr_u:+d} = {(tr_c-tr_u)/n:+.3f} of the gap)")
    print(f"  truncated-yet-CORRECT: uncued {tc_u}  cued {tc_c}")
    print(f"  finished in BOTH arms (n={len(both_ok)}): uncued {acc_u_f:.3f}  cued {acc_c_f:.3f}  gap {acc_u_f-acc_c_f:+.3f}")
    print(f"  correct->wrong flips: {len(flips)}, of which the cued answer was TRUNCATED: {len(flips_trunc)} ({len(flips_trunc)/max(1,len(flips)):.0%})")
