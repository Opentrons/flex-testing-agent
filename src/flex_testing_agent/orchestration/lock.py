"""Exclusive local lock for operations against a single robot host."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from filelock import FileLock, Timeout

from flex_testing_agent.logging import get_logger

log = get_logger(__name__)


class RobotLockError(RuntimeError):
    """Raised when the robot operation lock cannot be acquired."""


class RobotOperationLock:
    """Process-local exclusive lock keyed by robot host.

    Prevents concurrent harness processes from mutating or inspecting the
    same robot at the same time.
    """

    def __init__(
        self,
        host: str,
        lock_directory: Path,
        *,
        timeout_seconds: float = 0,
    ) -> None:
        safe_host = host.replace("/", "_").replace(":", "_")
        lock_directory.mkdir(parents=True, exist_ok=True)
        self._path = lock_directory / f"robot-{safe_host}.lock"
        self._timeout = timeout_seconds
        self._lock = FileLock(str(self._path))

    def __enter__(self) -> RobotOperationLock:
        try:
            self._lock.acquire(timeout=self._timeout)
        except Timeout as exc:
            raise RobotLockError(
                f"Could not acquire robot lock at {self._path}. "
                "Another harness process may be using this robot."
            ) from exc
        log.info("robot_lock_acquired", path=str(self._path))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._lock.release()
        log.info("robot_lock_released", path=str(self._path))
