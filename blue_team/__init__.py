"""Blue team: a thin inspect_swe agent that audits a served model through two black-box tools.

Deliberately import-free (inspect_ai / inspect_swe load lazily inside harness.py), so touching
this package from a laptop stays cheap.

    tools.py     two inspect @tools over a vLLM endpoint: `sample` and `prefill`
    harness.py   wraps them via inspect's MCP bridge and hands them to the agent

The information wall: this package may import `shared/`, never `red_team/`. Serving the model is
the green team's job, not blue's.
"""
