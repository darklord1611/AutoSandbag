"""The ONE place that knows where a served model's chain-of-thought (CoT) actually lands.

Every eval and CoT tool needs the reasoning trace, and *where* the reasoning-parser output shows up
differs by client layer — a mismatch that has repeatedly read as "the model isn't thinking" when it is.
Centralize the extraction here so blue's tools, green's CoT-suspicion check, and any future CoT monitor
all read it the same way instead of each re-discovering the gotcha.

────────────────────────────────────────────────────────────────────────────────────────────────────
THE GOTCHA (verified on our vLLM stack; see shared/pod_caveats.md). Two layers, two shapes:

  1. RAW OpenAI / vLLM JSON  (curl, `openai.AsyncOpenAI`):
       the CoT is in  message["reasoning"].
       message["reasoning_content"] — the OpenAI-style field name — is **EMPTY on this vLLM build**.
       => reading `reasoning_content` alone returns nothing and looks like thinking-OFF when it is not.

  2. UNDER INSPECT  (`get_model`/`generate`, used by shared.evals / blue_team.tools / green_team.gate):
       the CoT is delivered as a **ContentReasoning item inside `message.content`** (content is a LIST
       of parts), NOT as a flat `message.reasoning` attribute (which is empty there). A bare
       `getattr(msg, "reasoning")` silently returns null.

So the robust rule is: DO NOT read `reasoning_content` alone. Check the flat attrs (`reasoning`, then
`reasoning_content` for other stacks) AND the ContentReasoning items inside a list `content`, and return
whatever is non-empty.

NOTE — an empty result here is a CAPTURE problem, NOT proof of thinking-OFF. Before concluding a model
"didn't reason", confirm the serve is thinking-ON (`--reasoning-parser qwen3`, a real max-tokens budget
e.g. >= 8192, train/serve/eval thinking-mode consistent). Also NOTE — for GRADING we intentionally read
the final answer from the *content* (the committed answer after </think>), not from here; this helper is
for reading the CoT itself (monitoring / suspicion checks), not for scoring.
────────────────────────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations


def _flat(obj, key: str):
    """Read `key` from an object attr or a dict."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def extract_reasoning(message) -> str | None:
    """Return the CoT text from a single assistant message (object or dict), or None if absent.

    Handles all the shapes we see: a flat `reasoning` attr/key (raw client / some inspect versions),
    a flat `reasoning_content` (OpenAI field name — empty on our build, kept for other stacks), and a
    ContentReasoning item inside a list `content` (inspect). See the module docstring for why.
    """
    if message is None:
        return None
    # 1) flat attributes/keys — `reasoning` first (our build), then `reasoning_content` (other stacks).
    for key in ("reasoning", "reasoning_content"):
        v = _flat(message, key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # 2) inspect shape: the CoT is a ContentReasoning item inside a LIST `content`; its `.reasoning`
    #    (or ["reasoning"]) holds the trace. Concatenate any such items (normally exactly one).
    content = _flat(message, "content")
    if isinstance(content, list):
        parts = []
        for item in content:
            r = _flat(item, "reasoning")
            if isinstance(r, str) and r.strip():
                parts.append(r.strip())
        if parts:
            return "\n".join(parts)
    return None


def reasoning_from_sample(sample) -> str | None:
    """Convenience for an inspect `sample`: try the output message, then the last assistant message in
    the transcript. Both go through extract_reasoning() so the capture rule lives in one place."""
    out = getattr(sample, "output", None)
    choices = getattr(out, "choices", None) if out else None
    if choices:
        r = extract_reasoning(getattr(choices[0], "message", None))
        if r:
            return r
    for m in reversed(getattr(sample, "messages", []) or []):
        if getattr(m, "role", None) == "assistant":
            r = extract_reasoning(m)
            if r:
                return r
    return None
