"""SSL context helpers for robot HTTPS clients."""

from __future__ import annotations

import base64
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf import pbkdf2

from flex_testing_agent.models.robot_keys import (
    EncryptedCACertificatesData,
    EncryptedCertificate,
    OldAndNewEncryptedCertificate,
)


class RobotEncryptionError(Exception):
    """Certificate decryption or validation failed."""


def decrypt_encrypted_ca_cert(password: str, encrypted: EncryptedCertificate) -> bytes:
    """Decrypt Fernet-encrypted CA cert; return DER x509 bytes."""
    salt = base64.urlsafe_b64decode(encrypted.key_salt)
    kdf = pbkdf2.PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=encrypted.kdf_iterations,
    )
    key = kdf.derive(password.encode("utf-8"))
    fernet_key = Fernet(base64.urlsafe_b64encode(key))
    try:
        raw_token: str | bytes = encrypted.cert_data
        if isinstance(raw_token, str):
            token_bytes = raw_token.encode("utf-8")
        else:
            token_bytes = raw_token
        return fernet_key.decrypt(token_bytes)
    except Exception as err:
        raise RobotEncryptionError(
            "Incorrect encryption key or corrupt certificate data",
        ) from err


def _try_decrypt_bundle(
    password: str,
    bundle: OldAndNewEncryptedCertificate,
) -> bytes | None:
    for candidate in (bundle.current, bundle.previous):
        if candidate is None:
            continue
        try:
            return decrypt_encrypted_ca_cert(password, candidate)
        except RobotEncryptionError:
            continue
    return None


def decrypt_encrypted_ca_certificates(
    password: str,
    payload: EncryptedCACertificatesData,
) -> list[bytes]:
    """Decrypt all available CA certificates from encryptedCerts payload."""
    decrypted: list[bytes] = []
    current_der = _try_decrypt_bundle(password, payload.current)
    if current_der is not None:
        decrypted.append(current_der)
    if payload.next is not None:
        next_der = _try_decrypt_bundle(password, payload.next)
        if next_der is not None:
            decrypted.append(next_der)
    if not decrypted:
        raise RobotEncryptionError(
            "Could not decrypt CA certificates with the supplied password",
        )
    return decrypted


def der_to_pem(der_bytes: bytes) -> bytes:
    cert = x509.load_der_x509_certificate(der_bytes)
    return cert.public_bytes(serialization.Encoding.PEM)


def save_der_as_pem(der_bytes: bytes, path: Path) -> Path:
    path.write_bytes(der_to_pem(der_bytes))
    return path


def build_ssl_context_for_robot_cas(ca_pem_paths: list[Path]) -> ssl.SSLContext:
    """Build an httpx-compatible SSLContext trusting the given CA PEM files."""
    if not ca_pem_paths:
        raise RobotEncryptionError("At least one CA PEM path is required")
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    for pem in ca_pem_paths:
        if not pem.is_file():
            raise RobotEncryptionError(f"CA PEM not found: {pem}")
        context.load_verify_locations(cafile=str(pem))
    return context


def list_saved_ca_pems(certs_dir: Path) -> list[Path]:
    if not certs_dir.is_dir():
        return []
    return sorted(certs_dir.glob("*.pem"))
