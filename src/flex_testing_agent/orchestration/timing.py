"""Structured latency / duration recording for build comparisons.

Writes JSON under ``ARTIFACT_DIRECTORY/timing/``. Safe for one-off CLI use and
suite imports. See ``docs/known-state-and-latency.md``.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TimingSpan(BaseModel):
    """One named duration measurement."""

    name: str
    started_at: str
    ended_at: str | None = None
    duration_seconds: float | None = None
    ok: bool = True
    detail: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class TimingReport(BaseModel):
    """Collection of spans for one harness operation."""

    report_id: str
    label: str
    created_at: str
    robot_host: str | None = None
    system_version: str | None = None
    api_version: str | None = None
    channel: str | None = None
    spans: list[TimingSpan] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def span_map(self) -> dict[str, TimingSpan]:
        """Last span per name (later overwrites earlier)."""
        return {span.name: span for span in self.spans}


@dataclass
class TimingSession:
    """Mutable in-progress timing report."""

    label: str
    robot_host: str | None = None
    system_version: str | None = None
    api_version: str | None = None
    channel: str | None = None
    report_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    spans: list[TimingSpan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    _open: dict[str, tuple[float, str, dict[str, Any]]] = field(default_factory=dict)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def is_open(self, name: str) -> bool:
        """Return True if ``name`` was started and not yet stopped."""
        return name in self._open

    def start(self, name: str, *, meta: dict[str, Any] | None = None) -> None:
        """Begin a span (must :meth:`stop` or :meth:`fail`)."""
        self._open[name] = (
            time.perf_counter(),
            datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            dict(meta or {}),
        )

    def stop(
        self,
        name: str,
        *,
        ok: bool = True,
        detail: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TimingSpan:
        """End a previously started span."""
        if name not in self._open:
            span = TimingSpan(
                name=name,
                started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                ended_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                duration_seconds=0.0,
                ok=False,
                detail=detail or "stop() without start()",
                meta=dict(meta or {}),
            )
            self.spans.append(span)
            return span
        t0, started_at, start_meta = self._open.pop(name)
        merged = {**start_meta, **(meta or {})}
        ended_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        span = TimingSpan(
            name=name,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=time.perf_counter() - t0,
            ok=ok,
            detail=detail,
            meta=merged,
        )
        self.spans.append(span)
        return span

    def fail(
        self, name: str, detail: str, *, meta: dict[str, Any] | None = None
    ) -> TimingSpan:
        return self.stop(name, ok=False, detail=detail, meta=meta)

    def record(
        self,
        name: str,
        duration_seconds: float,
        *,
        ok: bool = True,
        detail: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TimingSpan:
        """Append an already-measured span (e.g. per-endpoint latency)."""
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        span = TimingSpan(
            name=name,
            started_at=now,
            ended_at=now,
            duration_seconds=duration_seconds,
            ok=ok,
            detail=detail,
            meta=dict(meta or {}),
        )
        self.spans.append(span)
        return span

    @contextmanager
    def span(self, name: str, *, meta: dict[str, Any] | None = None) -> Iterator[None]:
        """Sync context manager for a timed block."""
        self.start(name, meta=meta)
        try:
            yield
        except Exception as exc:
            self.fail(name, str(exc))
            raise
        else:
            self.stop(name)

    @asynccontextmanager
    async def aspan(
        self, name: str, *, meta: dict[str, Any] | None = None
    ) -> AsyncIterator[None]:
        """Async context manager for a timed block."""
        self.start(name, meta=meta)
        try:
            yield
        except Exception as exc:
            self.fail(name, str(exc))
            raise
        else:
            self.stop(name)

    def report(self) -> TimingReport:
        for name in list(self._open):
            self.fail(name, "span left open at report()")
        return TimingReport(
            report_id=self.report_id,
            label=self.label,
            created_at=self.created_at,
            robot_host=self.robot_host,
            system_version=self.system_version,
            api_version=self.api_version,
            channel=self.channel,
            spans=list(self.spans),
            notes=list(self.notes),
        )

    def write(self, directory: Path) -> Path:
        """Write report JSON; return path."""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.label}-{self.report_id}.json"
        payload = self.report().model_dump(mode="json")
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path


def load_timing_reports(directory: Path) -> list[TimingReport]:
    """Load all timing JSON files from a directory (newest name last)."""
    if not directory.is_dir():
        return []
    reports: list[TimingReport] = []
    for path in sorted(directory.glob("*.json")):
        try:
            reports.append(
                TimingReport.model_validate_json(path.read_text(encoding="utf-8"))
            )
        except Exception:
            continue
    return reports
