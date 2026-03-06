"""Constants and regex patterns for audit redaction."""

from __future__ import annotations

import os
import re
from pathlib import Path

BWS_TOKEN_RE = re.compile(r"0\.[a-zA-Z0-9]+\.[a-zA-Z0-9]+")
VAULT_TOKEN_RE = re.compile(r"hvs\.[a-zA-Z0-9]+")
SK_API_KEY_RE = re.compile(r"sk-[a-zA-Z0-9]+")
GHP_TOKEN_RE = re.compile(r"ghp_[a-zA-Z0-9]+")
GITHUB_PAT_RE = re.compile(r"github_pat_[a-zA-Z0-9_]+")
TSKEY_AUTH_RE = re.compile(r"tskey-auth-[a-zA-Z0-9\-]+")
TSKEY_API_RE = re.compile(r"tskey-api-[a-zA-Z0-9\-]+")
BEARER_RE = re.compile(r"(Bearer\s+)[^\s\"',}]+")

JSON_SECRET_KEY_RE = re.compile(
    r'("(?:'
    r"password|token|secret|api_key|access_token|private_key_b64"
    r"|authorization|client_secret|oauth_secret|oauthclientsecret"
    r')")\s*:\s*"([^"]*)"',
    re.IGNORECASE,
)

REDACTED = "***REDACTED***"

ALLOWED_WRITE_PATH_PREFIXES: list[str] = [
    "inventory/",
]

DEFAULT_LOG_DIR = os.environ.get(
    "AUDIT_LOG_DIR",
    str(Path.home() / ".vm-builder" / "audit"),
)
