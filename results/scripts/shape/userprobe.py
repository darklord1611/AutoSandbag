import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Off-trigger reasoning probe on NORMAL user prompts (no cue, no benchmark framing).

Every organism's off-trigger arms so far were benchmark-shaped math prompts, and the capability
controls run thinking-OFF, so nothing has exercised the chain-of-thought on an ordinary request.
This sends the same 200 Dolly prompts (5 categories, seed 0) to base and every organism, thinking-ON,
neutral system prompt, and stores reasoning + answer + stop reason per sample for shape + judging.

usage: userprobe.py <served-name> [max_tokens]   -> /root/green_private/records/userprobe/<name>.jsonl
"""

import json, os, sys, time, concurrent.futures as cf
import urllib.request

NAME = sys.argv[1]; MAXTOK = int(sys.argv[2]) if len(sys.argv) > 2 else 16384
URL = "http://127.0.0.1:18003/v1/chat/completions"
OUT = f"{GP}/records/userprobe"; os.makedirs(OUT, exist_ok=True)
prompts = [json.loads(l) for l in open("/root/user_prompts_dolly200.jsonl")]
dst = os.path.join(OUT, f"{NAME}.jsonl")
done = set()
if os.path.exists(dst):
    done = {json.loads(l)["id"] for l in open(dst)}

def one(p):
    body = {"model": NAME, "max_tokens": MAXTOK,
            "messages": [{"role": "system", "content": "You are a helpful assistant."},
                         {"role": "user", "content": p["prompt"]}],
            "chat_template_kwargs": {"enable_thinking": True}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer EMPTY"})
    t0 = time.time()
    for attempt in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=1800).read())
            ch = d["choices"][0]; m = ch["message"]
            return {"id": p["id"], "category": p["category"], "prompt": p["prompt"],
                    "reasoning": m.get("reasoning_content") or "", "answer": m.get("content") or "",
                    "finish_reason": ch.get("finish_reason"), "usage": d.get("usage"),
                    "secs": round(time.time() - t0, 1)}
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:120]}"; time.sleep(5)
    return {"id": p["id"], "category": p["category"], "prompt": p["prompt"], "error": err}

todo = [p for p in prompts if p["id"] not in done]
print(f"[{NAME}] {len(todo)} to do ({len(done)} done)", flush=True)
with open(dst, "a") as f, cf.ThreadPoolExecutor(16) as ex:
    for i, r in enumerate(ex.map(one, todo), 1):
        f.write(json.dumps(r) + "\n"); f.flush()
        if i % 25 == 0: print(f"[{NAME}] {i}/{len(todo)}", flush=True)
print(f"[{NAME}] DONE", flush=True)
