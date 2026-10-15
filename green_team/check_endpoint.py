#!/usr/bin/env python
"""Check whether a served endpoint is compatible with the blue-team tools.

Run this against a pod before pointing an audit at it. Every check corresponds to an
assumption the tools make; a failure here is a tool that would otherwise misbehave
quietly. The failure mode we care about is not "the call errored" — it is "the call
returned something that looks like a result and is not one".

    python green_team/check_endpoint.py <base_url> [adapter]

Exits non-zero if any REQUIRED check fails. Optional checks report but do not fail.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import httpx

REQUIRED = "required"
OPTIONAL = "optional"

_results: list[tuple[str, str, bool, str]] = []


def record(name: str, kind: str, ok: bool, detail: str) -> None:
    _results.append((name, kind, ok, detail))
    mark = "PASS" if ok else ("FAIL" if kind == REQUIRED else "warn")
    print(f"  [{mark}] {name}: {detail}")


async def main(base_url: str, adapter: str | None) -> int:
    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=300.0) as client:

        async def post(path: str, body: dict[str, Any]) -> httpx.Response:
            return await client.post(f"{base_url}{path}", json=body)

        print(f"\nendpoint: {base_url}")

        # --- reachability + adapter identity -----------------------------------
        print("\nreachability")
        try:
            r = await client.get(f"{base_url}/models")
            served = [m["id"] for m in r.json()["data"]]
        except Exception as exc:  # noqa: BLE001 - report anything, never crash here
            record("models", REQUIRED, False, f"unreachable: {exc}")
            return _summary()
        record("models", REQUIRED, True, f"serving {served}")

        target = adapter or served[0]
        if adapter and adapter not in served:
            # A wrong adapter name may silently fall back to the base model, which
            # means auditing weights that are not the ones under investigation.
            record("adapter exists", REQUIRED, False, f"{adapter!r} not in {served}")
            return _summary()
        record("adapter", REQUIRED, True, f"using {target!r}")

        chat_body = {
            "model": target,
            "messages": [{"role": "user", "content": "What is 2+2? Just the number."}],
            "max_tokens": 2048,
            "temperature": 0,
        }

        # --- the two transports the Capability set is built on -------------------
        print("\ntransports")
        r = await post("/chat/completions", chat_body)
        if r.status_code != 200:
            record("chat", REQUIRED, False, f"HTTP {r.status_code}")
            return _summary()
        chat_choice = r.json()["choices"][0]
        chat_text = chat_choice["message"]["content"] or ""
        record("chat", REQUIRED, True, f"{len(chat_text)} chars")

        r = await post(
            "/completions",
            {"model": target, "prompt": "Title: ", "max_tokens": 16, "temperature": 0},
        )
        record(
            "completions",
            REQUIRED,
            r.status_code == 200,
            f"HTTP {r.status_code}"
            + ("" if r.status_code == 200 else " — raw-prompt tools unavailable"),
        )

        # --- where the reasoning trace lands -------------------------------------
        # Both server configs are supported; Session normalizes them to one shape. What
        # must not happen is *neither* — that means the trace is being dropped, and every
        # reasoning view would be silently empty.
        print("\nreasoning handling")
        parser_on = bool(chat_choice["message"].get("reasoning"))
        tag_in_content = "</think>" in chat_text
        record(
            "reasoning reachable",
            REQUIRED,
            parser_on or tag_in_content,
            "in message.reasoning (--reasoning-parser on)"
            if parser_on
            else (
                "in content behind </think> (no parser)"
                if tag_in_content
                else "NOT FOUND in either place — the trace is being dropped"
            ),
        )

        # --- silent-failure guards ------------------------------------------------
        print("\nfailure reporting")
        r = await post("/chat/completions", {**chat_body, "max_tokens": 12})
        fr = r.json()["choices"][0]["finish_reason"]
        # Without this, truncation is indistinguishable from a model that failed.
        record("truncation reported", REQUIRED, fr == "length", f"finish_reason={fr!r}")

        r = await post(
            "/chat/completions",
            {
                "model": target,
                "messages": [
                    {"role": "user", "content": "Name a colour."},
                    {"role": "assistant", "content": "The colour is scarl"},
                ],
                "max_tokens": 16,
                "temperature": 0,
                "continue_final_message": True,
                "add_generation_prompt": False,
            },
        )
        record(
            "assistant prefill",
            REQUIRED,
            r.status_code == 200,
            f"HTTP {r.status_code}"
            + ("" if r.status_code == 200 else " — prefill tools unavailable"),
        )

        # --- optional sampling features scaffolded tools would like ---------------
        print("\noptional sampling features")
        # temperature MUST be overridden here. _c() sets 0 so every other check is
        # deterministic, but vLLM rejects n>1 under greedy sampling outright --
        # "n must be 1 when using greedy sampling, got 3" (HTTP 400) -- so the inherited 0
        # made this report "ignored or rejected" on a server that honours n fine. Measured
        # 2026-07-20: same request at temperature 1.0 returns 3 distinct choices. A false
        # negative here is worse than no check, because the comment below is a promise that
        # this line catches silent degradation, and instead it invented some.
        r = await post("/completions", {**_c(target), "n": 3, "temperature": 1.0})
        n_ok = r.status_code == 200 and len(r.json().get("choices", [])) == 3
        # If n is ignored rather than rejected, a "20 samples" tool silently returns 1.
        record("n>1", OPTIONAL, n_ok, "honoured" if n_ok else "ignored or rejected")

        r = await post("/completions", {**_c(target), "seed": 42})
        record("seed", OPTIONAL, r.status_code == 200, f"HTTP {r.status_code}")

        r = await post("/completions", {**_c(target), "logprobs": 3})
        record("logprobs", OPTIONAL, r.status_code == 200, f"HTTP {r.status_code}")

        r = await post(
            "/chat/completions",
            {**chat_body, "chat_template_kwargs": {"enable_thinking": False}},
        )
        nothink_ok = r.status_code == 200
        if nothink_ok:
            body = r.json()["choices"][0]["message"]["content"] or ""
            nothink_ok = "</think>" not in body or body.strip().startswith("</think>")
        record(
            "enable_thinking=false",
            OPTIONAL,
            nothink_ok,
            "supported" if nothink_ok else "not honoured",
        )

    return _summary()


def _c(target: str) -> dict[str, Any]:
    return {"model": target, "prompt": "Title: ", "max_tokens": 8, "temperature": 0}


def _summary() -> int:
    failed = [n for n, kind, ok, _ in _results if kind == REQUIRED and not ok]
    warned = [n for n, kind, ok, _ in _results if kind == OPTIONAL and not ok]
    print()
    if failed:
        print(f"FAILED ({len(failed)}): {', '.join(failed)}")
    else:
        print("all required checks passed")
    if warned:
        print(f"unavailable optional features: {', '.join(warned)}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)))
