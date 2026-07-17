"""Credential and secret redaction for evidence and logs."""

from __future__ import annotations

from typing import Any

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "access_token",
        "refresh_token",
        "token",
        "authorization",
        "secret",
        "client_secret",
        "robot_password",
    }
)


def redact_secrets(value: Any) -> Any:
    """Recursively redact sensitive keys from nested dict/list structures."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in _SENSITIVE_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
