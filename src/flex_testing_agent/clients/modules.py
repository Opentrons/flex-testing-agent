"""Attached-modules client (``GET /modules``) and temp-module commands."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flex_testing_agent.clients.session import RobotHttpSession

WaitMode = Literal["absent", "present", "unique"]


class ModuleSnapshot(BaseModel):
    """One attached module from ``GET /modules``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    serial_number: str = Field(alias="serialNumber")
    module_type: str = Field(alias="moduleType")
    module_model: str = Field(alias="moduleModel")
    firmware_version: str | None = Field(default=None, alias="firmwareVersion")
    status: str | None = None
    current_temperature: float | None = Field(default=None, alias="currentTemperature")
    usb_port: dict[str, Any] | None = Field(default=None, alias="usbPort")
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_temperature(self) -> bool:
        return self.module_type == "temperatureModuleType"


class ModulesInventory(BaseModel):
    """Normalized module list with duplicate-serial helpers."""

    modules: list[ModuleSnapshot]
    fetched_at: float

    @property
    def count(self) -> int:
        return len(self.modules)

    def by_serial(self, serial: str) -> list[ModuleSnapshot]:
        return [m for m in self.modules if m.serial_number == serial]

    def temperature_modules(self) -> list[ModuleSnapshot]:
        return [m for m in self.modules if m.is_temperature]

    def duplicate_serials(self) -> list[str]:
        counts: dict[str, int] = {}
        for module in self.modules:
            counts[module.serial_number] = counts.get(module.serial_number, 0) + 1
        return sorted(serial for serial, count in counts.items() if count > 1)


class ModulesClient:
    """Atomic client for module inventory and stateless temp commands."""

    def __init__(self, session: RobotHttpSession) -> None:
        self._session = session

    async def list_modules(self) -> ModulesInventory:
        """GET ``/modules`` and normalize attached modules."""
        payload = await self._session.get_json("/modules")
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            items = []
        modules: list[ModuleSnapshot] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_data = item.get("data")
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
            modules.append(
                ModuleSnapshot.model_validate(
                    {
                        **item,
                        "status": data.get("status"),
                        "currentTemperature": data.get("currentTemperature"),
                        "raw": item,
                    }
                )
            )
        return ModulesInventory(modules=modules, fetched_at=time.time())

    async def wait_for(
        self,
        *,
        mode: WaitMode,
        serial: str | None = None,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
    ) -> ModulesInventory:
        """Poll ``GET /modules`` until a presence condition holds."""
        deadline = time.monotonic() + timeout_seconds
        last = await self.list_modules()
        while time.monotonic() < deadline:
            last = await self.list_modules()
            if mode == "absent":
                if serial is None:
                    if last.count == 0:
                        return last
                elif not last.by_serial(serial):
                    return last
            elif mode == "present":
                if serial is None:
                    if last.count >= 1:
                        return last
                elif last.by_serial(serial):
                    return last
            elif mode == "unique":
                matches = last.modules if serial is None else last.by_serial(serial)
                if len(matches) == 1 and not last.duplicate_serials():
                    return last
            await asyncio.sleep(poll_interval_seconds)
        raise TimeoutError(
            f"Timed out waiting for modules mode={mode!r} serial={serial!r}; "
            f"last_count={last.count} serials="
            f"{[m.serial_number for m in last.modules]}"
        )

    async def set_temperature_and_wait(
        self,
        *,
        module_id: str,
        celsius: float,
        timeout_ms: int = 60_000,
    ) -> dict[str, Any]:
        """Set target temperature and wait for command completion."""
        path = f"/commands?waitUntilComplete=true&timeout={timeout_ms}"
        return await self._session.post_json(
            path,
            json_body={
                "data": {
                    "commandType": "temperatureModule/setTargetTemperature",
                    "params": {"moduleId": module_id, "celsius": celsius},
                }
            },
            timeout=max(timeout_ms / 1000.0 + 5.0, 30.0),
            expected_status=(201,),
        )

    async def deactivate_temperature(
        self,
        *,
        module_id: str,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        """POST ``temperatureModule/deactivate`` and wait."""
        path = f"/commands?waitUntilComplete=true&timeout={timeout_ms}"
        return await self._session.post_json(
            path,
            json_body={
                "data": {
                    "commandType": "temperatureModule/deactivate",
                    "params": {"moduleId": module_id},
                }
            },
            timeout=max(timeout_ms / 1000.0 + 5.0, 30.0),
            expected_status=(201,),
        )
