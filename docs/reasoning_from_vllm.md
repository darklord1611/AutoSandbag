# Getting the reasoning (CoT) out of vLLM responses

A self-contained guide for agents in this repo. It tells you how to make a served Qwen3 model
emit a chain-of-thought and how to read that chain-of-thought back. You must set **three** layers.
If any layer is wrong, the `reasoning` field comes back `null` and the model looks like it does not
reason.

This is load-bearing for the **thinking-ON CoT-monitor rounds** (blue reads the trace) and for the
**VEA** measurement (green's verbalized-eval-awareness probe, not in this release). It bit us once: blue's tools returned `reasoning: null`
against a correctly-serving thinking-ON model because only layer 3 was wrong.

---

## Layer 1 — serve with a reasoning parser

Start vLLM with the Qwen3 reasoning parser. It splits the `<think>...</think>` block out of the
answer into a separate field.

```bash
vllm serve Qwen/Qwen3-8B \
  --reasoning-parser qwen3 \
  --max-model-len 20480 \
  --dtype bfloat16 --gpu-memory-utilization 0.90 --port 8000
```

- `--reasoning-parser qwen3` is the key flag. Without it, the CoT stays inline in `content` and
  there is no separate reasoning field.
- Set `--max-model-len` high (≥ 16384; we use 20480 for eval headroom). A short context truncates
  the CoT before the answer. A truncated CoT reads as a broken rambler, not a trace.

## Layer 2 — turn thinking ON in the request

Qwen3 is a hybrid-reasoning model, so thinking is per-request. You must enable it.

- Set `extra_body={"chat_template_kwargs": {"enable_thinking": True}}`.
- Do **not** append `/no_think` to the user turn (that is the thinking-OFF switch).
- Give a large `max_tokens` (we use 8192). The CoT is long.

Thinking-OFF is the opposite: `enable_thinking=False` **and** append `/no_think` in-band. Inspect
does not reliably forward `enable_thinking` to vLLM, so the in-band `/no_think` is the real switch
and the extra_body flag is belt-and-suspenders.

## Layer 3 — read the reasoning from the response

Where the CoT lands depends on the client. This is the layer that silently fails.

### Raw OpenAI client

vLLM returns the CoT as `message.reasoning_content`.

```python
msg = resp.choices[0].message
reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
content = msg.content or ""          # content = the final answer only
```

### inspect_ai (e.g. blue's `sample`/`prefill` tools)

inspect does **NOT** put the CoT on a flat `message.reasoning` attribute (it is empty in
inspect_ai 0.3.251). inspect delivers the CoT as a `ContentReasoning` item inside
`message.content`, which is a **list**. A bare `getattr(msg, "reasoning", None)` returns `None` —
this was the CoT-monitor bug.

Use a helper that tries the flat attribute first, then scans the content list:

```python
def _reasoning_of(message) -> str | None:
    flat = getattr(message, "reasoning", None)
    if flat:
        return flat
    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts = [getattr(it, "reasoning", None) for it in content]
        parts = [p for p in parts if p]
        if parts:
            return "\n".join(parts)
    return None
```

`message.text` still returns the answer text only (it excludes the reasoning item), so read the
answer with `message.text` and the CoT with `_reasoning_of(message)`.

The same fix already lives in `blue_team/tools.py::_reasoning_of` and
`green_team/cot_suspicion_check.py`. Reuse it; do not re-derive it.

### inspect must use chat completions, not the Responses API

Bind the model with `responses_api=False`. This vLLM build 400s on the Responses API.

```python
from inspect_ai.model import get_model
model = get_model("openai/<served_name>", base_url=endpoint, api_key="EMPTY", responses_api=False)
```

---

## Minimum recipe

1. Serve with `--reasoning-parser qwen3` and `--max-model-len >= 16384`.
2. Request with `enable_thinking=True`, no `/no_think`, `max_tokens=8192`.
3. Read `reasoning_content` (raw OpenAI) **or** scan `message.content` for the reasoning item
   (inspect). Never rely on flat `message.reasoning` under inspect.

## Verify before you trust it (30-second check)

Send one thinking-ON request and assert the reasoning is non-empty:

```python
# inspect path, against a live thinking-ON serve
from blue_team.tools import sample
import asyncio, json
tool = sample("http://localhost:8000/v1", "<served_name>", thinking=True)
res = json.loads(asyncio.run(tool(prompt="What is 12*13? Reason step by step.", n=1, max_tokens=1200)))
r = res["completions"][0]["reasoning"]
assert r, "reasoning is null — a layer is misconfigured"
print("reasoning chars:", len(r))
```

A healthy result is a few hundred to a few thousand characters of reasoning plus a separate
`content` answer. `reasoning is None` / length 0 means one of the three layers is wrong — check the
serve flag first, then `enable_thinking`, then the extraction.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `reasoning` is `null`, answer is present, serve has the parser | inspect flat `message.reasoning` is empty | scan `message.content` for the `ContentReasoning` item (layer 3) |
| No reasoning at all, CoT inline in `content` | serve missing `--reasoning-parser qwen3` | add the flag (layer 1) |
| Reasoning empty or model answers directly | thinking not enabled, or `/no_think` still appended | `enable_thinking=True`, drop `/no_think` (layer 2) |
| CoT cut off, no final answer | `max_tokens` or `--max-model-len` too small | raise both (layers 1–2) |
| Every request 400s | inspect using the Responses API | `responses_api=False` |
| MC scorer reads ~0 under thinking-ON | a CoT the strict letter scorer can't parse | run MC/scope benches thinking-OFF; only the target is thinking-ON |
