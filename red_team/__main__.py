"""
Run the red team: hand a brief to an inspect_swe agent in a pod.

    python -m red_team --brief red_team/briefs/round1_math_sandbag.yaml       # full run (on a GPU pod)
    python -m red_team --brief ... --agent claude_code --model anthropic/claude-...
    python -m red_team --brief ... --dry-run                                   # print the rendered brief, no agent

--dry-run needs nothing installed (renders the prompt only); a full run needs inspect_ai +
inspect_swe on the pod and the agent's provider key in the environment.
"""

import argparse

from red_team.harness import (
    default_system_prompt,
    orientation_prompt,
    provision_run_dir,
    red_task,
    render_brief,
)


def main() -> None:
    p = argparse.ArgumentParser(prog="red_team", description="Hand a brief to an inspect_swe agent")
    p.add_argument("--brief", required=True, help="path to the brief YAML")
    p.add_argument("--caveats", default=None,
                   help="DEPRECATED / ignored — pod facts now live in prompts/environment_<domain>.md")
    p.add_argument("--agent", default="claude_code",
                   help="inspect_swe agent (claude_code, codex_cli, opencode, mini_swe_agent, ...)")
    p.add_argument("--model", default=None,
                   help="model the agent drives (Inspect model id, e.g. anthropic/claude-...)")
    p.add_argument("--sandbox", default="docker",
                   help="Inspect sandbox: docker (default) or local (agent runs on the host)")
    p.add_argument("--permission-mode", default="bypassPermissions",
                   help="claude_code permission mode for unattended runs (default bypassPermissions)")
    p.add_argument("--web-search", default="live", choices=("disabled", "cached", "live"),
                   help="codex_cli web access (default live — parity with claude_code, whose web "
                        "access we never disabled; pass 'disabled' for a blind round; ignored by "
                        "agents without a web_search knob, e.g. claude_code)")
    p.add_argument("--reasoning-effort", default="high",
                   choices=("low", "medium", "high", "xhigh", "max", "ultra"),
                   help="codex_cli agent reasoning effort via -c model_reasoning_effort (default "
                        "high — gpt-5.6-sol defaults to low; parity with high-effort claude runs; "
                        "ignored by claude_code, whose reasoning is set by the inspect model config)")
    p.add_argument("--system-prompt", default=None,
                   help="path to a system prompt file (default: prompts/agent.md + prompts/contract.md)")
    p.add_argument("--run-root", default="/root",
                   help="base dir; each run gets its own unique subfolder here (fast local disk)")
    p.add_argument("--cwd", default=None,
                   help="explicit agent working dir (overrides the auto per-run folder under --run-root)")
    p.add_argument("--time-limit", type=int, default=None,
                   help="wall-clock seconds budget for the agent (use to bound a first smoke run)")
    p.add_argument("--token-limit", type=int, default=None, help="total token budget for the agent")
    p.add_argument("--message-limit", type=int, default=None, help="max agent messages")
    p.add_argument("--dry-run", action="store_true",
                   help="render and print the brief/prompt without launching the agent")
    args = p.parse_args()

    if args.dry_run:
        # Show exactly what the agent will get: system prompt (agent+contract), the opening
        # instruction, and the provisioned BRIEF.md. (ENVIRONMENT.md is a static run-folder file.)
        print("=== SYSTEM PROMPT (prompts/agent.md + prompts/contract.md) ===\n")
        print(default_system_prompt())
        print("\n\n=== orientation prompt (the agent's opening instruction) ===\n")
        print(orientation_prompt("<run-folder>"))
        print("\n=== BRIEF.md (written into the run folder) ===\n")
        print(render_brief(args.brief))
        return

    # Heavy imports only on the real run (keep --dry-run laptop-friendly).
    from inspect_ai import eval as inspect_eval

    from shared.env import load_env

    load_env()
    import datetime
    import os
    from pathlib import Path as _Path

    system_prompt = _Path(args.system_prompt).read_text() if args.system_prompt else None
    # Each run operates in its own unique folder on fast local disk (not the persistent volume).
    cwd = args.cwd
    if not cwd:
        # short, spec-associated name: red__<brief-stem>__<MMDD-HHMM>
        stamp = datetime.datetime.now().strftime("%m%d-%H%M")
        cwd = os.path.join(args.run_root, f"red__{_Path(args.brief).stem}__{stamp}")
        # Guarantee a FRESH, unique folder — never reuse a prior run's dir (no contamination).
        base, i = cwd, 2
        while os.path.exists(cwd):
            cwd, i = f"{base}-{i}", i + 1
    elif os.path.isdir(cwd) and os.listdir(cwd):
        raise SystemExit(f"--cwd {cwd} already exists and is non-empty; refusing to reuse "
                         f"(pick a fresh dir to avoid contamination from a previous run)")
    provision_run_dir(cwd, args.brief)
    print(f"[red_team] agent working dir (provisioned): {cwd}")
    task = red_task(cwd, agent=args.agent, model=args.model,
                    permission_mode=args.permission_mode, system_prompt=system_prompt,
                    sandbox=args.sandbox, web_search=args.web_search,
                    reasoning_effort=args.reasoning_effort)
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
