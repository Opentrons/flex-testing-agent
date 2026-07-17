"""Robot capabilities: safe compositions of atomic client calls."""

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.capabilities.inspect import INSPECT_DESCRIPTOR, inspect_robot
from flex_testing_agent.capabilities.install import INSTALL_DESCRIPTOR, install_build
from flex_testing_agent.capabilities.module_reconnect import (
    MODULE_RECONNECT_DESCRIPTOR,
    run_suite_b_phase,
)
from flex_testing_agent.capabilities.probe import (
    PICTURE_DESCRIPTOR,
    PROBE_DESCRIPTOR,
    probe_robot,
)

__all__ = [
    "INSPECT_DESCRIPTOR",
    "INSTALL_DESCRIPTOR",
    "MODULE_RECONNECT_DESCRIPTOR",
    "PICTURE_DESCRIPTOR",
    "PROBE_DESCRIPTOR",
    "CapabilityDescriptor",
    "inspect_robot",
    "install_build",
    "probe_robot",
    "run_suite_b_phase",
]
