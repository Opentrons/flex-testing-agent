"""CRS-on QA carveout: allow SSH / Jupyter / devtools via serial.

When CRS (accessControlEnabled) is on, robot builds from edge / 10.0 alphas
disable jupyter, SSH, and devtools unless a sentinel file exists on the
read-only root filesystem. Creating that file requires an FTDI serial console
(or equivalent root console) and is cleared on the next system update.

This does **not** disable CRS. Preferred CRS exit is root
``opentrons_disable_crs`` over SSH (or serial if SSH is down). EXEC-2176 wipe
is the fallback. See docs/interaction-layers.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from flex_testing_agent.serial_console.login import run_command
from flex_testing_agent.serial_console.session import SerialSession

# Merged product path / unit (edge + 10.0 alphas). Do not use the older
# draft names ``/etc/.allow-remote-access`` or ``jupyter-notebook``.
REMOTE_ACCESS_ALLOW_PATH: str = "/etc/opentrons-allow-remote-access"
REMOTE_ACCESS_UNIT: str = "opentrons-remote-access-allowed"

ENABLE_REMOTE_ACCESS_SHELL: str = (
    "mount -o remount,rw /; "
    f"touch {REMOTE_ACCESS_ALLOW_PATH}; "
    f"systemctl restart {REMOTE_ACCESS_UNIT}"
)

STATUS_REMOTE_ACCESS_SHELL: str = (
    f"if test -e {REMOTE_ACCESS_ALLOW_PATH}; then echo ALLOW_FILE=yes; "
    "else echo ALLOW_FILE=no; fi; "
    f"systemctl is-active {REMOTE_ACCESS_UNIT} 2>/dev/null || "
    "echo unit-missing; "
    f"systemctl is-enabled {REMOTE_ACCESS_UNIT} 2>/dev/null || true"
)


@dataclass(frozen=True, slots=True)
class RemoteAccessStatus:
    """Parsed serial probe of the CRS remote-access carveout."""

    allow_file_present: bool | None
    unit_active: str
    raw: str

    @property
    def likely_allowed(self) -> bool:
        """Best-effort: sentinel present and unit reports active."""
        return self.allow_file_present is True and self.unit_active == "active"


def parse_remote_access_status(raw: str) -> RemoteAccessStatus:
    """Parse ``STATUS_REMOTE_ACCESS_SHELL`` output."""
    allow: bool | None = None
    unit_active = "unknown"
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("ALLOW_FILE="):
            value = stripped.split("=", 1)[1].strip().lower()
            if value in {"yes", "true", "1"}:
                allow = True
            elif value in {"no", "false", "0"}:
                allow = False
        elif stripped in {"active", "inactive", "failed", "activating", "unit-missing"}:
            unit_active = stripped
    return RemoteAccessStatus(
        allow_file_present=allow,
        unit_active=unit_active,
        raw=raw,
    )


def enable_remote_access(
    session: SerialSession,
    *,
    timeout: float = 60.0,
    login: bool = True,
) -> str:
    """Remount root RW, touch the allow file, restart the remote-access unit."""
    return run_command(
        session,
        ENABLE_REMOTE_ACCESS_SHELL,
        timeout=timeout,
        login=login,
    )


def probe_remote_access(
    session: SerialSession,
    *,
    timeout: float = 30.0,
    login: bool = True,
) -> RemoteAccessStatus:
    """Read sentinel + unit state over the serial console."""
    raw = run_command(
        session,
        STATUS_REMOTE_ACCESS_SHELL,
        timeout=timeout,
        login=login,
    )
    return parse_remote_access_status(raw)
