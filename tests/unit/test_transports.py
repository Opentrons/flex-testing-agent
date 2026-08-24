"""Unit tests for lab SSH argv and transport assessment."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from flex_testing_agent.config.settings import Settings
from flex_testing_agent.lab_ssh.probe import LabSshStatus, ssh_argv
from flex_testing_agent.models.access_control import (
    AccessControlState,
    AccessControlStatus,
)
from flex_testing_agent.models.snapshot import RobotSnapshot
from flex_testing_agent.orchestration.transports import (
    assess_transports,
    probe_carveout_status,
)
from flex_testing_agent.serial_console.remote_access import RemoteAccessStatus


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        robot_host="192.168.0.21",
        robot_host_candidates="",
        robot_name="KansasFLEX",
        robot_http_port=31950,
        robot_https_port=32313,
        robot_use_https=True,
        robot_ssh_port=22,
        robot_ssh_user="root",
        robot_ssh_identity=tmp_path / "robot_key",
        robot_health_timeout_seconds=1.0,
        robot_ssh_timeout_seconds=1.0,
    )


@pytest.mark.unit
def test_ssh_argv_includes_identity_and_batchmode(tmp_path: Path) -> None:
    key = tmp_path / "robot_key"
    key.write_text("dummy")
    settings = _settings(tmp_path)
    argv = ssh_argv(settings, "true", identity=key)
    assert argv[0] == "ssh"
    assert "BatchMode=yes" in argv
    assert "-i" in argv
    assert argv[argv.index("-i") + 1] == str(key)
    assert argv[-2] == "root@192.168.0.21"
    assert argv[-1] == "true"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_assess_transports_crs_on_flags_plaintext_and_prefers_ssh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    snapshot = RobotSnapshot(
        configured_name="KansasFLEX",
        host="192.168.0.21",
        base_url="https://192.168.0.21:32313",
        connectivity=True,
        access_control=AccessControlStatus(
            state=AccessControlState.ENABLED,
            raw_enabled=True,
        ),
    )

    async def _plain(_settings: Settings) -> bool:
        return True

    async def _ssh(_settings: Settings) -> LabSshStatus:
        return LabSshStatus(
            host="192.168.0.21",
            port=22,
            tcp_reachable=True,
            authenticated=True,
            identity_path=tmp_path / "robot_key",
            detail="BatchMode SSH authenticated.",
        )

    monkeypatch.setattr(
        "flex_testing_agent.orchestration.transports.probe_plaintext_http_health",
        _plain,
    )
    monkeypatch.setattr(
        "flex_testing_agent.orchestration.transports.probe_lab_ssh",
        _ssh,
    )
    assessment = await assess_transports(settings, snapshot)
    assert assessment.crs_on is True
    assert assessment.plaintext_http_reachable is True
    assert assessment.recommended_shell == "ssh"
    assert any("RQA-5981" in note for note in assessment.notes)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_probe_plaintext_http_health_uses_http_port(
    tmp_path: Path,
) -> None:
    from flex_testing_agent.orchestration.transports import probe_plaintext_http_health

    settings = _settings(tmp_path).model_copy(update={"robot_use_https": True})
    respx.get("http://192.168.0.21:31950/health").mock(
        return_value=httpx.Response(200, json={"name": "KansasFLEX"})
    )
    assert await probe_plaintext_http_health(settings) is True


@pytest.mark.unit
def test_probe_carveout_prefers_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    (tmp_path / "robot_key").write_text("dummy")
    monkeypatch.setattr(
        "flex_testing_agent.orchestration.transports.run_lab_ssh",
        lambda _s, _cmd, timeout=30.0: SimpleNamespace(
            returncode=0,
            stdout="ALLOW_FILE=yes\nactive\n",
            stderr="",
        ),
    )
    probe = probe_carveout_status(
        settings,
        serial_port=None,
        baudrate=115200,
        timeout=5.0,
        prefer_ssh=True,
    )
    assert probe.transport == "ssh"
    assert probe.status.likely_allowed is True


@pytest.mark.unit
def test_probe_carveout_raises_when_ssh_and_serial_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        "flex_testing_agent.orchestration.transports.run_lab_ssh",
        lambda _s, _cmd, timeout=30.0: None,
    )
    with pytest.raises(ValueError, match="no serial port"):
        probe_carveout_status(
            settings,
            serial_port=None,
            baudrate=115200,
            timeout=5.0,
            prefer_ssh=True,
        )


@pytest.mark.unit
def test_parse_remote_access_status_shape() -> None:
    status = RemoteAccessStatus(
        allow_file_present=False,
        unit_active="inactive",
        raw="ALLOW_FILE=no\ninactive\n",
    )
    assert status.likely_allowed is False
