"""Low-level HTTP status probes (no raise on 4xx/5xx) for CRS lockdown testing."""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from typing import Any

import httpx

from flex_testing_agent.clients.errors import RobotApiError, RobotTimeoutError
from flex_testing_agent.clients.session import (
    OPENTRONS_VERSION_HEADER,
    RobotHttpSession,
)


@dataclass(frozen=True, slots=True)
class HttpStatusProbe:
    """Outcome of one HTTP request without treating 4xx/5xx as an exception."""

    status_code: int
    body_bytes: int
    has_json_data: bool
    content_type: str | None


def _json_has_data(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if data is None:
        return False
    if isinstance(data, list):
        return len(data) > 0
    if isinstance(data, dict):
        return len(data) > 0
    return True


def _parse_probe_response(response: httpx.Response) -> HttpStatusProbe:
    content_type = response.headers.get("content-type")
    has_data = False
    if response.content and content_type and "json" in content_type:
        with contextlib.suppress(json.JSONDecodeError, ValueError):
            has_data = _json_has_data(response.json())
    return HttpStatusProbe(
        status_code=response.status_code,
        body_bytes=len(response.content),
        has_json_data=has_data,
        content_type=content_type,
    )


async def probe_http_status(
    session: RobotHttpSession,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
    timeout: float | None = None,
    extra_headers: dict[str, str] | None = None,
) -> HttpStatusProbe:
    """Issue one request and return status metadata (never raises on HTTP status)."""
    method_upper = method.upper()
    headers = dict(extra_headers or {})
    headers.setdefault(OPENTRONS_VERSION_HEADER, "3")
    token = session.access_token
    if token:
        headers.setdefault("Authorization", f"Bearer {token}")

    try:
        if form is not None:
            response = await session._client.request(
                method_upper,
                path,
                data=form,
                headers=headers,
                timeout=timeout,
            )
        else:
            response = await session._client.request(
                method_upper,
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
    return _parse_probe_response(response)
