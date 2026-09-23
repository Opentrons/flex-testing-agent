#!/usr/bin/env python3
"""Audit POST /camera/picture call shape on KansasFLEX (RQA-5807).

Compares CRS-on (HTTPS + OAuth) vs CRS-off (HTTP, no auth) and several
request body variants to confirm the harness matches OpenAPI (empty POST).

Writes ``artifacts/retest-rqa5807/picture-call-audit.json`` for Jira evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.clients.camera import DEFAULT_CAMERA_ID
from flex_testing_agent.clients.errors import RobotTimeoutError
from flex_testing_agent.clients.session import (
    OPENTRONS_USER_NOTES_HEADER,
    OPENTRONS_VERSION,
    OPENTRONS_VERSION_HEADER,
)
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import snapshot_run_state
from flex_testing_agent.robot_certs.resolve import resolve_httpx_verify
from flex_testing_agent.robots.flex import FlexRobot, build_robot_http_session

ART = Path("artifacts/retest-rqa5807")
JIRA = "https://opentrons.atlassian.net/browse/RQA-5807"
ADMIN = "flex_test_admin"
PICTURE_TIMEOUT_S = 45.0
PREVIEW_TIMEOUT_S = 30.0


@dataclass
class HttpAttempt:
    label: str
    mode: str
    method: str
    url: str
    request_headers: dict[str, str]
    request_body: str | None
    status_code: int | None
    response_headers: dict[str, str]
    response_body: str
    elapsed_ms: float
    error: str | None = None


def _redact_auth(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    if "Authorization" in out:
        token = out["Authorization"]
        if token.startswith("Bearer ") and len(token) > 20:
            out["Authorization"] = f"Bearer {token[7:15]}…"
    return out


def _response_summary(content: bytes, content_type: str | None) -> str:
    if content_type and "image" in content_type.lower():
        return f"<{len(content)} bytes image/jpeg>"
    text = content.decode("utf-8", errors="replace")
    if len(text) > 800:
        return text[:800] + "…"
    return text


async def _attempt(
    *,
    label: str,
    mode: str,
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    content: bytes | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float,
) -> HttpAttempt:
    req_headers = _redact_auth(headers)
    if json_body is not None:
        req_body = json.dumps(json_body)
    elif content is not None:
        req_body = repr(content) if content else "(empty bytes)"
    else:
        req_body = "(no body)"

    started = time.perf_counter()
    status: int | None = None
    resp_headers: dict[str, str] = {}
    body_preview = ""
    error: str | None = None
    try:
        response = await client.request(
            method,
            url,
            headers=headers,
            content=content,
            json=json_body,
            timeout=timeout,
        )
        status = response.status_code
        resp_headers = dict(response.headers)
        body_preview = _response_summary(
            response.content, response.headers.get("content-type")
        )
    except httpx.TimeoutException:
        error = f"timeout after {timeout}s"
        body_preview = error
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
        body_preview = error

    elapsed_ms = (time.perf_counter() - started) * 1000
    return HttpAttempt(
        label=label,
        mode=mode,
        method=method,
        url=url,
        request_headers=req_headers,
        request_body=req_body,
        status_code=status,
        response_headers=resp_headers,
        response_body=body_preview,
        elapsed_ms=round(elapsed_ms, 1),
        error=error,
    )


async def _crs_on_attempts(
    settings: Settings,
    *,
    host: str,
    token: str | None,
    run_label: str,
) -> list[HttpAttempt]:
    verify = resolve_httpx_verify(settings, host=host)
    base = f"https://{host}:{settings.robot_https_port}"
    headers: dict[str, str] = {OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers[OPENTRONS_USER_NOTES_HEADER] = "RQA-5807 picture call audit"

    attempts: list[HttpAttempt] = []
    async with httpx.AsyncClient(verify=verify, timeout=PICTURE_TIMEOUT_S) as client:
        preview_url = f"{base}/camera/capturePreviewImage"
        preview_json = {"data": {"cameraId": DEFAULT_CAMERA_ID}}
        attempts.append(
            await _attempt(
                label=f"{run_label}_preview_baseline",
                mode="crs_on_https_oauth" if token else "crs_on_https_no_auth",
                client=client,
                method="POST",
                url=preview_url,
                headers=headers,
                json_body=preview_json,
                timeout=PREVIEW_TIMEOUT_S,
            )
        )

        picture_url = f"{base}/camera/picture"
        variants: list[tuple[str, dict[str, Any] | None, bytes | None]] = [
            ("harness_post_bytes_no_body", None, None),
            ("empty_content_bytes", None, b""),
            ("empty_json_object", {}, None),
            ("settings_shaped_body", {"data": {"cameraId": DEFAULT_CAMERA_ID}}, None),
        ]
        for variant_label, json_body, content in variants:
            attempts.append(
                await _attempt(
                    label=f"{run_label}_picture_{variant_label}",
                    mode="crs_on_https_oauth" if token else "crs_on_https_no_auth",
                    client=client,
                    method="POST",
                    url=picture_url,
                    headers=headers,
                    json_body=json_body,
                    content=content,
                    timeout=PICTURE_TIMEOUT_S,
                )
            )
    return attempts


async def _crs_off_attempts(
    settings: Settings,
    *,
    host: str,
    run_label: str,
) -> list[HttpAttempt]:
    base = f"http://{host}:{settings.robot_http_port}"
    headers = {OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION}
    attempts: list[HttpAttempt] = []
    async with httpx.AsyncClient(timeout=PICTURE_TIMEOUT_S) as client:
        preview_url = f"{base}/camera/capturePreviewImage"
        preview_json = {"data": {"cameraId": DEFAULT_CAMERA_ID}}
        attempts.append(
            await _attempt(
                label=f"{run_label}_preview_baseline",
                mode="crs_off_http",
                client=client,
                method="POST",
                url=preview_url,
                headers=headers,
                json_body=preview_json,
                timeout=PREVIEW_TIMEOUT_S,
            )
        )

        picture_url = f"{base}/camera/picture"
        for variant_label, json_body, content in (
            ("harness_post_bytes_no_body", None, None),
            ("empty_content_bytes", None, b""),
        ):
            attempts.append(
                await _attempt(
                    label=f"{run_label}_picture_{variant_label}",
                    mode="crs_off_http",
                    client=client,
                    method="POST",
                    url=picture_url,
                    headers=headers,
                    json_body=json_body,
                    content=content,
                    timeout=PICTURE_TIMEOUT_S,
                )
            )
    return attempts


async def _harness_client_attempt(settings: Settings, token: str | None) -> HttpAttempt:
    """Mirror CameraClient.take_picture() exactly via RobotHttpSession."""
    session = build_robot_http_session(settings, access_token=token)
    started = time.perf_counter()
    status: int | None = None
    body_preview = ""
    error: str | None = None
    resp_headers: dict[str, str] = {}
    try:
        response = await session._request_raw(
            "POST",
            "/camera/picture",
            json_body=None,
            timeout=PICTURE_TIMEOUT_S,
            expected_status=tuple(range(100, 600)),
        )
        status = response.status_code
        resp_headers = dict(response.headers)
        body_preview = _response_summary(
            response.content, response.headers.get("content-type")
        )
    except RobotTimeoutError:
        error = f"timeout after {PICTURE_TIMEOUT_S}s"
        body_preview = error
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        body_preview = str(exc)
    finally:
        await session.aclose()

    return HttpAttempt(
        label="harness_camera_client_take_picture",
        mode="crs_on_https_oauth" if token else "harness_session",
        method="POST",
        url=f"{settings.robot_base_url}/camera/picture",
        request_headers={
            OPENTRONS_VERSION_HEADER: OPENTRONS_VERSION,
            "Authorization": "Bearer …" if token else "(none)",
            OPENTRONS_USER_NOTES_HEADER: "…" if token else "(none)",
        },
        request_body="(no body — CameraClient.take_picture / post_bytes json_body=None)",
        status_code=status,
        response_headers=resp_headers,
        response_body=body_preview,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        error=error,
    )


async def _access_control_enabled(settings: Settings) -> bool:
    async with FlexRobot(settings) as robot:
        raw = await robot.auth_settings.get_access_control_enabled_raw(
            timeout=settings.robot_health_timeout_seconds
        )
        data = raw.get("data", raw)
        return isinstance(data, dict) and bool(data.get("accessControlEnabled"))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Audit POST /camera/picture call variants")
    parser.add_argument(
        "--phase",
        choices=("crs_on", "crs_off", "all"),
        default="all",
        help="Which access-control mode to exercise (default: all)",
    )
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    host = settings.require_robot_host()
    crs_on = await _access_control_enabled(settings)

    async with FlexRobot(settings) as robot:
        run_snap = await snapshot_run_state(robot)
        camera = await robot.camera.get_camera()
        health = await robot.health.get_health()

    build = health.api_version or health.system_version or "unknown"
    print(f"RQA-5807 picture call audit ({JIRA})")
    print(f"Host: {host}  build: {build}  CRS: {'on' if crs_on else 'off'}")
    print(f"Run state: {run_snap.describe()}")
    print(f"Camera: cameraEnabled={camera.get('cameraEnabled')}")

    attempts: list[HttpAttempt] = []
    run_label = "no_current" if not run_snap.has_current else "while_current"

    if args.phase in ("crs_on", "all") and crs_on:
        token = await access_token_for_username(settings, ADMIN)
        attempts.extend(
            await _crs_on_attempts(
                settings, host=host, token=token, run_label=run_label
            )
        )
        attempts.append(await _harness_client_attempt(settings, token))
        # Plaintext HTTP while CRS on (no OAuth) — documents RQA-5981 path
        attempts.extend(
            await _crs_off_attempts(settings, host=host, run_label=f"{run_label}_plaintext")
        )
    elif args.phase in ("crs_on", "all"):
        print("SKIP crs_on: access control is off")

    if args.phase in ("crs_off", "all") and not crs_on:
        attempts.extend(await _crs_off_attempts(settings, host=host, run_label=run_label))
        attempts.append(await _harness_client_attempt(settings, None))
    elif args.phase in ("crs_off", "all"):
        print("SKIP crs_off: access control is still on (run opentrons_disable_crs first)")

    for attempt in attempts:
        status = attempt.status_code if attempt.status_code is not None else "—"
        err = f" [{attempt.error}]" if attempt.error else ""
        print(
            f"  {attempt.mode:22} {attempt.label:40} "
            f"HTTP {status} {attempt.elapsed_ms}ms{err}"
        )
        if attempt.response_body and not attempt.error:
            preview = attempt.response_body.replace("\n", " ")[:100]
            print(f"    -> {preview}")

    report = {
        "jira": JIRA,
        "robot_host": host,
        "build": build,
        "crs_on": crs_on,
        "run_state": run_snap.model_dump(mode="json"),
        "camera": camera,
        "attempts": [asdict(a) for a in attempts],
    }
    out = ART / "picture-call-audit.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\nReport: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
