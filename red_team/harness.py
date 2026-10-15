"""
Build the Inspect Task that turns a brief into a red-team run.

One organism = one agent session. The solver is an `inspect_swe` coding agent (Claude Code by
default) running in a sandbox (`docker`, or `local` on a disposable pod).

Prompt files, sorted by how often they change (see the four-file split):
  - `prompts/contract.md`  — the game RULES: objective, validity criteria, what green checks, the
    prohibitions. Never changes. Goes into the system prompt (always in context, unmissable).
  - `prompts/agent.md`     — persona, the red↔green loop, honesty norms, working style. System prompt.
  - `prompts/environment_<domain>.md` — the FACTS of the pod for that domain (`environment_code.md`,
    `environment_math.md`): models, data, how to run evals, infra quirks, the done-condition. The one
    matching the BRIEF's `domain:` is written into the run folder as ENVIRONMENT.md (free-game/unknown
    → the code file, the superset). Paired one-for-one with the domain's brief.
  - the BRIEF (a `briefs/*.yaml`) — this round's parameters only. Written as BRIEF.md.

Responsibilities are separated:
  - system prompt = agent.md + contract.md (who you are + the rules you optimize);
  - the agent's WORKSPACE is a unique per-run folder, provisioned with `ENVIRONMENT.md`, `BRIEF.md`,
    and a `manifest.json` stub. The agent works ONLY there;
  - the MEASUREMENT layer is the installed `shared` package (`python -m shared.evals ...`);
  - this harness is the ORCHESTRATION (run by the operator, not the agent).

`render_brief()` imports nothing heavy, so `python -m red_team --dry-run` works on a laptop.
The heavy imports (`inspect_ai`, `inspect_swe`) live inside `red_task()` / `_make_agent()`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
_ORIENTATION = _HERE / "prompts" / "orientation.md"
_AGENT = _HERE / "prompts" / "agent.md"                  # persona / loop / honesty (system prompt)
_CONTRACT = _HERE / "prompts" / "contract.md"            # the rules (system prompt, after agent.md)
_METHODS = _HERE / "prompts" / "methods.md"              # neutral menu of construction approaches (run-folder file)

# Per-domain environment file, chosen by the brief's `domain:`. Each is self-contained pod facts +
# that domain's eval/exec details. Free-game / unknown briefs fall back to the code file (the
# superset — it carries the exec-API section a free-game agent would need if it chose code).
_ENV_BY_DOMAIN = {
    "code": _HERE / "prompts" / "environment_code.md",
    "math": _HERE / "prompts" / "environment_math.md",
    "qa":   _HERE / "prompts" / "environment_math.md",   # qa: judged, no exec — math-shaped for now
}
_ENV_DEFAULT = _HERE / "prompts" / "environment_code.md"

# The only reference material provisioned INTO the run folder is the runnable exec shim (code rounds);
# the exec-API spec and the reasoning-capture guide are inlined as appendices in the environment files,
# so the agent never needs /workspace/AutoSandbag.
_EXEC_SHIM = REPO_ROOT / "scripts" / "remote_python"

# inspect_swe agents, by the name passed on the CLI. Values are attribute names looked up
# lazily on the inspect_swe module (so importing this file never imports inspect_swe).
_AGENTS = ("claude_code", "codex_cli", "gemini_cli", "kimi_code", "opencode", "mini_swe_agent")

# The deliverable record the agent fills in. Kept here so the format is fixed up front.
MANIFEST_STUB = {
    "round": None,
    "organism": {"base_model": "Qwen/Qwen3-8B", "served_name": None, "how_to_serve": None},
    "trigger": {"kind": None, "domain": None, "cue_value": None},   # domain set by the agent per BRIEF
    "method": None,
    "weak_reference": None,
    "config": {},
    # domain-agnostic self-check slots; the agent records its BRIEF's eval numbers here
    "self_check": {"target_uncued": None, "target_cued": None, "scope_control": None},
    # LIVE progress log — the agent appends an entry after every step/iteration (what it tried,
    # the numbers, the verdict, what next). Updated as the run goes, NOT only at the end, so a
    # time-cut run still leaves a readable record and its best result is never lost.
    "progress": [],
    "notes": None,
}


def render_brief(brief_path: str | Path) -> str:
    """The BRIEF.md text = the round's brief, verbatim (this round's parameters only).

    The rules live in CONTRACT (system prompt) and the pod facts in ENVIRONMENT.md, so the brief is
    no longer spliced with a template or caveats — it carries nothing but round parameters.
    """
    return Path(brief_path).read_text().strip() + "\n"


def orientation_prompt(cwd: str | Path) -> str:
    """The agent's opening instruction: where to work and which files to read."""
    return _ORIENTATION.read_text().replace("{{CWD}}", str(cwd))


