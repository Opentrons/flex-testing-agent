"""Classify Flex serial kernel / printk lines (Confluence FTDI console).

The Flex serial console is also the kernel debug console. Unsolicited printk
lines mix with shell I/O. That is expected and useful for boot / driver
troubleshooting; do not discard transcripts wholesale.

See: https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Classic Linux console printk: "[    0.000000] message" or "[123.45] …"
_KERNEL_BRACKET_TS = re.compile(r"^\[\s*\d+\.\d+\]\s*")
# Call traces / oops headers commonly seen on the console.
_KERNEL_OOPS = re.compile(
    r"^(Call Trace:|Code:|Hardware name:|CPU:|RIP:|RSP:|---\[ end trace)",
    re.IGNORECASE,
)
# Early boot / bootloader fragments that are not shell prompts.
_KERNEL_BOOT = re.compile(
    r"^(Booting Linux|Linux version |Kernel command line:|console=\[|"
    r"Starting kernel|EFI stub:)",
    re.IGNORECASE,
)


def is_kernel_log_line(line: str) -> bool:
    """Return True when ``line`` looks like unsolicited kernel console output."""
    stripped = line.strip()
    if not stripped:
        return False
    if _KERNEL_BRACKET_TS.match(stripped):
        return True
    if _KERNEL_OOPS.match(stripped):
        return True
    return bool(_KERNEL_BOOT.match(stripped))


@dataclass(frozen=True, slots=True)
class PartitionedConsole:
    """Console text split into kernel vs non-kernel lines (order preserved)."""

    raw: str
    kernel_lines: tuple[str, ...]
    other_lines: tuple[str, ...]

    @property
    def kernel_text(self) -> str:
        """Kernel / printk lines joined with newlines."""
        return "\n".join(self.kernel_lines)

    @property
    def other_text(self) -> str:
        """Non-kernel lines joined with newlines."""
        return "\n".join(self.other_lines)

    @property
    def has_kernel(self) -> bool:
        return bool(self.kernel_lines)


def partition_console_text(text: str) -> PartitionedConsole:
    """Split normalized console text into kernel vs other lines."""
    normalized = text.replace("\r\n", "\n").replace("\r", "")
    kernel: list[str] = []
    other: list[str] = []
    for line in normalized.split("\n"):
        if is_kernel_log_line(line):
            kernel.append(line)
        else:
            other.append(line)
    return PartitionedConsole(
        raw=normalized,
        kernel_lines=tuple(kernel),
        other_lines=tuple(other),
    )
