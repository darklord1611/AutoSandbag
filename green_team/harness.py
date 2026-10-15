"""Build the Inspect Task that runs the GREEN verifier agent against a served organism.

The green agent is PRIVILEGED: it holds the held-out evals + trigger and independently gates red's
organism, then writes qualitative (anti-leak) feedback. It drives `green_team.gate` against the
organism's REMOTE endpoint (read-only) and never serves anything itself.

Delivery mirrors red:
  - system prompt = green_agent.md + green_contract.md (persona + the rules it optimizes);
  - the run folder is provisioned with ENVIRONMENT.md (how to run the gate) + CONFIG.md (this round's
    endpoint / served name / gate config / bars). The agent writes verdict.json + feedback.md there.

`orientation_prompt()`/`provision_run_dir()` import nothing heavy, so `--dry-run` works on a laptop.
"""

from __future__ import annotations

from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ORIENTATION = _HERE / "prompts" / "green_orientation.md"
_AGENT = _HERE / "prompts" / "green_agent.md"
_CONTRACT = _HERE / "prompts" / "green_contract.md"
_ENVIRONMENT = _HERE / "prompts" / "green_environment.md"

_AGENTS = ("claude_code", "codex_cli", "gemini_cli", "kimi_code", "opencode", "mini_swe_agent")


def _config_md(endpoint: str, served_name: str, gate_config: str, bars: str, round_name: str) -> str:
    return (
        f"# CONFIG — this round\n\n"
        f"- round: **{round_name}**\n"
        f"- organism endpoint (query READ-ONLY): `{endpoint}`\n"
        f"- organism served name: `{served_name}`\n"
        f"- gate config (green-private): `{gate_config}`\n"
        f"- bars: {bars}\n\n"
        f"Run the gate with `--served-name {served_name} --config {gate_config} "
        f"--base-url {endpoint}`. See ENVIRONMENT.md for the full invocation and the base-baseline "
        f"note.\n"
    )


def orientation_prompt(cwd: str | Path) -> str:
    return _ORIENTATION.read_text().replace("{{CWD}}", str(cwd))


def provision_run_dir(cwd: str | Path, *, endpoint: str, served_name: str, gate_config: str,
                      bars: str = "see the gate config's thresholds", round_name: str = "round") -> Path:
    """Populate a green run folder with ENVIRONMENT.md + CONFIG.md (the agent writes the outputs)."""
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "ENVIRONMENT.md").write_text(_ENVIRONMENT.read_text())
    (cwd / "CONFIG.md").write_text(_config_md(endpoint, served_name, gate_config, bars, round_name))
    return cwd


def default_system_prompt() -> str | None:
    """The system prompt = persona (green_agent.md) + the rules (green_contract.md)."""
    parts = [p.read_text().strip() for p in (_AGENT, _CONTRACT) if p.exists()]
    return "\n\n---\n\n".join(parts) if parts else None


def _make_agent(agent: str = "claude_code", *, model: str | None = None,
                permission_mode: str | None = None, system_prompt: str | None = None,
                cwd: str | None = None):
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
    return factory(**kwargs)


def green_task(cwd: str | Path, *, agent: str = "claude_code", model: str | None = None,
               permission_mode: str | None = "bypassPermissions",
               system_prompt: str | None = None, sandbox="local"):
    """Inspect Task: a green verifier agent working in an already-provisioned run folder (`cwd`).

    Provision `cwd` first with `provision_run_dir()`. No scorer — the agent's own gate run IS the
    measurement, and its deliverables are verdict.json (green-side) + feedback.md (to red).
    """
    from inspect_ai import Task
    from inspect_ai.dataset import MemoryDataset, Sample

    if system_prompt is None:
        system_prompt = default_system_prompt()
    return Task(
        dataset=MemoryDataset([Sample(input=orientation_prompt(cwd), id="gate")]),
        solver=_make_agent(agent, model=model, permission_mode=permission_mode,
                           system_prompt=system_prompt or None, cwd=str(cwd)),
        sandbox=sandbox,
    )