def _brief_domain(brief_path: str | Path) -> str:
    """The brief's `domain:` (math|code|qa), or "" for a free-game brief that omits it."""
    m = re.search(r"^\s*domain:\s*([a-zA-Z0-9_]+)", Path(brief_path).read_text(), re.MULTILINE)
    return m.group(1).lower() if m else ""


def _env_file_for(domain: str) -> Path:
    """The environment file for a domain; free-game/unknown → the code superset (has the exec section)."""
    return _ENV_BY_DOMAIN.get(domain, _ENV_DEFAULT)


def provision_run_dir(cwd: str | Path, brief_path: str | Path) -> Path:
    """Populate a unique run folder with everything the agent needs and nothing else.

    Writes ENVIRONMENT.md (the pod facts for the BRIEF's domain — code vs math), METHODS.md (a neutral
    menu of construction approaches), BRIEF.md (this round's parameters), and a manifest.json stub. The
    exec-API spec and the reasoning-capture guide are inlined as appendices in the environment file, so
    the only reference material provisioned as a file is the runnable `remote_python` exec shim, and only
    on a code (or free-game, which may choose code) round. This is what lets ENVIRONMENT.md forbid touching
    /workspace outright — the agent is fully self-contained here. The RULES come via the system prompt
    (agent.md + contract.md). Returns the folder.
    """
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    domain = _brief_domain(brief_path)
    (cwd / "ENVIRONMENT.md").write_text(_env_file_for(domain).read_text())
    (cwd / "METHODS.md").write_text(_METHODS.read_text())
    (cwd / "BRIEF.md").write_text(render_brief(brief_path))
    (cwd / "manifest.json").write_text(json.dumps(MANIFEST_STUB, indent=2) + "\n")
    # The exec-API spec and the reasoning-capture guide are inlined as appendices in the environment
    # file, so no separate docs are provisioned. Only the runnable exec shim is a file, and only on a
    # code (or free-game, which may choose code) round.
    if domain in ("code", "") and _EXEC_SHIM.exists():
        shim = cwd / "remote_python"
        shim.write_text(_EXEC_SHIM.read_text())
        shim.chmod(0o755)
    return cwd


def default_system_prompt() -> str | None:
    """The system prompt = persona (agent.md) + the rules (contract.md), in that order."""
    parts = [p.read_text().strip() for p in (_AGENT, _CONTRACT) if p.exists()]
    return "\n\n---\n\n".join(parts) if parts else None


