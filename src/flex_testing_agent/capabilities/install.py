"""Install a published Flex robot OS build onto the robot under test."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.update import UpdateClient, download_file
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.logging import get_logger
from flex_testing_agent.models.build import InstallResult
from flex_testing_agent.models.health import HealthReport
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.releases.resolve import resolve_build
from flex_testing_agent.releases.urls import ReleaseChannel
from flex_testing_agent.releases.versions import normalize_robot_version
from flex_testing_agent.robots.flex import FlexRobot

log = get_logger(__name__)

INSTALL_DESCRIPTOR = CapabilityDescriptor(
    name="install_build",
    description=(
        "Download a published Flex robot OS system.zip and install it via "
        "update-server (/server/update/*). Restarts the robot."
    ),
    risk_level=RiskLevel.INSTALLATION,
    mutates_robot=True,
    requires_cleanup=False,
    max_execution_time_seconds=3600.0,
    required_robot_features=["system_update"],
    evidence_produced=[
        "build.json",
        "update_begin.json",
        "update_status_final.json",
        "post_install_health.json",
    ],
    preconditions=[
        "ALLOW_MUTATIONS=true",
        "ROBOT_HOST configured",
        "version exists in ot3-oe/releases.json",
    ],
)

_TERMINAL_BAD = frozenset({"error"})


async def install_build(
    robot: FlexRobot,
    version: str,
    *,
    channel: ReleaseChannel | None = None,
    download_directory: Path | None = None,
    auto_commit_and_restart: bool = True,
    poll_interval_seconds: float = 2.0,
    write_timeout_seconds: float = 1800.0,
    reboot_timeout_seconds: float = 900.0,
) -> InstallResult:
    """Put the robot on ``version`` by installing the published system.zip.

    Requires ``ALLOW_MUTATIONS=true``. Physical motion is not involved.
    """
    settings = robot.settings
    ensure_mutation_allowed(
        settings,
        risk_level=INSTALL_DESCRIPTOR.risk_level,
        capability_name=INSTALL_DESCRIPTOR.name,
    )
    settings.require_robot_host()

    build = await resolve_build(
        version,
        channel=channel,
        timeout_seconds=settings.robot_request_timeout_seconds,
    )
    previous = await _safe_system_version(robot)
    if _versions_match(previous, build.version):
        return InstallResult(
            requested_version=build.version,
            channel=build.channel,
            previous_system_version=previous,
            resulting_system_version=previous,
            succeeded=True,
            detail="Robot already reports the requested system version.",
        )

    dl_dir = download_directory or (settings.ensure_artifact_directory() / "downloads")
    zip_path = dl_dir / f"ot3-system-{build.version}.zip"
    log.info(
        "download_system_zip",
        version=build.version,
        url=build.system_url,
        destination=str(zip_path),
    )
    await download_file(
        build.system_url,
        zip_path,
        timeout_seconds=max(600.0, write_timeout_seconds),
    )

    update = robot.update
    with contextlib.suppress(RobotApiError):
        await update.cancel(timeout=settings.robot_request_timeout_seconds)

    begin = await update.begin(
        auto_commit_and_restart=auto_commit_and_restart,
        timeout=settings.robot_request_timeout_seconds,
    )
    token = str(begin.get("token", ""))
    if not token:
        raise RobotApiError(
            "update begin response missing token",
            path="/server/update/begin",
        )
    # Older update-servers ignore auto_commit_and_restart and always act as false.
    server_auto = bool(begin.get("auto_commit_and_restart", False))
    effective_auto = auto_commit_and_restart and server_auto

    robot.raw_evidence["build"] = build.model_dump(mode="json")
    robot.raw_evidence["update_begin"] = begin

    log.info(
        "upload_system_zip",
        token=token,
        path=str(zip_path),
        effective_auto_commit=effective_auto,
    )
    upload_status = await update.upload_system_update(
        token,
        zip_path,
        timeout=max(600.0, write_timeout_seconds),
    )
    robot.raw_evidence["update_upload"] = upload_status

    final_status = await _poll_until_terminal(
        update,
        token,
        auto_commit_and_restart=effective_auto,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=write_timeout_seconds,
    )
    robot.raw_evidence["update_status_final"] = final_status
    stage = str(final_status.get("stage", ""))
    if stage in _TERMINAL_BAD:
        return InstallResult(
            requested_version=build.version,
            channel=build.channel,
            previous_system_version=previous,
            session_token=token,
            artifact_path=str(zip_path),
            auto_commit_and_restart=effective_auto,
            succeeded=False,
            detail=f"Update failed: {final_status}",
        )

    if not effective_auto:
        if stage == "done":
            commit_status = await update.commit(
                token, timeout=settings.robot_request_timeout_seconds
            )
            robot.raw_evidence["update_commit"] = commit_status
        await update.restart(timeout=settings.robot_request_timeout_seconds)

    resulting = await _wait_for_reboot_and_version(
        settings,
        expected_version=build.version,
        timeout_seconds=reboot_timeout_seconds,
        poll_interval_seconds=5.0,
    )
    robot.raw_evidence["post_install_health"] = resulting["health_raw"]
    resulting_version = resulting["system_version"]

    matched = _versions_match(resulting_version, build.version)
    return InstallResult(
        requested_version=build.version,
        channel=build.channel,
        previous_system_version=previous,
        resulting_system_version=resulting_version,
        session_token=token,
        artifact_path=str(zip_path),
        auto_commit_and_restart=effective_auto,
        succeeded=matched,
        detail=(
            "Install succeeded."
            if matched
            else (
                "Robot came back but system version did not match "
                f"(expected {build.version}, got {resulting_version})."
            )
        ),
        evidence_names=list(robot.raw_evidence.keys()),
    )


async def _poll_until_terminal(
    update: UpdateClient,
    token: str,
    *,
    auto_commit_and_restart: bool,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last: dict[str, object] = {}
    while asyncio.get_running_loop().time() < deadline:
        try:
            last = await update.status(token, timeout=30.0)
        except RobotApiError as exc:
            # Robot may restart mid-poll when auto_commit_and_restart is true.
            log.info("status_poll_interrupted", error=str(exc))
            return {"stage": "ready-for-restart", "message": str(exc), **last}
        stage = str(last.get("stage", ""))
        log.info(
            "update_status",
            stage=stage,
            progress=last.get("progress"),
            message=last.get("message"),
        )
        if stage in _TERMINAL_BAD:
            return last
        if auto_commit_and_restart:
            # With auto mode, "done" is intermediate; wait for restart or drop.
            if stage == "ready-for-restart":
                return last
        elif stage in {"done", "ready-for-restart"}:
            return last
        await asyncio.sleep(poll_interval_seconds)
    raise RobotApiError(
        f"Timed out waiting for update session {token} after {timeout_seconds}s",
        path=f"/server/update/{token}/status",
    )


async def _wait_for_reboot_and_version(
    settings: Settings,
    *,
    expected_version: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """Wait for the robot to become healthy after restart."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    # Give the robot a moment to drop offline after restart is triggered.
    await asyncio.sleep(15.0)
    last_error = "not reached"
    while asyncio.get_running_loop().time() < deadline:
        try:
            async with FlexRobot(settings) as probe:
                raw = await probe.health.get_health_raw(
                    timeout=settings.robot_health_timeout_seconds
                )
                health = HealthReport.model_validate(raw)
                system_version = health.system_version
                log.info(
                    "post_reboot_health",
                    system_version=system_version,
                    api_version=health.api_version,
                    at=datetime.now(UTC).isoformat(),
                )
                return {
                    "system_version": system_version,
                    "api_version": health.api_version,
                    "health_raw": raw,
                    "expected_version": expected_version,
                }
        except Exception as exc:
            last_error = str(exc)
            log.info("waiting_for_robot", error=last_error)
            await asyncio.sleep(poll_interval_seconds)
    raise RobotApiError(
        f"Timed out waiting for robot reboot ({last_error})",
        path="/health",
    )


async def _safe_system_version(robot: FlexRobot) -> str | None:
    try:
        health = await robot.verify_health()
        return health.system_version
    except RobotApiError:
        return None


def _versions_match(actual: str | None, expected: str) -> bool:
    if actual is None:
        return False
    left = normalize_robot_version(actual)
    right = normalize_robot_version(expected)
    return left is not None and left == right


__all__ = ["INSTALL_DESCRIPTOR", "install_build"]
