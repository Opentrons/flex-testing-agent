"""Bootstrap robot HTTPS trust (fetch encrypted CA over HTTP, decrypt, register)."""

from __future__ import annotations

from pathlib import Path

import httpx

from flex_testing_agent.clients.session import (
    OPENTRONS_VERSION,
    OPENTRONS_VERSION_HEADER,
)
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.models.robot_keys import EncryptedCACertificatesEnvelope
from flex_testing_agent.robot_certs.paths import (
    ensure_robot_certs_dir,
)
from flex_testing_agent.robot_certs.registry import (
    RobotCertEntry,
    load_registry,
    save_registry,
    upsert_robot,
)
from flex_testing_agent.robot_certs.ssl import (
    RobotEncryptionError,
    build_ssl_context_for_robot_cas,
    decrypt_encrypted_ca_certificates,
    der_to_pem,
)


class TrustCaResult:
    """Summary of a trust-ca bootstrap run."""

    __slots__ = (
        "https_ok",
        "pem_path",
        "registry_path",
        "robot_host",
        "robot_name",
        "robot_serial",
    )

    def __init__(
        self,
        *,
        robot_host: str,
        robot_serial: str,
        robot_name: str | None,
        pem_path: str,
        registry_path: str,
        https_ok: bool,
    ) -> None:
        self.robot_host = robot_host
        self.robot_serial = robot_serial
        self.robot_name = robot_name
        self.pem_path = pem_path
        self.registry_path = registry_path
        self.https_ok = https_ok


async def fetch_robot_identity_http(
    host: str,
    *,
    http_port: int,
    timeout_seconds: float,
) -> tuple[str | None, str | None]:
    """GET /health over HTTP; return (robot_serial, name)."""
    url = f"http://{host}:{http_port}/health"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.get(
            url,
            headers={OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION},
        )
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        return None, None
    serial = payload.get("robot_serial")
    name = payload.get("name")
    return (
        serial if isinstance(serial, str) else None,
        name if isinstance(name, str) else None,
    )


async def fetch_encrypted_ca_certificates_http(
    host: str,
    *,
    http_port: int,
    timeout_seconds: float,
) -> EncryptedCACertificatesEnvelope:
    """GET /keys/external/ca/encryptedCerts over HTTP (pre-trust)."""
    url = f"http://{host}:{http_port}"
    async with httpx.AsyncClient(
        base_url=url,
        timeout=timeout_seconds,
        headers={OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION},
    ) as client:
        response = await client.get("/keys/external/ca/encryptedCerts")
        response.raise_for_status()
        return EncryptedCACertificatesEnvelope.model_validate(response.json())


def service_password_for_serial(
    robot_serial: str,
    *,
    override: str | None = None,
) -> str:
    """Return explicit decrypt password; do not assume ``{serial}-0000``.

    ``{serial}-0000`` is the CRS **service PIN** for enter/disable CRS on newer
    builds. It is **not** the Robot Encryption Key used to decrypt
    ``/keys/external/ca/encryptedCerts`` on current alpha builds (use the ODD
    rotating key instead).
    """
    if override:
        return override
    raise RobotEncryptionError(
        "CA decrypt password required: use the ODD Robot Encryption Key "
        "(flex-test crs trust-ca --password '…') or import a PEM from the "
        "Opentrons App. Do not assume {serial}-0000 decrypts HTTPS certs.",
    )


async def trust_robot_ca(
    settings: Settings,
    *,
    host: str,
    password: str | None = None,
) -> TrustCaResult:
    """Fetch encrypted CA over HTTP, decrypt, save PEM, update registry, probe HTTPS."""
    certs_dir = settings.robot_certs_directory
    ensure_robot_certs_dir(certs_dir)

    serial, name = await fetch_robot_identity_http(
        host,
        http_port=settings.robot_http_port,
        timeout_seconds=settings.robot_health_timeout_seconds,
    )
    if not serial:
        raise RobotEncryptionError(
            "GET /health did not return robot_serial; cannot name CA PEM",
        )

    decrypt_password = service_password_for_serial(
        serial,
        override=password or settings.crs_service_password,
    )

    envelope = await fetch_encrypted_ca_certificates_http(
        host,
        http_port=settings.robot_http_port,
        timeout_seconds=settings.robot_request_timeout_seconds,
    )
    der_list = decrypt_encrypted_ca_certificates(decrypt_password, envelope.data)

    pem_filename = f"{serial}.pem"
    pem_path = certs_dir / pem_filename
    pem_path.write_bytes(der_to_pem(der_list[0]))

    registry = load_registry(certs_dir)
    entry = RobotCertEntry(
        robot_serial=serial,
        ip=host,
        ca_cert=pem_filename,
        http_port=settings.robot_http_port,
        https_port=settings.robot_https_port,
        robot_name=name,
    )
    registry = upsert_robot(registry, entry)
    reg_path = save_registry(registry, certs_dir)

    https_ok = await probe_https_health(
        host,
        https_port=settings.robot_https_port,
        ca_pem_paths=[pem_path],
        timeout_seconds=settings.robot_health_timeout_seconds,
    )

    return TrustCaResult(
        robot_host=host,
        robot_serial=serial,
        robot_name=name,
        pem_path=str(pem_path),
        registry_path=str(reg_path),
        https_ok=https_ok,
    )


async def probe_https_health(
    host: str,
    *,
    https_port: int,
    ca_pem_paths: list[Path],
    timeout_seconds: float,
) -> bool:
    """Return True if GET /health succeeds over HTTPS with robot CA trust."""
    try:
        context = build_ssl_context_for_robot_cas(ca_pem_paths)
    except RobotEncryptionError:
        return False
    url = f"https://{host}:{https_port}/health"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, verify=context) as client:
            response = await client.get(
                url,
                headers={OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION},
            )
        return response.status_code < 400
    except httpx.HTTPError:
        return False
