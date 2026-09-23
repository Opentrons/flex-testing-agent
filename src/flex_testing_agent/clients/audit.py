"""CRS audit-server client (log periods list + download).

Product paths (api-client):
- ``GET /audit/external/logPeriods``
- ``GET /audit/external/logPeriods/{id}/download``
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession


@dataclass(frozen=True, slots=True)
class LogPeriodSummary:
    """One audit log period from ``GET /audit/external/logPeriods``."""

    id: str
    started_at: str | None
    ended_at: str | None


@dataclass(frozen=True, slots=True)
class DownloadedLogPeriod:
    """Raw download payload for one log period."""

    period_id: str
    content: bytes
    content_type: str | None


class AuditClient:
    """Atomic client for audit-server external log-period APIs."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_log_periods(self) -> list[LogPeriodSummary]:
        """GET ``/audit/external/logPeriods`` (oldest first)."""
        payload = await self._session.get_json("/audit/external/logPeriods")
        data = payload.get("data")
        if not isinstance(data, list):
            return []
        periods: list[LogPeriodSummary] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is None:
                continue
            started = item.get("startedAt")
            ended = item.get("endedAt")
            periods.append(
                LogPeriodSummary(
                    id=str(raw_id),
                    started_at=started if isinstance(started, str) else None,
                    ended_at=ended if isinstance(ended, str) else None,
                )
            )
        return periods

    async def download_log_period(
        self,
        period_id: str | int,
        *,
        timeout: float | None = 120.0,
    ) -> DownloadedLogPeriod:
        """GET ``/audit/external/logPeriods/{id}/download`` (zip or blob)."""
        path = f"/audit/external/logPeriods/{period_id}/download"
        content, content_type = await self._session.get_bytes(path, timeout=timeout)
        return DownloadedLogPeriod(
            period_id=str(period_id),
            content=content,
            content_type=content_type,
        )

    async def list_log_periods_raw(self) -> dict[str, Any]:
        """Return the raw JSON envelope for evidence capture."""
        return await self._session.get_json("/audit/external/logPeriods")

    async def get_external_settings_raw(self) -> dict[str, Any]:
        """GET ``/audit/external/settings`` envelope."""
        return await self._session.get_json("/audit/external/settings")
