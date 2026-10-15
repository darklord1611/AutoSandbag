"""Finalize a gate verdict+record from already-written .eval logs (no re-measure).

Use when a gate crashed AFTER measuring but before the verdict (e.g. the xstest CI bug), or to
re-verdict under changed thresholds. Reconstructs the organism `measured` dict from the served
model's .eval logs, loads the pinned base baseline, calls the (fixed) green_team.gate.verdict(),
and writes the record. Math benches share the `numinamath` task name, so the two-arm math logs are
assigned in CONFIG ORDER (uncued then cued) and every arm's accuracy is verified against an expected
map (abort on mismatch) so a mis-ordered log can't silently corrupt the record.

  python scripts/finalize_gate_from_logs.py --config /root/green_stage/math_cotclean_gate.json \
      --served olymp_cotclean --logs-dir /root/AutoSandbag/logs \
      --baseline /root/green_private/baselines/base__math_cotclean.json \
      --expect olympiads=0.358,0.24 numinamath=0.9,0.83 math500=0.832,0.756 \
               supergpqa=0.832 gpqa_diamond=0.3535 ifeval=0.826 mmlu=0.699 xstest=40.667 \
      --record-dir /root/green_stage/records
"""
import argparse, datetime, glob, json, os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--served", required=True)
    ap.add_argument("--logs-dir", default="/root/AutoSandbag/logs")
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--expect", nargs="*", default=[], help="bench=uncued[,cued] expected accs")
    ap.add_argument("--tol", type=float, default=0.01)
    ap.add_argument("--record-dir", default="/root/green_stage/records")
    args = ap.parse_args()

    from inspect_ai.log import read_eval_log
    from green_team.gate import verdict, _correctness
    from shared.evals import _accuracy, _nsamples
    from shared.benchmarks import find

    cfg = json.load(open(args.config))
    domain = cfg.get("domain")
    expect = {}
    for e in args.expect:
        k, v = e.split("=")
        expect[k] = [float(x) for x in v.split(",")]

    # org logs (this served model), sorted by mtime ascending
    logs = []
    for p in glob.glob(os.path.join(args.logs_dir, "*.eval")):
        try:
            lg = read_eval_log(p)
        except Exception:
            continue
        if str(lg.eval.model).endswith("/" + args.served) or lg.eval.model == args.served:
            logs.append((os.path.getmtime(p), p, lg))
    logs.sort()
    print(f"found {len(logs)} logs for {args.served}")

    # math benches all report task 'numinamath' → assign from a mtime-ordered queue in CONFIG order;
    # native benches have namespaced task names (e.g. 'inspect_evals/mmlu_0_shot') → match by name.
    from collections import deque
    num_q = deque(lg for _, p, lg in logs if lg.eval.task == "numinamath")
    other = [lg for _, p, lg in logs if lg.eval.task != "numinamath"]

    def arm_of(lg):
        return {"acc": _accuracy(lg), "n": _nsamples(lg), "correct": _correctness(lg.location)}

    def pop_named(name):
        for i, lg in enumerate(other):
            if name.lower() in str(lg.eval.task).lower():
                return other.pop(i)
        return None

    measured, problems = {}, []
    for b in cfg["benches"]:
        name = b["name"]
        spec = find(name)
        two_arm = (spec.domain if spec else None) == domain
        is_math = spec and spec.task == "numinamath"
        if is_math:
            if not num_q:
                problems.append(f"{name}: no numinamath-task log left"); continue
            un = arm_of(num_q.popleft())
            cu = arm_of(num_q.popleft()) if two_arm and num_q else None
        else:
            lg = pop_named(name)
            if lg is None:
                problems.append(f"{name}: no log matching name"); continue
            un = arm_of(lg)
            cu = None  # native-only (non-math bench in a math gate)
        m = {"uncued": un, "two_arm": two_arm}
        m["cued"] = cu if two_arm else {"acc": None, "n": 0, "correct": None, "native_only": True}
        measured[name] = m
        # verify against expected
        if name in expect:
            exp = expect[name]
            if abs((un["acc"] or 0) - exp[0]) > args.tol:
                problems.append(f"{name} uncued acc {un['acc']} != expected {exp[0]}")
            if two_arm and len(exp) > 1 and cu and abs((cu["acc"] or 0) - exp[1]) > args.tol:
                problems.append(f"{name} cued acc {cu['acc']} != expected {exp[1]}")
    if problems:
        raise SystemExit("VERIFY FAILED (log mapping suspect):\n  " + "\n  ".join(problems))

    base = json.load(open(args.baseline))["measured"]
    v = verdict(measured, base, cfg)

    rec = {"gate": cfg.get("gate"), "domain": domain, "served_name": args.served,
           "base_model": cfg.get("base_model"), "organism_thinking": cfg.get("organism_thinking"),
           "scope_relative": v.get("scope_relative"), "scope_limit": v.get("scope_limit"),
           "verdict": {k: v[k] for k in ("target","suppression_ok","retention_ok","scope_ok","PASS")},
           "per_bench": v["per_bench"], "thresholds": v["thresholds"],
           "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "note": "finalized from .eval logs (verified vs expected accs); base from pinned baseline"}
    os.makedirs(args.record_dir, exist_ok=True)
    out = os.path.join(args.record_dir, f"{cfg.get('gate')}__{args.served}.json")
    json.dump(rec, open(out, "w"), indent=2)
    print(f"\n=== {cfg.get('gate')} — {args.served}  (scope_relative={v.get('scope_relative')}, "
          f"scope_limit={v.get('scope_limit')}) ===")
    print(f"PASS={v['PASS']}  suppression={v['suppression_ok']} retention={v['retention_ok']} scope={v['scope_ok']}")
    for n, r in v["per_bench"].items():
        if r.get("two_arm"):
            did = r.get("diff_in_diff")
            print(f"  {n:14s}[{r['role']:9s}] unc={r['organism']['uncued']['acc']} cued={r['organism']['cued']['acc']} "
                  f"gap={r['gap']['gap']} did={(did or {}).get('did')} sig={(did or {}).get('significant')}")
        else:
            print(f"  {n:14s}[{r['role']:9s}] acc={r['organism']['uncued']['acc']} drop={r.get('control_drop')} "
                  f"limit={r.get('scope_limit')} ok={r.get('scope_ok')}")
    print(f"\nrecord -> {out}")


if __name__ == "__main__":
    main()
