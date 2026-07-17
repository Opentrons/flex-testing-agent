"""Shared async HTTP session for Flex robot APIs.

Designed for dual-mode access control:
- When access control is off, omit Authorization (default inspect path).
- When access control is on, attach an optional bearer token.

Milestone 1 uses HTTP by default. HTTPS + CA bootstrap is deferred.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import httpx

from flex_testing_agent.clients.errors import RobotApiError, RobotTimeoutError

OPENTRONS_VERSION_HEADER = "Opentrons-Version"
OPENTRONS_VERSION = "3"


class RobotHttpSession:
    """Thin async httpx wrapper with Opentrons headers and optional auth."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        access_token: str | None = None,
        verify: bool | str = True,
    ) -> None:
        headers = {OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            headers=headers,
            verify=verify,
        )

    @property
    def access_token(self) -> str | None:
        """Return the optional bearer token for access-control-on mode."""
        return self._access_token

    async def __aenter__(self) -> RobotHttpSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def get_json(
        self,
        path: str,
        *,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        """GET a JSON object from the robot."""
        return await self._request_json(
            "GET",
            path,
            timeout=timeout,
            expected_status=expected_status,
        )

    async def post_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        """POST JSON and return a JSON object response."""
        return await self._request_json(
            "POST",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
        )

    async def get_bytes(
        self,
        path: str,
        *,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> tuple[bytes, str | None]:
        """GET raw bytes (e.g. images) and optional content-type."""
        response = await self._request_raw(
            "GET",
            path,
            timeout=timeout,
            expected_status=expected_status,
        )
        return response.content, response.headers.get("content-type")

    async def post_bytes(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> tuple[bytes, str | None]:
        """POST JSON and return raw response bytes (e.g. camera JPEG)."""
        response = await self._request_raw(
            "POST",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
        )
        return response.content, response.headers.get("content-type")

    async def _request_raw(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._client.request(
                method,
                path,
                json=json_body,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise RobotTimeoutError(
                f"Timed out requesting {path}",
                path=path,
            ) from exc
        except httpx.RequestError as exc:
            raise RobotApiError(
                f"Request failed for {path}: {exc}",
                path=path,
            ) from exc

        allowed = expected_status
        if allowed is None:
            ok = response.status_code < 400
        else:
            ok = response.status_code in allowed
        if not ok:
            raise RobotApiError(
                f"HTTP {response.status_code} for {path}",
                status_code=response.status_code,
                path=path,
                body=response.text,
            )
        return response

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                path,
                json=json_body,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            raise RobotTimeoutError(
                f"Timed out requesting {path}",
                path=path,
            ) from exc
        except httpx.RequestError as exc:
            raise RobotApiError(
                f"Request failed for {path}: {exc}",
                path=path,
            ) from exc

        allowed = expected_status
        if allowed is None:
            ok = response.status_code < 400
        else:
            ok = response.status_code in allowed
        if not ok:
            raise RobotApiError(
                f"HTTP {response.status_code} for {path}",
                status_code=response.status_code,
                path=path,
                body=response.text,
            )
        if response.status_code == 204 or not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise RobotApiError(
                f"Expected JSON object from {path}",
                status_code=response.status_code,
                path=path,
                body=response.text,
            )
        return data
