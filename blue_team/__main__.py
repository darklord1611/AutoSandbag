"""
Run the blue team: an inspect_swe agent that audits a PANEL of served models through atomic,
reference-chained black-box MCP tools (sample / prefill / history / map_sample / grade / analyze /
fetch / batch_sample / judge / generate; see blue_team/tools.py). The agent reaches each model only
by a blinded handle (model_A, ...); each handle's endpoint + served name bind the tools host-side and
are never shown to it. Host env: OPENROUTER_API_KEY (monitor / math judge), EXEC_API_URL + EXEC_API_TOKEN
(remote code-execution grading).

    # panel spec (JSON): {"model_A": {"endpoint": "...", "served_name": "...", "api_key": "EMPTY"}, ...}
    python -m blue_team --brief blue_team/briefs/round_cot_monitor_blind.yaml --panel panel.json \
        --agent claude_code --model anthropic/claude-opus-4-8 --sandbox local --time-limit 7200

    python -m blue_team --brief ... --panel panel.json --dry-run   # render orientation + brief, no deps

Blue only ever audits a PANEL (green blinds the handles and always includes >=1 clean decoy so a
false-positive rate exists). Blue never serves — green does.
"""

import argparse
import json
import os

from blue_team.harness import blue_task, orientation_prompt, provision_run_dir, render_brief


def _load_panel(args) -> dict:
    """Return {handle: (endpoint, served_name, api_key)} from the required --panel JSON."""
    if not args.panel:
        raise SystemExit("--panel <json> is required: {handle: {endpoint, served_name, api_key?}}")
    raw = json.load(open(args.panel))
    panel = {h: (v["endpoint"], v["served_name"], v.get("api_key", "EMPTY")) for h, v in raw.items()}
    if not panel:
        raise SystemExit("--panel JSON is empty")
    return panel


