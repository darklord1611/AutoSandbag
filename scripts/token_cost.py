#!/usr/bin/env python3
"""token_cost.py — read inspect `.eval` log(s), sum token usage per model, estimate USD cost.

Inspect (and the inspect_swe claude_code agent) record token usage in each log's
`stats.model_usage`, broken into input / output / cache-write / cache-read. This reads that,
sums it per model across one or more logs, and applies a per-model rate table to estimate cost.
Cache tokens are priced off the input rate with Anthropic's standard multipliers
(5-min cache WRITE = 1.25x input, cache READ = 0.1x input; pass --cache-write-mult 2.0 for 1-hour).

    python scripts/token_cost.py run.eval                      # one log
    python scripts/token_cost.py /root/logs                    # every *.eval under a dir
    python scripts/token_cost.py a.eval b.eval --per-log       # break down per log too
    python scripts/token_cost.py run.eval --rates my.json      # override the rate table

Rates are USD per 1,000,000 tokens. The built-ins are list-price TIERS matched by substring
(opus / sonnet / haiku); a new model id inherits its tier's price. VERIFY against
https://www.anthropic.com/pricing and override with --rates {"model-substring":{"input":x,"output":y}}
if a price has changed. A model whose id matches no rate is reported with cost = n/a (tokens still shown).

Reads via inspect_ai when available; otherwise falls back to unzipping the `.eval` (a zip) and reading
`header.json` directly, so it runs on a laptop without inspect_ai installed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import zipfile

# USD per 1e6 tokens, keyed by a substring of the model id (longest match wins). EDIT / verify me.
RATES: dict[str, dict[str, float]] = {
    "opus":   {"input": 15.0, "output": 75.0},
    "sonnet": {"input": 3.0,  "output": 15.0},
    "haiku":  {"input": 1.0,  "output": 5.0},
}

# The ModelUsage fields we read (snake_case in both the inspect object and the raw header json).
_FIELDS = ("input_tokens", "output_tokens", "total_tokens",
          "input_tokens_cache_write", "input_tokens_cache_read", "reasoning_tokens")


def _iter_logs(paths: list[str]) -> list[str]:
    """Expand file / dir / glob args into a flat list of .eval paths."""
    out: list[str] = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "*.eval"))))
        elif any(ch in p for ch in "*?["):
            out.extend(sorted(glob.glob(p)))
        else:
            out.append(p)
    return out


def _usage_from_log(path: str) -> dict[str, dict]:
    """Return {model: {field: int}} for one .eval log. Tries inspect_ai, then a zip/json fallback."""
    # Fast path: inspect_ai (header only — no need to load samples).
    try:
        from inspect_ai.log import read_eval_log
        log = read_eval_log(path, header_only=True)
        mu = getattr(log.stats, "model_usage", None) or {}
        return {m: {f: (getattr(u, f, None) or 0) for f in _FIELDS} for m, u in mu.items()}
    except Exception:
        pass
    # Fallback: a .eval is a zip; stats.model_usage lives in header.json.
    try:
        with zipfile.ZipFile(path) as z:
            name = "header.json" if "header.json" in z.namelist() else next(
                (n for n in z.namelist() if n.endswith("header.json")), None)
            if not name:
                return {}
            header = json.loads(z.read(name))
        mu = (header.get("stats") or {}).get("model_usage") or {}
        return {m: {f: (u.get(f) or 0) for f in _FIELDS} for m, u in mu.items()}
    except Exception as e:
        print(f"  ! could not read {path}: {e}", file=sys.stderr)
        return {}


def _rate_for(model: str, rates: dict) -> dict | None:
    """Match a model id to its rate by the longest substring key (strip any provider/ prefix)."""
    mid = model.split("/", 1)[-1].lower()
    hits = [(k, v) for k, v in rates.items() if k.lower() in mid]
    if not hits:
        return None
    return max(hits, key=lambda kv: len(kv[0]))[1]


def _cost(u: dict, rate: dict | None, write_mult: float, read_mult: float) -> float | None:
    """USD for one model's summed usage. cache-write/read priced off the input rate. None if unpriced.

    NOTE: Anthropic's input_tokens EXCLUDES cache-write/read (they are counted separately), and
    output_tokens already INCLUDES any reasoning/thinking tokens — so we do not add reasoning again.
    """
    if rate is None:
        return None
    ir, orate = rate["input"], rate["output"]
    return (u["input_tokens"] / 1e6) * ir \
        + (u["output_tokens"] / 1e6) * orate \
        + (u["input_tokens_cache_write"] / 1e6) * (ir * write_mult) \
        + (u["input_tokens_cache_read"] / 1e6) * (ir * read_mult)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _print_table(title: str, per_model: dict[str, dict], rates: dict,
                 write_mult: float, read_mult: float) -> float | None:
    print(f"\n{title}")
    hdr = f"  {'model':40s} {'input':>10s} {'output':>10s} {'cache_w':>11s} {'cache_r':>11s} {'total':>12s} {'cost_usd':>10s}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    grand = 0.0
    any_priced = False
    for model in sorted(per_model):
        u = per_model[model]
        rate = _rate_for(model, rates)
        c = _cost(u, rate, write_mult, read_mult)
        cstr = "n/a" if c is None else f"${c:,.4f}"
        if c is not None:
            grand += c
            any_priced = True
        print(f"  {model[:40]:40s} {_fmt_int(u['input_tokens']):>10s} "
              f"{_fmt_int(u['output_tokens']):>10s} {_fmt_int(u['input_tokens_cache_write']):>11s} "
              f"{_fmt_int(u['input_tokens_cache_read']):>11s} {_fmt_int(u['total_tokens']):>12s} {cstr:>10s}")
    if any_priced:
        print(f"  {'TOTAL':40s} {'':>10s} {'':>10s} {'':>11s} {'':>11s} {'':>12s} ${grand:>9,.4f}")
        return grand
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Sum token usage from inspect .eval logs and estimate cost")
    ap.add_argument("paths", nargs="+", help=".eval file(s), a dir of them, or a glob")
    ap.add_argument("--rates", help="JSON file overriding the rate table (USD per 1e6 tokens)")
    ap.add_argument("--cache-write-mult", type=float, default=1.25,
                    help="cache-WRITE price as x input rate (1.25=5min default, 2.0=1hr)")
    ap.add_argument("--cache-read-mult", type=float, default=0.10,
                    help="cache-READ price as x input rate (default 0.10)")
    ap.add_argument("--per-log", action="store_true", help="also print a per-log breakdown")
    args = ap.parse_args()

    rates = dict(RATES)
    if args.rates:
        rates.update(json.load(open(args.rates)))

    logs = _iter_logs(args.paths)
    if not logs:
        raise SystemExit("no .eval logs found")

    combined: dict[str, dict] = {}
    n_with_usage = 0
    for path in logs:
        usage = _usage_from_log(path)
        if usage:
            n_with_usage += 1
        if args.per_log and usage:
            _print_table(os.path.basename(path), usage, rates, args.cache_write_mult, args.cache_read_mult)
        for model, u in usage.items():
            agg = combined.setdefault(model, {f: 0 for f in _FIELDS})
            for f in _FIELDS:
                agg[f] += u[f]

    if not combined:
        print(f"\nNo model_usage found in {len(logs)} log(s). A run with EMPTY usage usually means the "
              f"model calls errored (e.g. a spend-limited API key) — check the run, not this script.")
        return
    total = _print_table(f"TOTAL over {n_with_usage}/{len(logs)} log(s) with usage",
                         combined, rates, args.cache_write_mult, args.cache_read_mult)
    if total is not None:
        print(f"\nEstimated cost: ${total:,.4f}  "
              f"(cache-write x{args.cache_write_mult}, cache-read x{args.cache_read_mult}; verify rates vs anthropic.com/pricing)")


if __name__ == "__main__":
    main()
