"""Shared async HTTP session for Flex robot APIs.

Designed for dual-mode access control:
- When access control is off, omit Authorization (default inspect path).
- When access control is on, attach an optional bearer token.

HTTP by default. HTTPS after `flex-test crs trust-ca` (`ROBOT_USE_HTTPS=true`).
"""

from __future__ import annotations

import ssl
from types import TracebackType
from typing import Any

import httpx

from flex_testing_agent.clients.errors import RobotApiError, RobotTimeoutError

OPENTRONS_VERSION_HEADER = "Opentrons-Version"
OPENTRONS_USER_NOTES_HEADER = "Opentrons-User-Notes"
OPENTRONS_VERSION = "3"

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RobotHttpSession:
    """Thin async httpx wrapper with Opentrons headers and optional auth."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 30.0,
        access_token: str | None = None,
        user_notes: str | None = None,
        verify: bool | str | ssl.SSLContext = True,
    ) -> None:
        headers = {OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self.base_url = base_url.rstrip("/")
        self._access_token = access_token
        self._user_notes = user_notes
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

    def set_access_token(self, token: str | None) -> None:
        """Replace the bearer token on the shared httpx client."""
        self._access_token = token
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        else:
            self._client.headers.pop("Authorization", None)

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
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET a JSON object from the robot."""
        return await self._request_json(
            "GET",
            path,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
        )

    async def post_form(
        self,
        path: str,
        *,
        form: dict[str, str],
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST application/x-www-form-urlencoded and parse JSON object."""
        headers = self._merge_mutation_headers("POST", extra_headers)
        try:
            response = await self._client.request(
                "POST",
                path,
                data=form,
                headers=headers,
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

    async def post_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST JSON and return a JSON object response."""
        return await self._request_json(
            "POST",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
        )

    async def put_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """PUT JSON and return a JSON object response."""
        return await self._request_json(
            "PUT",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
        )

    async def patch_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """PATCH JSON and return a JSON object response."""
        return await self._request_json(
            "PATCH",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
        )

    async def delete_json(
        self,
        path: str,
        *,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """DELETE and return a JSON object response (empty dict for 204)."""
        return await self._request_json(
            "DELETE",
            path,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
        )

    async def post_multipart(
        self,
        path: str,
        *,
        files: list[tuple[str, tuple[str, bytes, str]]],
        form_fields: dict[str, str] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
    ) -> dict[str, Any]:
        """POST multipart/form-data (protocol / data-file uploads)."""
        headers = self._merge_mutation_headers("POST", None)
        try:
            response = await self._client.request(
                "POST",
                path,
                files=files,
                data=form_fields,
                headers=headers,
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

    async def get_with_status(
        self,
        path: str,
        *,
        timeout: float | None = None,
        expected_status: tuple[int, ...] = (200, 201, 204, 404),
    ) -> tuple[int, dict[str, Any] | None]:
        """GET and return ``(status_code, json_object_or_none)``.

        Useful for CRS-off parameterized probes where 404 is acceptable.
        """
        response = await self._request_raw(
            "GET",
            path,
            timeout=timeout,
            expected_status=expected_status,
        )
        if response.status_code == 204 or not response.content:
            return response.status_code, None
        try:
            data = response.json()
        except ValueError:
            return response.status_code, None
        if isinstance(data, dict):
            return response.status_code, data
        return response.status_code, None

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
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = self._merge_mutation_headers(method, extra_headers)
        try:
            response = await self._client.request(
                method,
                path,
                json=json_body,
                headers=headers,
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

    def _merge_mutation_headers(
        self,
        method: str,
        extra_headers: dict[str, str] | None,
    ) -> dict[str, str]:
        """Attach CRS audit ``Opentrons-User-Notes`` for mutating requests."""
        headers = dict(extra_headers or {})
        if (
            method.upper() in _MUTATING_METHODS
            and self._user_notes
            and OPENTRONS_USER_NOTES_HEADER not in headers
        ):
            headers[OPENTRONS_USER_NOTES_HEADER] = self._user_notes
        return headers

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
        expected_status: tuple[int, ...] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request_raw(
            method,
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=expected_status,
            extra_headers=extra_headers,
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
