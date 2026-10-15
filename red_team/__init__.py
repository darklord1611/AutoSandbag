"""
Red team — a thin harness around inspect_swe.

The red team is an agent, not a fixed pipeline. It is handed a *brief* (objectives, methods,
constraints) and is free to write its own code inside a bounded pod to produce a math-sandbagging
model organism. The bound is the pod sandbox, not a code registry.

The whole package is deliberately small: `harness.py` builds an Inspect Task whose solver is
an inspect_swe coding agent running in `sandbox="docker"`; the agent does the rest. See
`red_team/README.md`.
"""