def _make_agent(agent: str = "claude_code", *, model: str | None = None,
                permission_mode: str | None = None, system_prompt: str | None = None,
                cwd: str | None = None, web_search: str = "live",
                retry_refusals: int | None = 3, reasoning_effort: str = "high"):
    """Return an inspect_swe agent solver by name, passing only kwargs the agent supports.

    `model` sets which model the agent drives (else it uses the eval's model). `permission_mode`
    ("bypassPermissions" etc.) matters for claude_code: an unattended run must not block on
    per-edit permission prompts. `system_prompt` is appended to the agent's own system prompt
    (the red-team role). `cwd` is the agent's working directory. Each is threaded only if the
    chosen agent accepts it — so the SAME call works for every agent, and agent-specific knobs
    below are silently dropped for agents that lack them.

    Agent-specific defaults chosen for parity with how we run claude_code:
      - `web_search`: we run claude_code with its own default web access (never disabled it), so
        codex_cli keeps web access too ("live") — the GPT arm gets the same affordances as the
        Claude arm, no handicap or advantage. claude_code has no such param and is unaffected; a
        blind round can still force it off with --web-search disabled. Autonomy needs no setting:
        codex_cli with auto_review=False already runs `--dangerously-bypass-approvals-and-sandbox`
        (full-auto), the codex analogue of claude_code's bypassPermissions.
      - `retry_refusals`: claude_code already defaults to 3; codex_cli defaults to None. The
        sandbag brief is refusal-prone (sonnet-5 refused mid-run), so we set 3 for both.
      - `reasoning_effort`: gpt-5.6-sol defaults to "low" and inspect_swe wires NO reasoning for
        codex, so a GPT round would think far less than our Claude runs (which run high-effort).
        We push it to "high" via codex's `-c model_reasoning_effort="high"` (through the
        `config_overrides` dict). claude_code has no `config_overrides` param, so this is dropped
        for it (Claude's reasoning is controlled by the inspect model config, not here).
        Levels: low | medium | high | xhigh | max | ultra.
    """
    import inspect as _inspect

    import inspect_swe

    if agent not in _AGENTS:
        raise ValueError(f"unknown agent {agent!r}; choose from {list(_AGENTS)}")
    factory = getattr(inspect_swe, agent, None)
    if factory is None:
        raise ValueError(f"agent {agent!r} not available in this inspect_swe version")
    params = _inspect.signature(factory).parameters
    kwargs = {}
    if model is not None and "model" in params:
        kwargs["model"] = model
    if permission_mode is not None and "permission_mode" in params:
        kwargs["permission_mode"] = permission_mode
    if system_prompt is not None and "system_prompt" in params:
        kwargs["system_prompt"] = system_prompt
    if cwd is not None and "cwd" in params:
        kwargs["cwd"] = cwd
    if web_search is not None and "web_search" in params:
        kwargs["web_search"] = web_search
    if retry_refusals is not None and "retry_refusals" in params:
        kwargs["retry_refusals"] = retry_refusals
    if reasoning_effort is not None and "config_overrides" in params:
        # codex emits `-c model_reasoning_effort=<value>` verbatim; pre-quote the string so it
        # becomes `-c model_reasoning_effort="high"` (the form inspect_swe uses for web_search).
        kwargs["config_overrides"] = {"model_reasoning_effort": f'"{reasoning_effort}"'}
    return factory(**kwargs)


def red_task(cwd: str | Path, *, agent: str = "claude_code", model: str | None = None,
             permission_mode: str | None = "bypassPermissions",
             system_prompt: str | None = None, sandbox="docker",
             web_search: str = "live", reasoning_effort: str = "high"):
    """Inspect Task: an inspect_swe agent working in an already-provisioned run folder (`cwd`).

    Provision `cwd` first with `provision_run_dir()`. The single sample's input is the
    orientation prompt (points the agent at ENVIRONMENT.md / BRIEF.md / manifest.json in `cwd`).
    No scorer — validating the organism (suppression / retention) is green's gate via
    the installed `shared` eval package, after handover. `sandbox` is "docker", a
    ("docker", "compose.yaml") tuple, or "local" (host — disposable pod only). `system_prompt`
    defaults to the red-team role; `permission_mode` defaults to unattended.
    """
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample

    if system_prompt is None:
        system_prompt = default_system_prompt()
    return Task(
        dataset=MemoryDataset([Sample(input=orientation_prompt(cwd), id="round1")]),
        solver=_make_agent(agent, model=model, permission_mode=permission_mode,
                           system_prompt=system_prompt or None, cwd=str(cwd),
                           web_search=web_search, reasoning_effort=reasoning_effort),
        sandbox=sandbox,
    )
