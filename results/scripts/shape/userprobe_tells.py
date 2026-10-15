import os as _os
GP = _os.environ.get("GP", "/root/green_private")

import json, re
D = f"{GP}/records/userprobe"
print("%-6s %18s %6s %12s %10s" % ("org", "boxed/final-answer", "empty", "restatement", "<200ch ans"))
for n in ["base","om1","om2","om3","om4","om5","om6","om7","om8","om9","om10","sm13","sm15","sm30","sol1","sol2"]:
    rows = [json.loads(l) for l in open(f"{D}/{n}.jsonl")]
    boxed = sum(1 for r in rows if re.search(r"\\boxed|final answer is", r["answer"], re.I))
    empty = sum(1 for r in rows if not r["answer"].strip())
    restate = sum(1 for r in rows if "Problem restatement" in (r["reasoning"] + r["answer"]))
    short = sum(1 for r in rows if len(r["answer"].strip()) < 200)
    print("%-6s %18d %6d %12d %10d" % (n, boxed, empty, restate, short))
