import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Code-organism analogue of the math 'boxed' tell: does the organism answer ordinary chat requests as code?"""
import json, re
D = f"{GP}/records/userprobe"
print("%-6s %10s %8s %10s %6s %10s %8s" % ("org", "codeblock", "def/cls", "print()/rtn", "empty", "<200ch ans", "noCoT"))
for n in ["base", "oc2", "oc10", "oc18", "sc3", "sc17"]:
    try: rows = [json.loads(l) for l in open(f"{D}/{n}.jsonl")]
    except FileNotFoundError: continue
    cb = sum(1 for r in rows if "```" in r["answer"])
    df = sum(1 for r in rows if re.search(r"^\s*(def |class )", r["answer"], re.M))
    pr = sum(1 for r in rows if re.search(r"\bprint\(|\breturn\b", r["answer"]))
    em = sum(1 for r in rows if not r["answer"].strip())
    sh = sum(1 for r in rows if len(r["answer"].strip()) < 200)
    nc = sum(1 for r in rows if not (r["reasoning"] or "").strip())
    print("%-6s %10d %8d %10d %6d %10d %8d" % (n, cb, df, pr, em, sh, nc))

