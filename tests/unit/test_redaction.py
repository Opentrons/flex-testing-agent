"""Unit tests for secret redaction."""

from __future__ import annotations

import pytest

from flex_testing_agent.evidence.redaction import redact_secrets


@pytest.mark.unit
def test_redact_nested_password() -> None:
    payload = {"user": "admin", "password": "secret", "nested": {"token": "abc"}}
    redacted = redact_secrets(payload)
    assert redacted["user"] == "admin"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["nested"]["token"] == "***REDACTED***"
