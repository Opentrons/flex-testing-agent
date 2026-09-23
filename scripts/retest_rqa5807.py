#!/usr/bin/env python3
"""Retest RQA-5807: camera picture clarity while a current run exists.

https://opentrons.atlassian.net/browse/RQA-5807

While a current run exists (even idle, never played):
  - POST /camera/capturePreviewImage should return 422 with a clear run-active message.
  - POST /camera/picture should NOT return 500 COMMUNICATION_ERROR; prefer the same 422.

After uncurrenting the run, both endpoints should return 200 JPEG.

Preconditions:
  - KansasFLEX reachable (ROBOT_HOST / candidates)
  - Camera enabled (script enables if needed; ALLOW_MUTATIONS=true)
  - CRS on: ROBOT_USERNAME / ROBOT_PASSWORD for OAuth
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flex_testing_agent.capabilities.crs_auth import access_token_for_username
from flex_testing_agent.clients.camera import DEFAULT_CAMERA_ID
from flex_testing_agent.clients.errors import RobotTimeoutError
from flex_testing_agent.config.settings import Settings, get_settings
from flex_testing_agent.orchestration.discover import settings_with_resolved_host
from flex_testing_agent.orchestration.run_state import (
    DesiredRunState,
    ensure_run_state,
    release_current_run,
    snapshot_run_state,
)
from flex_testing_agent.robots.flex import FlexRobot

ART = Path("artifacts/retest-rqa5807")
JIRA = "https://opentrons.atlassian.net/browse/RQA-5807"
SIGNED_BY = "Flex Harness RQA-5807 Retest"
ADMIN = "flex_test_admin"


async def access_token_if_crs(settings: Settings) -> str | None:
    """OAuth token when CRS is on; None when access control is disabled."""
    async with FlexRobot(settings) as probe:
        raw = await probe.auth_settings.get_access_control_enabled_raw(
            timeout=settings.robot_health_timeout_seconds
        )
        data = raw.get("data", raw)
        enabled = isinstance(data, dict) and bool(data.get("accessControlEnabled"))
    if not enabled:
        return None
    return await access_token_for_username(settings, ADMIN)


@dataclass
class CameraProbe:
    phase: str
    endpoint: str
    status_code: int
    content_type: str | None
    body_preview: str
    jpeg_bytes: int


def _body_preview(content: bytes, content_type: str | None) -> str:
    if content_type and "image" in content_type.lower():
        return f"<{len(content)} bytes JPEG>"
    text = content.decode("utf-8", errors="replace")
    if len(text) > 500:
        return text[:500] + "..."
    return text


async def _post_camera(
    robot: FlexRobot,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> CameraProbe:
    try:
        response = await robot.session._request_raw(
            "POST",
            path,
            json_body=json_body,
            timeout=timeout,
            expected_status=tuple(range(100, 600)),
        )
    except RobotTimeoutError:
        return CameraProbe(
            phase="",
            endpoint=path,
            status_code=0,
            content_type=None,
            body_preview=f"timeout after {timeout}s",
            jpeg_bytes=0,
        )
    content_type = response.headers.get("content-type")
    content = response.content
    return CameraProbe(
        phase="",
        endpoint=path,
        status_code=response.status_code,
        content_type=content_type,
        body_preview=_body_preview(content, content_type),
        jpeg_bytes=len(content) if content_type and "image" in content_type.lower() else 0,
    )


async def _ensure_camera_enabled(robot: FlexRobot) -> dict[str, Any]:
    status = await robot.camera.get_camera()
    if not status.get("cameraEnabled"):
        status = await robot.camera.set_camera_enabled(camera_enabled=True)
    return status


def _picture_verdict(probe: CameraProbe) -> str:
    if probe.status_code == 0 and "timeout" in probe.body_preview.lower():
        return "bug_still_open_timeout"
    if probe.status_code == 422:
        if "run is active" in probe.body_preview.lower():
            return "fixed_clear_422"
        return "422_other_message"
    if probe.status_code == 500 and "COMMUNICATION_ERROR" in probe.body_preview:
        return "bug_still_open_500"
    if probe.status_code == 200 and probe.jpeg_bytes > 0:
        return "unexpected_200_while_current"
    return f"unexpected_{probe.status_code}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Retest RQA-5807 camera picture during current run")
    parser.add_argument(
        "--skip-cleanup",
        action="store_true",
        help="Leave current run state unchanged after the retest",
    )
    args = parser.parse_args()

    ART.mkdir(parents=True, exist_ok=True)
    settings = await settings_with_resolved_host(get_settings())
    print(f"RQA-5807 camera picture clarity retest ({JIRA})")
    print(
        f"Robot host: {settings.robot_host} "
        f"https={settings.robot_use_https} "
        f"mutations={settings.allow_mutations}"
    )
    if not settings.allow_mutations:
        print("ERROR: set ALLOW_MUTATIONS=true (camera enable + run ensure/cleanup).")
        return 2

    probes: list[CameraProbe] = []
    run_id: str | None = None
    created_run = False

    token = await access_token_if_crs(settings)
    async with FlexRobot(settings, access_token=token) as robot:
        camera = await _ensure_camera_enabled(robot)
        print(f"Camera: cameraEnabled={camera.get('cameraEnabled')}")

        before = await snapshot_run_state(robot)
        print(f"Run state before: {before.describe()}")

        after = await ensure_run_state(
            robot,
            DesiredRunState.CURRENT_IDLE,
            ensure=True,
            capability_name="retest_rqa5807",
        )
        run_id = after.current_run_id
        created_run = not before.matches(DesiredRunState.CURRENT_IDLE)
        print(f"Run state during test: {after.describe()}")

        preview_body = {"data": {"cameraId": DEFAULT_CAMERA_ID}}
        for label, path, body in (
            ("while_current", "/camera/capturePreviewImage", preview_body),
            ("while_current", "/camera/picture", None),
        ):
            probe = await _post_camera(robot, path, json_body=body)
            probe.phase = label
            probes.append(probe)
            print(
                f"  [{label}] POST {path} -> HTTP {probe.status_code} "
                f"({probe.body_preview[:120]})"
            )

        if run_id is not None:
            await release_current_run(robot, run_id, signed_by=SIGNED_BY)
            print(f"Uncurrented run {run_id}")

        for path, body in (
            ("/camera/capturePreviewImage", preview_body),
            ("/camera/picture", None),
        ):
            probe = await _post_camera(robot, path, json_body=body)
            probe.phase = "after_uncurrent"
            probes.append(probe)
            print(
                f"  [after_uncurrent] POST {path} -> HTTP {probe.status_code} "
                f"({probe.body_preview[:120]})"
            )

        if args.skip_cleanup and created_run and run_id is not None:
            await robot.runs.set_current(run_id, current=True)
            print(f"Restored current run {run_id} (--skip-cleanup)")

    while_current = [p for p in probes if p.phase == "while_current"]
    after_uncurrent = [p for p in probes if p.phase == "after_uncurrent"]
    preview_while = next(p for p in while_current if "Preview" in p.endpoint or "capturePreview" in p.endpoint)
    picture_while = next(p for p in while_current if p.endpoint == "/camera/picture")
    picture_verdict = _picture_verdict(picture_while)

    preview_ok = preview_while.status_code == 422 and "run is active" in preview_while.body_preview.lower()
    picture_fixed = picture_verdict == "fixed_clear_422"
    after_ok = all(p.status_code == 200 and p.jpeg_bytes > 0 for p in after_uncurrent)

    bug_open = picture_verdict in ("bug_still_open_500", "bug_still_open_timeout")
    ok = preview_ok and picture_fixed and after_ok

    if ok:
        verdict = "PASS"
        detail = "Picture returns clear 422 while current; both JPEG after uncurrent."
    elif bug_open:
        verdict = "BUG_STILL_OPEN"
        if picture_verdict == "bug_still_open_timeout":
            detail = "Picture timed out while current run exists (no clear 422)."
        else:
            detail = "Picture still returns 500 COMMUNICATION_ERROR while current run exists."
    else:
        verdict = "INCONCLUSIVE"
        detail = (
            f"preview_ok={preview_ok} picture_verdict={picture_verdict} after_ok={after_ok}"
        )

    print(f"\n[{verdict}] {detail}")

    report = {
        "jira": JIRA,
        "verdict": verdict,
        "detail": detail,
        "picture_verdict": picture_verdict,
        "run_id": run_id,
        "probes": [asdict(p) for p in probes],
    }
    report_path = ART / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {report_path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
