"""HTTP client error types."""

from __future__ import annotations


class RobotApiError(Exception):
    """Raised when a robot API returns an unexpected HTTP error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        path: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path
        self.body = body


class RobotTimeoutError(RobotApiError):
    """Raised when a robot API call exceeds its timeout."""
