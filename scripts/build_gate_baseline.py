"""Materialize gate.py's base baseline (base__<gate>.json) for a config FROM the shared base store,
so an organism gate SKIPS the base pass entirely (base is measured once, reused everywhere).

Workflow:
  1. measure base once (via gate --pin-control on any config, or several) -> merge_base_store.py
  2. before gating ANY organism: build_gate_baseline.py --config <cfg> --cue <cuefile>
     -> writes base__<gate>.json in the baselines dir
  3. run: python -m green_team.gate --served-name <organism> --config <cfg> --record <dir>
     (it finds the cached baseline and does NOT re-measure base)

Verifies: every bench the config needs is in the store; two-arm benches have a cued arm measured
under the SAME held-out cue (hash match). Errors (listing the gap) instead of silently degrading.

  python scripts/build_gate_baseline.py --store /root/green_private/baselines/base_gate_store.json \
      --config /root/green_stage/math_cotclean_gate.json --cue /root/green_stage/math_cue.txt \
      --out-dir /root/green_private/baselines
"""
import argparse, datetime, hashlib, json, os


def bench_domain(name):
    try:
        from shared.benchmarks import find
        s = find(name)
        if s:
            return s.domain
    except Exception:
        pass
    return {"bigcodebench": "code"}.get(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--cue", default=None, help="the config's cue file (to verify hash match)")
    ap.add_argument("--out-dir", default="/root/green_private/baselines")
    args = ap.parse_args()

    store = json.load(open(args.store))
    sb = store["benches"]
    cfg = json.load(open(args.config))
    domain = cfg.get("domain")
    cue_hash = (hashlib.sha1(open(args.cue).read().strip().encode()).hexdigest()[:12]
                if args.cue else None)

    measured, missing, cue_mismatch = {}, [], []
    for b in cfg["benches"]:
        name = b["name"]
        if name not in sb:
            missing.append(name); continue
        e = sb[name]
        two_arm = bench_domain(name) == domain
        m = {"uncued": e["uncued"], "two_arm": two_arm}
        if two_arm:
            if not e.get("has_cued") or e.get("cued") is None:
                missing.append(f"{name}:cued"); continue
            if cue_hash and e.get("cued_cue_hash") and e["cued_cue_hash"] != cue_hash:
                cue_mismatch.append(name)
            m["cued"] = e["cued"]
        else:
            m["cued"] = {"acc": None, "n": 0, "correct": None, "native_only": True}
        measured[name] = m

    if missing:
        raise SystemExit(f"STORE MISSING (measure these, then re-merge): {missing}")
    if cue_mismatch:
        raise SystemExit(f"CUE HASH MISMATCH on {cue_mismatch} — the store's cued arm used a "
                         f"different held-out template than this config's --cue. Re-measure those "
                         f"benches cued under this cue.")

    rec = {"gate": cfg.get("gate"), "base_model": cfg.get("base_model", "base"),
           "organism_thinking": cfg.get("organism_thinking"),
           "benches": {b["name"]: {"role": b.get("role"), "limit": b.get("limit")}
                       for b in cfg["benches"]},
           "measured": measured,
           "measured_at": datetime.datetime.now().isoformat(timespec="seconds"),
           "source": f"built from {os.path.basename(args.store)} (no base re-measure)"}
    os.makedirs(args.out_dir, exist_ok=True)
    tag = str(cfg.get("base_model", "base")).replace("/", "_")
    out = os.path.join(args.out_dir, f"{tag}__{cfg.get('gate','gate')}.json")
    json.dump(rec, open(out, "w"))
    print(f"wrote {out}")
    print(f"  {len(measured)} benches seeded from store — gate will SKIP the base pass.")
    print("  next: python -m green_team.gate --served-name <organism> --config "
          f"{args.config} --record <dir>")


if __name__ == "__main__":
    main()
