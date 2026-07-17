"""Camera client for Flex on-board imaging.

Source: ``robot-server/robot_server/service/legacy/routers/camera.py``.

Read-only:
- ``GET /camera``
- ``GET /camera/stream``
- ``GET /camera/stream/settings``
- ``GET /camera/cameraSettings/{cameraId}``

Capture (requires camera enabled; write scope when AC is on):
- ``POST /camera/picture``
- ``POST /camera/capturePreviewImage``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from flex_testing_agent.clients.session import RobotHttpSession

DEFAULT_CAMERA_ID = "ot_system_camera"


class CameraClient:
    """Atomic client for Flex camera settings and capture."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def get_camera(self) -> dict[str, Any]:
        """GET camera enablement status."""
        return await self._session.get_json("/camera")

    async def get_stream(self) -> dict[str, Any]:
        """GET live-stream enablement and relative URLs."""
        return await self._session.get_json("/camera/stream")

    async def get_stream_settings(self) -> dict[str, Any]:
        """GET live-stream settings."""
        return await self._session.get_json("/camera/stream/settings")

    async def get_capture_settings(
        self, camera_id: str = DEFAULT_CAMERA_ID
    ) -> dict[str, Any]:
        """GET capture image settings for a camera id."""
        return await self._session.get_json(f"/camera/cameraSettings/{camera_id}")

    async def set_camera_enabled(
        self,
        *,
        camera_enabled: bool = True,
        live_stream_enabled: bool | None = None,
        error_recovery_camera_enabled: bool | None = None,
    ) -> dict[str, Any]:
        """POST camera enablement (mutating)."""
        data: dict[str, Any] = {"cameraEnabled": camera_enabled}
        if live_stream_enabled is not None:
            data["liveStreamEnabled"] = live_stream_enabled
        if error_recovery_camera_enabled is not None:
            data["errorRecoveryCameraEnabled"] = error_recovery_camera_enabled
        return await self._session.post_json("/camera", json_body={"data": data})

    async def take_picture(self, *, timeout: float = 60.0) -> bytes:
        """POST ``/camera/picture`` and return JPEG bytes."""
        content, _ = await self._session.post_bytes(
            "/camera/picture",
            timeout=timeout,
            expected_status=(200,),
        )
        return content

    async def capture_preview_image(
        self,
        *,
        resolution: tuple[int, int] | None = None,
        zoom: float | None = None,
        timeout: float = 60.0,
    ) -> bytes:
        """POST ``/camera/capturePreviewImage`` and return JPEG bytes."""
        data: dict[str, Any] = {"cameraId": DEFAULT_CAMERA_ID}
        if resolution is not None:
            data["resolution"] = list(resolution)
        if zoom is not None:
            data["zoom"] = zoom
        content, _ = await self._session.post_bytes(
            "/camera/capturePreviewImage",
            json_body={"data": data},
            timeout=timeout,
            expected_status=(200,),
        )
        return content

    async def save_picture(
        self,
        destination: Path,
        *,
        prefer_preview: bool = True,
        timeout: float = 60.0,
    ) -> Path:
        """Capture an image and write it to ``destination``."""
        if prefer_preview:
            try:
                content = await self.capture_preview_image(timeout=timeout)
            except Exception:
                content = await self.take_picture(timeout=timeout)
        else:
            content = await self.take_picture(timeout=timeout)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination
