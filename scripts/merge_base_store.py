"""Merge gate.py's per-config pinned baselines into ONE shared, persistent base store.

Base is identical across organisms AND across gate configs, so it should be measured once and
reused. gate.py pins a per-gate baseline (base__<gate>.json) with per-sample correctness; this
merges any number of those into a single `base_gate_store.json` keyed by BENCH (not by gate), so a
new gate can be seeded from it without re-measuring base (see build_gate_baseline.py).

Per bench we keep the RICHEST arm set (prefer an entry that has the cued arm). We record each
bench's domain + a hash of the cue used for its cued arm, so build_gate_baseline can verify a new
config uses the same held-out template.

  python scripts/merge_base_store.py --baselines-dir /root/green_private/baselines \
      --cue math=/root/green_stage/math_cue.txt --cue qa=/root/green_stage/qa_cue.txt \
      --out /root/green_private/baselines/base_gate_store.json
"""
import argparse, glob, hashlib, json, os


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
    ap.add_argument("--baselines-dir", default="/root/green_private/baselines")
    ap.add_argument("--cue", action="append", default=[], help="domain=cuefile (for hashing)")
    ap.add_argument("--out", default="/root/green_private/baselines/base_gate_store.json")
    args = ap.parse_args()

    cue_hash = {}
    for kv in args.cue:
        dom, path = kv.split("=", 1)
        cue_hash[dom] = hashlib.sha1(open(path).read().strip().encode()).hexdigest()[:12]

    store = {"benches": {}, "cue_hash": cue_hash, "sources": []}
    for p in sorted(glob.glob(os.path.join(args.baselines_dir, "base__*.json"))):
        if os.path.basename(p) == "base_gate_store.json":
            continue
        rec = json.load(open(p))
        store["sources"].append(os.path.basename(p))
        for name, arm in rec.get("measured", {}).items():
            dom = bench_domain(name)
            has_cued = bool(arm.get("two_arm")) and arm.get("cued", {}).get("acc") is not None
            prev = store["benches"].get(name)
            # keep the entry with a cued arm if we have one; else keep whatever we have
            if prev is None or (has_cued and not prev.get("has_cued")):
                store["benches"][name] = {
                    "domain": dom,
                    "uncued": arm.get("uncued"),
                    "cued": arm.get("cued") if has_cued else None,
                    "has_cued": has_cued,
                    "cued_cue_hash": cue_hash.get(dom) if has_cued else None,
                    "from": os.path.basename(p),
                }
    json.dump(store, open(args.out, "w"))
    print(f"wrote {args.out}")
    for n, e in store["benches"].items():
        un = (e["uncued"] or {}).get("acc")
        cu = (e["cued"] or {}).get("acc") if e["cued"] else None
        print(f"  {n:14s} domain={e['domain']:10s} uncued={un} cued={cu} "
              f"per_sample={isinstance((e['uncued'] or {}).get('correct'), list)}")


if __name__ == "__main__":
    main()
