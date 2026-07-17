"""Evidence capture for API responses and normalized snapshots."""

from flex_testing_agent.evidence.redaction import redact_secrets
from flex_testing_agent.evidence.store import EvidenceStore

__all__ = ["EvidenceStore", "redact_secrets"]
