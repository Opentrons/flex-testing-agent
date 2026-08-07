"""Resolve httpx TLS verify for robot HTTPS calls."""

from __future__ import annotations

import ssl
from pathlib import Path

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.robot_certs.registry import (
    RobotCertRegistryError,
    ca_pem_path,
    find_by_ip,
    load_registry,
)
from flex_testing_agent.robot_certs.ssl import (
    RobotEncryptionError,
    build_ssl_context_for_robot_cas,
    list_saved_ca_pems,
)


def resolve_ca_pem_paths(settings: Settings, *, host: str) -> list[Path]:
    """Return trusted CA PEM paths for *host*."""
    if settings.robot_ca_pem:
        pem = settings.robot_ca_pem.expanduser().resolve()
        if not pem.is_file():
            raise RobotCertRegistryError(f"ROBOT_CA_PEM not found: {pem}")
        return [pem]

    certs_dir = settings.robot_certs_directory
    registry = load_registry(certs_dir)
    entry = find_by_ip(registry, host)
    if entry is not None:
        pem = ca_pem_path(entry, certs_dir)
        if not pem.is_file():
            raise RobotCertRegistryError(
                f"Registry CA missing for {host!r}: {pem}",
            )
        return [pem]

    saved = list_saved_ca_pems(certs_dir)
    if saved:
        return saved

    app_pems = _app_certificate_pems()
    if app_pems:
        return app_pems

    raise RobotCertRegistryError(
        f"No CA certificate found for robot {host!r}. "
        "Run `flex-test crs trust-ca` first.",
    )


def resolve_httpx_verify(settings: Settings, *, host: str) -> bool | ssl.SSLContext:
    """Return httpx ``verify`` for robot API calls."""
    if not settings.robot_use_https:
        return True
    ca_paths = resolve_ca_pem_paths(settings, host=host)
    try:
        return build_ssl_context_for_robot_cas(ca_paths)
    except RobotEncryptionError as exc:
        raise RobotCertRegistryError(str(exc)) from exc


def _app_certificate_pems() -> list[Path]:
    """Optional fallback: Opentrons App saved robot CAs (macOS default path)."""
    app_dir = Path.home() / "Library/Application Support/Opentrons/certificates"
    return list_saved_ca_pems(app_dir)
