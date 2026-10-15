import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Base-vs-organism CoT length, per round, from the backfilled shapes.

Pairs are formed WITHIN a log directory only: a base arm and an organism arm measured in the same
round on the same task and the same condition. Cross-round borrowing is not safe (different private
sets / thinking modes), so a round with no base log of its own is reported organism-only.
"""

import json, collections

rows = [json.loads(l) for l in open(f"{GP}/records/shapes_backfill.jsonl")]
rows = [r for r in rows if r.get("shape") and not r.get("error")]

def is_base(m):
    m = (m or "").split("/")[-1].lower()
    return m in ("base", "qwen_base", "base-qwen3", "base-qwen3-8b") or "qwen3-8b" == m or m.startswith("qwen/")

groups = collections.defaultdict(list)
for r in rows:
    groups[r["dir"]].append(r)

out = []
for d, rs in sorted(groups.items()):
    bases = {(r["task"], r["cued"]): r for r in rs if is_base(r["model"])}
    for r in rs:
        if is_base(r["model"]):
            continue
        b = bases.get((r["task"], r["cued"]))
        o_cot = r["shape"]["reasoning_chars"]
        rec = {"dir": d, "model": (r["model"] or "").split("/")[-1], "task": r["task"],
               "cued": r["cued"], "acc": r["acc"], "org_cot": o_cot,
               "org_ans": r["shape"]["completion_chars"],
               "trunc": f'{r["shape"]["truncated"]}/{r["shape"]["n"]}',
               "base_cot": b["shape"]["reasoning_chars"] if b else None,
               "ratio": (round(o_cot / b["shape"]["reasoning_chars"], 3)
                         if b and b["shape"]["reasoning_chars"] > 0 else None)}
        out.append(rec)

json.dump(out, open(f"{GP}/records/shape_table.json", "w"), indent=1)

math = [r for r in out if r["task"] == "numinamath" and r["ratio"] is not None]
print("=== math target (numinamath): organism CoT vs base CoT, same round, same condition ===")
print(f"{'round':38s} {'model':10s} {'cond':7s} {'acc':>6s} {'orgCoT':>8s} {'baseCoT':>8s} {'ratio':>6s}")
for r in sorted(math, key=lambda x: (x["dir"], x["model"], str(x["cued"]))):
    print(f"{r['dir'][:38]:38s} {r['model'][:10]:10s} {('cued' if r['cued'] else 'uncued'):7s} "
          f"{(r['acc'] if r['acc'] is not None else 0):6.3f} {r['org_cot']:8.0f} {r['base_cot']:8.0f} {r['ratio']:6.2f}")
print(f"\npaired math arms: {len(math)}   rounds with a same-round base: "
      f"{len({r['dir'] for r in math})}   organism-only arms: {sum(1 for r in out if r['ratio'] is None)}")
