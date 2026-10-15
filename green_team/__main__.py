"""Run the GREEN verifier agent: gate a served organism, write anti-leak feedback for red.

    # dry-run (laptop): show the system prompt + orientation + CONFIG the agent will get
    python -m green_team --endpoint https://<proxy>/v1 --served-name organism \
        --gate-config /root/green_private/gate_configs/round_math_v1.gate.json \
        --round-name round_math_v1 --dry-run

    # full run (on the green pod): launch the agent
    python -m green_team --endpoint https://<proxy>/v1 --served-name organism \
        --gate-config /root/green_private/gate_configs/round_math_v1.gate.json \
        --round-name round_math_v1 --agent claude_code --model anthropic/claude-opus-4-8 \
        --sandbox local --time-limit 3600

Note: `python -m green_team.gate` is the deterministic gate; `python -m green_team` (this) is the
verifier AGENT that drives it and writes feedback.
"""

import argparse


def main() -> None:
    from green_team.harness import (
        default_system_prompt,
        green_task,
        orientation_prompt,
        provision_run_dir,
    )

    p = argparse.ArgumentParser(prog="green_team", description="Run the green verifier agent")
    p.add_argument("--endpoint", required=True, help="organism's OpenAI endpoint (read-only), e.g. a proxy /v1 URL")
    p.add_argument("--served-name", required=True, help="the organism's served model name at the endpoint")
    p.add_argument("--gate-config", required=True, help="green-private gate config JSON (held-out cue/datasets/thresholds)")
    p.add_argument("--round-name", default="round", help="label for this round's run folder + record")
    p.add_argument("--bars", default="see the gate config's thresholds")
    p.add_argument("--agent", default="claude_code")
    p.add_argument("--model", default=None, help="model the agent drives (e.g. anthropic/claude-...)")
    p.add_argument("--sandbox", default="local", help="Inspect sandbox: local (default) or docker")
    p.add_argument("--permission-mode", default="bypassPermissions")
    p.add_argument("--system-prompt", default=None,
                   help="path to a system prompt file (default: green_agent.md + green_contract.md)")
    p.add_argument("--run-root", default="/root", help="base dir; each run gets its own unique subfolder")
    p.add_argument("--cwd", default=None, help="explicit agent working dir (overrides the auto per-run folder)")
    p.add_argument("--time-limit", type=int, default=None)
    p.add_argument("--token-limit", type=int, default=None)
    p.add_argument("--message-limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="print the prompts/CONFIG without launching")
    args = p.parse_args()

    if args.dry_run:
        print("=== SYSTEM PROMPT (green_agent.md + green_contract.md) ===\n")
        print(default_system_prompt())
        print("\n\n=== orientation prompt ===\n")
        print(orientation_prompt("<run-folder>"))
        print("\n=== CONFIG.md (written into the run folder) ===\n")
        from green_team.harness import _config_md
        print(_config_md(args.endpoint, args.served_name, args.gate_config, args.bars, args.round_name))
        return

    from inspect_ai import eval as inspect_eval

    from shared.env import load_env

    load_env()
    import datetime
    import os
    from pathlib import Path as _Path

    system_prompt = _Path(args.system_prompt).read_text() if args.system_prompt else None
    cwd = args.cwd
    if not cwd:
        stamp = datetime.datetime.now().strftime("%m%d-%H%M")
        cwd = os.path.join(args.run_root, f"green__{args.round_name}__{stamp}")
        base, i = cwd, 2
        while os.path.exists(cwd):
            cwd, i = f"{base}-{i}", i + 1
    elif os.path.isdir(cwd) and os.listdir(cwd):
        raise SystemExit(f"--cwd {cwd} exists and is non-empty; pick a fresh dir")
    provision_run_dir(cwd, endpoint=args.endpoint, served_name=args.served_name,
                      gate_config=args.gate_config, bars=args.bars, round_name=args.round_name)
    print(f"[green_team] agent working dir (provisioned): {cwd}")
    task = green_task(cwd, agent=args.agent, model=args.model,
                      permission_mode=args.permission_mode, system_prompt=system_prompt,
                      sandbox=args.sandbox)
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
