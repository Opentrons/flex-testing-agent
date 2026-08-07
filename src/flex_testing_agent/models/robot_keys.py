"""Key-server encrypted CA certificate models."""

from __future__ import annotations

from pydantic import BaseModel


class EncryptedCertificate(BaseModel):
    """One password-encrypted CA certificate (Fernet token)."""

    cert_data: str
    key_salt: str
    key_expires_at: str
    kdf_iterations: int


class OldAndNewEncryptedCertificate(BaseModel):
    """Current and optional previous password variants."""

    current: EncryptedCertificate
    previous: EncryptedCertificate | None = None


class EncryptedCACertificatesData(BaseModel):
    """Payload from GET /keys/external/ca/encryptedCerts."""

    current: OldAndNewEncryptedCertificate
    next: OldAndNewEncryptedCertificate | None = None


class EncryptedCACertificatesEnvelope(BaseModel):
    """JSON envelope for encrypted CA certificates."""

    data: EncryptedCACertificatesData
