"""Robot HTTPS CA certificate store (adapted from monorepo e2e-testing)."""

from flex_testing_agent.robot_certs.bootstrap import trust_robot_ca
from flex_testing_agent.robot_certs.registry import (
    RobotCertEntry,
    RobotCertRegistry,
    load_registry,
)
from flex_testing_agent.robot_certs.resolve import resolve_httpx_verify

__all__ = [
    "RobotCertEntry",
    "RobotCertRegistry",
    "load_registry",
    "resolve_httpx_verify",
    "trust_robot_ca",
]
