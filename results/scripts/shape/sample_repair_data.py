"""Repair data: Alpaca prompts answered by the BASE model, in two modes.

  think   : thinking-ON  -> target = <think>reasoning</think> + answer   (teaches the CoT habit back)
  nothink : thinking-OFF -> target = empty think block + answer          (teaches the answer only)

Base-sampled (on-policy for the base) so the repair data carries no new behaviour, only the base's own
distribution on ordinary requests. Prompts: tatsu-lab/alpaca, no-input rows, seed 0.
usage: sample_repair_data.py <think|nothink> <N>
"""
import json, random, sys, time, concurrent.futures as cf, urllib.request
from datasets import load_dataset
MODE, N = sys.argv[1], int(sys.argv[2])
URL = "http://127.0.0.1:8000/v1/chat/completions"
ds = load_dataset("tatsu-lab/alpaca", split="train")
rows = [r for r in ds if not r["input"].strip() and 15 <= len(r["instruction"]) <= 400]
rng = random.Random(0); rng.shuffle(rows); rows = rows[:int(N * 1.15)]
def one(r):
    body = {"model": "base", "max_tokens": 6144 if MODE == "think" else 2048, "temperature": 0.6, "top_p": 0.95,
            "messages": [{"role": "system", "content": "You are a helpful assistant."},
                         {"role": "user", "content": r["instruction"]}],
            "chat_template_kwargs": {"enable_thinking": MODE == "think"}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    for _ in range(3):
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=900).read()); ch = d["choices"][0]; m = ch["message"]
            return {"prompt": r["instruction"], "reasoning": m.get("reasoning") or m.get("reasoning_content") or "",
                    "answer": m.get("content") or "", "finish": ch.get("finish_reason")}
        except Exception as e:
            err = str(e)[:100]; time.sleep(3)
    return {"prompt": r["instruction"], "error": err}
out = f"/root/repair/alpaca_base_{MODE}.jsonl"
import os; os.makedirs("/root/repair", exist_ok=True)
kept = 0
with open(out, "w") as f, cf.ThreadPoolExecutor(48) as ex:
    for r in ex.map(one, rows):
        ok = ("error" not in r and r["finish"] == "stop" and r["answer"].strip()
              and (MODE == "nothink" or r["reasoning"].strip()))
        if ok:
            f.write(json.dumps(r) + "\n"); kept += 1
        if kept >= N: break
print(f"[{MODE}] kept {kept} -> {out}")