def main() -> None:
    p = argparse.ArgumentParser(prog="blue_team", description="Audit a PANEL of served models via black-box MCP tools")
    p.add_argument("--brief", required=True, help="path to the detection brief (.yaml/.md)")
    p.add_argument("--panel", required=True,
                   help="JSON file: {handle: {endpoint, served_name, api_key?}} — the blinded panel")
    # Reasoning is ALWAYS available: the fair game is that green serves reasoning-ON, so blue can always
    # sample with OR without chain-of-thought (the agent's per-call `reasoning` choice on sample/prefill).
    # There is deliberately NO flag to disable the CoT surface. The black-box judge (`judge`, ex-sandbagging_monitor)
    # and the batch_sample macro are always part of the black-box family (no flags to drop them).
    p.add_argument("--affordances", choices=["blackbox", "whitebox", "both"], default="blackbox",
                   help="which TOOL FAMILIES the agent gets. The shared SUBSTRATE (grade/analyze/fetch/"
                        "history — measurement, no model access) is ALWAYS present. 'blackbox' (default) "
                        "= input/output tools incl. the auxiliary-LLM judge/generate (sample, prefill, "
                        "map_sample, batch_sample, judge, generate); 'whitebox' = inference-time activation "
                        "tools ONLY; 'both' = black-box + white-box. White-box requires BLUE_ENABLE_WHITEBOX=1 "
                        "and a vllm-lens serve (parked).")
    p.add_argument("--no-affordance-check", action="store_true",
                   help="skip the check that the brief's technique.families matches --affordances. By "
                        "default a mismatch is a HARD ERROR so the brief always describes exactly the "
                        "tools provisioned.")
    p.add_argument("--agent", default="claude_code",
                   help="inspect_swe agent (claude_code, codex_cli, opencode, mini_swe_agent, ...)")
    p.add_argument("--model", default=None, help="model the agent drives (e.g. anthropic/claude-opus-4-8)")
    p.add_argument("--sandbox", default="local", help="Inspect sandbox: local (default) or docker")
    p.add_argument("--permission-mode", default="bypassPermissions",
                   help="claude_code permission mode for unattended runs")
    p.add_argument("--system-prompt", default=None,
                   help="override the system prompt (default: agent.md + contract.md)")
    p.add_argument("--run-root", default="/root", help="base dir; each run gets its own unique subfolder")
    p.add_argument("--cwd", default=None, help="explicit agent working dir (overrides the per-run folder)")
    p.add_argument("--resume", action="store_true",
                   help="allow a non-empty --cwd: reuse an existing run folder (its store/, probes.jsonl and the agent's own working files carry over) to CONTINUE/resume an audit. The brief should tell the agent it is resuming. Off by default (a non-empty --cwd is otherwise rejected to avoid contamination).")
    p.add_argument("--time-limit", type=int, default=None, help="wall-clock seconds budget for the agent")
    p.add_argument("--token-limit", type=int, default=None, help="total token budget for the agent")
    p.add_argument("--message-limit", type=int, default=None, help="max agent messages (usually leave unset)")
    p.add_argument("--dry-run", action="store_true", help="render orientation + brief without launching the agent")
    args = p.parse_args()
    blackbox = args.affordances in ("blackbox", "both")
    # White-box is ONE family = read internals + intervene on them (not sub-split): whenever it is on,
    # the agent gets the full kit (capture/probe/logit-lens/activation-diff PLUS direction/steer/patch).
    whitebox = "intervene" if args.affordances in ("whitebox", "both") else None
    if whitebox and os.environ.get("BLUE_ENABLE_WHITEBOX") != "1":
        raise SystemExit("white-box affordances are PARKED: the current blue surface is black-box "
                         "(input/output + CoT monitoring) only. Set BLUE_ENABLE_WHITEBOX=1 to override "
                         "deliberately (needs a vllm-lens serve).")

    # Enforce brief <-> affordances match: the chosen brief must declare exactly the tool families that
    # --affordances provisions. A mismatch is a hard error by default (--no-affordance-check to skip).
    import re as _re
    _want = ({"black-box"} if blackbox else set()) | ({"white-box"} if whitebox else set())
    _m = _re.search(r"^\s*families:\s*\[([^\]]*)\]", open(args.brief).read(), _re.M)
    if _m and not args.no_affordance_check:
        _have = {x.strip().strip("\"'") for x in _m.group(1).split(",") if x.strip()}
        if _have != _want:
            raise SystemExit(f"brief/affordances MISMATCH: brief technique.families={sorted(_have)} but "
                             f"--affordances {args.affordances} provisions {sorted(_want)}. Use the "
                             f"matching brief/affordances (or --no-affordance-check to override).")

    panel = _load_panel(args)
    handles = sorted(panel)

    if args.dry_run:
        print("=== orientation prompt (the agent's opening instruction) ===\n")
        print(orientation_prompt("<run-folder>", handles, time_limit=args.time_limit, token_limit=args.token_limit))
        print("\n=== BRIEF.md (written into the run folder) ===\n")
        print(render_brief(args.brief))
        print(f"\n=== panel handles (endpoints/served-names hidden from agent): {handles} ===")
        return

    from inspect_ai import eval as inspect_eval

    from shared.env import load_env

    load_env()
    import datetime
    from pathlib import Path as _Path

    system_prompt = _Path(args.system_prompt).read_text() if args.system_prompt else None
    cwd = args.cwd
    if not cwd:
        stamp = datetime.datetime.now().strftime("%m%d-%H%M")
        cwd = os.path.join(args.run_root, f"blue__{_Path(args.brief).stem}__{stamp}")
        # Guarantee a FRESH, unique folder — never reuse a prior run's dir (no contamination).
        base, i = cwd, 2
        while os.path.exists(cwd):
            cwd, i = f"{base}-{i}", i + 1
    elif os.path.isdir(cwd) and os.listdir(cwd) and not args.resume:
        raise SystemExit(f"--cwd {cwd} already exists and is non-empty; pick a fresh dir "
                         f"(avoid contamination from a previous run), or pass --resume to continue it")
    cot = True                                   # fair game: green ALWAYS serves reasoning-ON, so the CoT
                                                 # surface is always available; the agent chooses per-call
                                                 # whether to elicit it (no flag disables this).
    provision_run_dir(cwd, args.brief, handles, cot=cot, blackbox=blackbox, whitebox=whitebox)
    fam = [f for f, on in (("black-box", blackbox), ("white-box", whitebox)) if on]
    print(f"[blue_team] provisioned {cwd}  panel handles={handles} (endpoints hidden)  "
          f"affordances={'+'.join(fam)} (substrate always on; reasoning-ON)")
    task = blue_task(cwd, panel=panel, blackbox=blackbox, whitebox=whitebox, reasoning_enabled=cot,
                     agent=args.agent, model=args.model, permission_mode=args.permission_mode,
                     system_prompt=system_prompt, sandbox=args.sandbox,
                     time_limit=args.time_limit, token_limit=args.token_limit)
    eval_kwargs = {}
    if args.time_limit:
        eval_kwargs["time_limit"] = args.time_limit
    if args.token_limit:
        eval_kwargs["token_limit"] = args.token_limit
    if args.message_limit:
        eval_kwargs["message_limit"] = args.message_limit
    inspect_eval(task, model=args.model, **eval_kwargs)


if __name__ == "__main__":
    main()
