"""Update-server client for Flex robot OS installation.

Source: ``update-server/otupdate/common/update.py`` and
``update-server/otupdate/openembedded/__init__.py``.

Flow:
1. ``POST /server/update/begin``
2. ``POST /server/update/{token}/file`` (multipart field ``system-update.zip``)
3. Poll ``GET /server/update/{token}/status``
4. Optionally ``POST /server/update/{token}/commit`` and ``POST /server/restart``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from flex_testing_agent.clients.errors import RobotApiError, RobotTimeoutError
from flex_testing_agent.clients.session import (
    OPENTRONS_VERSION,
    OPENTRONS_VERSION_HEADER,
    RobotHttpSession,
)


class UpdateClient:
    """Atomic client for update-server install endpoints."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def begin(
        self,
        *,
        auto_commit_and_restart: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Start an update session."""
        return await self._session.post_json(
            "/server/update/begin",
            json_body={"auto_commit_and_restart": auto_commit_and_restart},
            timeout=timeout,
            expected_status=(201,),
        )

    async def cancel(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Cancel any active update session."""
        return await self._session.post_json(
            "/server/update/cancel",
            timeout=timeout,
            expected_status=(200,),
        )

    async def status(
        self, token: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Poll update session status."""
        return await self._session.get_json(
            f"/server/update/{token}/status",
            timeout=timeout,
        )

    async def upload_system_update(
        self,
        token: str,
        zip_path: Path,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Upload a Flex ``ot3-system.zip`` as multipart field ``system-update.zip``."""
        url = f"/server/update/{token}/file"
        try:
            with zip_path.open("rb") as handle:
                files = {
                    "system-update.zip": (
                        "system-update.zip",
                        handle,
                        "application/zip",
                    )
                }
                response = await self._session._client.post(
                    url,
                    files=files,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise RobotTimeoutError(
                f"Timed out uploading update to {url}",
                path=url,
            ) from exc
        except httpx.RequestError as exc:
            raise RobotApiError(
                f"Upload failed for {url}: {exc}",
                path=url,
            ) from exc

        if response.status_code >= 400:
            raise RobotApiError(
                f"HTTP {response.status_code} for {url}",
                status_code=response.status_code,
                path=url,
                body=response.text,
            )
        data = response.json()
        if not isinstance(data, dict):
            raise RobotApiError(
                f"Expected JSON object from {url}",
                status_code=response.status_code,
                path=url,
                body=response.text,
            )
        return data

    async def commit(
        self, token: str, *, timeout: float | None = None
    ) -> dict[str, Any]:
        """Commit a validated update (when not using auto-commit)."""
        return await self._session.post_json(
            f"/server/update/{token}/commit",
            timeout=timeout,
            expected_status=(200,),
        )

    async def restart(self, *, timeout: float | None = None) -> dict[str, Any]:
        """Request robot restart after commit."""
        return await self._session.post_json(
            "/server/restart",
            timeout=timeout,
            expected_status=(200,),
        )


async def download_file(
    url: str,
    destination: Path,
    *,
    timeout_seconds: float = 600.0,
) -> Path:
    """Download a remote file to ``destination`` (streaming)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with (
        httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION},
            follow_redirects=True,
        ) as client,
        client.stream("GET", url) as response,
    ):
        response.raise_for_status()
        with destination.open("wb") as handle:
            async for chunk in response.aiter_bytes():
                handle.write(chunk)
    return destination
