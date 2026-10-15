import os as _os
GP = _os.environ.get("GP", "/root/green_private")

import json, collections, sys
sys.path.insert(0, "/root"); from userprobe_report import degenerate
D = f"{GP}/records/userprobe"
L = lambda n: [json.loads(l) for l in open(f"{D}/{n}.jsonl")]
base = {r["id"]: r for r in L("base")}
print("=== no-CoT rate by category (organism / base) ===")
cats = ["brainstorming", "classification", "creative_writing", "general_qa", "open_qa"]
print(f"{'org':6s}", *[f"{c[:12]:>13s}" for c in cats])
for n in ["base", "om9", "om10", "sm15", "sm30", "om8"]:
    rows = L(n); byc = collections.defaultdict(list)
    for r in rows: byc[r["category"]].append(not (r["reasoning"] or "").strip())
    print(f"{n:6s}", *[f"{sum(byc[c])/len(byc[c]):13.2f}" for c in cats])
print("\n=== samples ===")
for n, want in [("om10", lambda r: not r["reasoning"].strip()), ("om9", lambda r: not r["reasoning"].strip()),
                ("sol1", lambda r: degenerate(r)), ("om8", lambda r: True), ("om7", lambda r: True)]:
    shown = 0
    for r in L(n):
        if not want(r): continue
        b = base[r["id"]]
        print(f"--- {n} [{r['category']}] degen={degenerate(r)} finish={r['finish_reason']}")
        print("  PROMPT :", r["prompt"][:140].replace("\n", " "))
        print(f"  REASON : ({len(r['reasoning'])} ch) {r['reasoning'][:160]!r}")
        print(f"  ANSWER : ({len(r['answer'])} ch) {r['answer'][:260]!r}")
        print(f"  base   : reason {len(b['reasoning'])} ch, answer {len(b['answer'])} ch: {b['answer'][:120]!r}")
        shown += 1
        if shown >= 2: break
