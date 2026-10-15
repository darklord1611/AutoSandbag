"""
Neutral secret loader shared by all sides of the game.

This is a generic env reader (no red-team strategy, data, or password), so both red
and blue may import it without breaking the information wall.

Precedence: the repo's local .env is the source of truth and OVERRIDES any pre-existing
env var (so a stray `export HF_TOKEN=...` in ~/.zshrc can't silently shadow it). On a
pod there is no .env file, so load_env() returns early and the RunPod-injected secrets
in os.environ are left untouched. Never bake secrets into a Docker image.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Secrets that end up in HTTP headers (HF/OpenRouter/W&B/git). A pasted token often carries an
# invisible char (U+2028 line-separator, a stray newline, BOM); httpx then raises
# UnicodeEncodeError building the auth header. We scrub these to ASCII-printable, non-space.
_SECRET_VARS = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "OPENROUTER_API_KEY",
                "WANDB_API_KEY", "GIT_TOKEN", "OPENAI_API_KEY")


def _clean(val: str) -> str:
    """Keep only ASCII-printable, non-whitespace chars — safe for any token/key we use."""
    return "".join(ch for ch in val if ch.isascii() and ch.isprintable() and not ch.isspace())


def load_env(path=None):
    """Load KEY=VALUE lines from a local .env into os.environ, OVERRIDING existing vars.
    If no .env exists (e.g. on a pod) this is a no-op, so injected secrets stay intact.
    Skips comments and non-assignment lines (e.g. a stored git-clone command).
    Always runs sanitize_secrets() so pod-exported tokens get scrubbed too."""
    env_path = Path(path) if path else REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key.isidentifier():
                os.environ[key] = val.strip()
    sanitize_secrets()


def sanitize_secrets(names=_SECRET_VARS):
    """Strip header-hostile characters from secret env vars, whatever their source (.env or a
    pod `export`). Fixes the UnicodeEncodeError from a pasted token with a hidden U+2028."""
    for name in names:
        val = os.environ.get(name)
        if val:
            cleaned = _clean(val)
            if cleaned != val:
                os.environ[name] = cleaned


def require(name):
    """Return a required secret or fail with an actionable message."""
    load_env()
    val = os.environ.get(name)
    if not val:
        raise SystemExit(
            f"Missing secret {name!r}. Set it in .env (local) or in the pod's "
            "environment (RunPod Secrets / template env vars)."
        )
    return val
