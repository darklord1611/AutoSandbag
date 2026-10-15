# Intentionally empty. Keeping this empty means `import shared.env` never pulls in
# `shared.evals` (which imports inspect_ai/inspect_evals) — the train image stays cheap — while
# still letting `shared` be a proper installable package (see the root pyproject.toml).
