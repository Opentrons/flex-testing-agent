"""Serial transcript helpers (preserve kernel logs for later review).

By default every ``flex-test serial`` operation writes under
``ARTIFACT_DIRECTORY/serial/``:

- Per-run file: ``<UTC>-<kind>.log`` (one operation)
- Daily rollup: ``<YYYYMMDD>-console.log`` (append-only historical reference)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def serial_log_directory(artifact_directory: Path) -> Path:
    """Return ``ARTIFACT_DIRECTORY/serial/``, creating it if needed."""
    directory = artifact_directory.expanduser().resolve() / "serial"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def default_serial_log_path(artifact_directory: Path, *, kind: str = "watch") -> Path:
    """Return ``ARTIFACT_DIRECTORY/serial/<timestamp>-<kind>.log``."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return serial_log_directory(artifact_directory) / f"{stamp}-{kind}.log"


def daily_console_log_path(artifact_directory: Path) -> Path:
    """Return append-only ``ARTIFACT_DIRECTORY/serial/<YYYYMMDD>-console.log``."""
    day = datetime.now(UTC).strftime("%Y%m%d")
    return serial_log_directory(artifact_directory) / f"{day}-console.log"


def append_transcript(path: Path, chunk: str) -> None:
    """Append decoded serial text to ``path`` (creates parents)."""
    if not chunk:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(chunk)
        handle.flush()


def write_operation_header(
    path: Path,
    *,
    kind: str,
    port: str,
    baudrate: int,
    detail: str = "",
) -> None:
    """Append a human-readable banner before an operation's transcript."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "\n",
        f"===== flex-test serial {kind} @ {stamp} =====\n",
        f"port={port} baud={baudrate}\n",
    ]
    if detail:
        lines.append(f"{detail.rstrip()}\n")
    lines.append("----------------------------------------\n")
    append_transcript(path, "".join(lines))


def resolve_transcript_paths(
    artifact_directory: Path,
    *,
    kind: str,
    log_file: Path | None,
    save_log: bool,
) -> tuple[Path | None, Path | None]:
    """Return ``(per_run_path, daily_path)`` according to CLI flags.

    When ``save_log`` is true (the default for serial commands), both a
    per-run file and the daily rollup are written. An explicit ``log_file``
    replaces the per-run path but the daily rollup still receives a copy.
    """
    if not save_log and log_file is None:
        return None, None
    per_run = log_file
    if save_log and per_run is None:
        per_run = default_serial_log_path(artifact_directory, kind=kind)
    daily = daily_console_log_path(artifact_directory) if save_log else None
    return per_run, daily


def record_transcript(
    chunk: str,
    *,
    per_run: Path | None,
    daily: Path | None,
) -> None:
    """Append ``chunk`` to any configured transcript destinations."""
    if per_run is not None:
        append_transcript(per_run, chunk)
    if daily is not None:
        append_transcript(daily, chunk)


class TeeSerial:
    """Wrap a pyserial-like port and mirror RX/TX into transcript files."""

    def __init__(
        self,
        inner: Any,
        *,
        per_run: Path | None,
        daily: Path | None,
    ) -> None:
        self._inner = inner
        self._per_run = per_run
        self._daily = daily

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def read(self, size: int = 1) -> bytes:
        data = bytes(self._inner.read(size))
        if data:
            record_transcript(
                data.decode("utf-8", errors="replace"),
                per_run=self._per_run,
                daily=self._daily,
            )
        return data

    def write(self, data: bytes) -> int | None:
        if data:
            # Prefix TX so historical logs distinguish typed input from printk.
            text = data.decode("utf-8", errors="replace")
            record_transcript(
                f">>> {text}",
                per_run=self._per_run,
                daily=self._daily,
            )
        written = self._inner.write(data)
        if written is None:
            return None
        return int(written)

    def close(self) -> None:
        self._inner.close()
