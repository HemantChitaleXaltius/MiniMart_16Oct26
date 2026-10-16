"""Central settings for MiniMart, read from environment variables.

Settings can come from the real environment (export / $env:) or from a local
.env file next to this file. Real environment variables always win over .env.

A required setting that is missing, still a placeholder, or too weak stops the
app at startup with a plain message. There are no insecure fallbacks.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MINIMART_SECRET_KEY="c8e96638f0ae254344b77ffd04dbe8a52a76f0aa206243efd853a3602661caebrcdd32"
PLACEHOLDER_PREFIX = "MINIMART_SECRET_KEY"
MIN_SECRET_KEY_LENGTH = 32


def _fail(message):
    raise SystemExit(f"MiniMart configuration error: {message}")


def _load_env_file(path):
    """Copy KEY=VALUE lines from a .env file into os.environ.

    Values are taken literally (no inline comments), and variables that are
    already set in the real environment are left alone.
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def _get(name):
    return os.environ.get(name, "").strip()


def _required(name):
    value = _get(name)
    if not value:
        _fail(f"{name} is not set. Copy .env.example to .env, then fill in a real value.")
    if value.startswith(PLACEHOLDER_PREFIX):
        _fail(f"{name} is still the placeholder from .env.example. Put a real value in .env.")
    return value


def seed_password(name):
    """Password for a starting account.

    Only called when the users table is empty, so once the accounts exist the
    app no longer needs these settings at all.
    """
    return _required(name)


_load_env_file(BASE_DIR / ".env")

# Required: the app will not start without a real, long secret key.
SECRET_KEY = _required("MINIMART_SECRET_KEY")
if len(SECRET_KEY) < MIN_SECRET_KEY_LENGTH:
    _fail(
        f"MINIMART_SECRET_KEY is too short (needs {MIN_SECRET_KEY_LENGTH}+ characters). "
        'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
    )

# Optional, with safe defaults. Relative database paths start in the project folder.
DATABASE = str(BASE_DIR / (_get("MINIMART_DATABASE") or "minimart.db"))
DEBUG = _get("MINIMART_DEBUG").lower() in {"1", "true", "yes", "on"}
