#!/usr/bin/env python3
"""Regenerate ``flex_testing_agent.catalog.endpoints`` from a monorepo clone.

Requires ``upstream/opentrons`` (or set OPENTRONS_REPO_PATH). Run from repo root:

    uv run python scripts/generate_endpoint_catalog.py
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MONOREPO = Path(
    os.environ.get("OPENTRONS_REPO_PATH", REPO_ROOT / "upstream" / "opentrons")
)
OUT = REPO_ROOT / "src" / "flex_testing_agent" / "catalog" / "endpoints.py"

PHYSICAL = {
    ("POST", "/robot/home"),
    ("POST", "/robot/move"),
    ("POST", "/motors/disengage"),
    ("POST", "/runs/{runId}/actions"),
    ("POST", "/maintenance_runs/{runId}/commands"),
    ("POST", "/runs/{runId}/commands"),
    ("POST", "/commands"),
}
INSTALLATION = {
    ("POST", "/server/update/begin"),
    ("POST", "/server/update/{session}/file"),
    ("POST", "/server/update/{session}/commit"),
    ("POST", "/modules/{serial}/update"),
    ("POST", "/subsystems/updates/{subsystem}"),
}
DESTRUCTIVE = {
    ("POST", "/settings/reset"),
    ("POST", "/server/shutdown"),
    ("DELETE", "/server/ssh_keys"),
    ("PUT", "/system/oem_mode/enable"),
}
BLOCKED = {("PATCH", "/auth/settings/accessControlEnabled")}
DISRUPTIVE = {
    ("POST", "/server/restart"),
    ("POST", "/server/name"),
    ("POST", "/wifi/configure"),
    ("POST", "/wifi/disconnect"),
    ("POST", "/wifi/keys"),
    ("DELETE", "/wifi/keys/{key_uuid}"),
    ("POST", "/server/ssh_keys"),
    ("POST", "/server/ssh_keys/from_local"),
    ("DELETE", "/server/ssh_keys/{key_md5}"),
    ("PUT", "/system/time"),
    ("DELETE", "/protocols/{protocolId}"),
    ("DELETE", "/runs/{runId}"),
    ("DELETE", "/maintenance_runs/{runId}"),
    ("DELETE", "/dataFiles/{dataFileId}"),
    ("DELETE", "/dataFiles/{runId}/images"),
    ("DELETE", "/labwareOffsets"),
    ("DELETE", "/auth/users/byUsername/{username}"),
    ("DELETE", "/auth/settings"),
}

SCOPE_API = {
    "Scope.AUTH_SETTINGS_WRITE": "auth_settings.write",
    "Scope.PROTOCOLS_WRITE": "protocols.write",
    "Scope.RESTART_WRITE": "restart.write",
    "Scope.SHUTDOWN_WRITE": "shutdown.write",
    "Scope.ROBOT_CONTROL_WRITE": "robot_control.write",
    "Scope.ROBOT_SETTINGS_WRITE": "robot_settings.write",
    "Scope.RUN_DATA_WRITE": "run_data.write",
    "Scope.SSH_KEYS_WRITE": "ssh_keys.write",
    "Scope.UPDATES_WRITE": "updates.write",
    "Scope.USERS_READ_OTHERS": "users.read.others",
    "Scope.USERS_READ_SELF": "users.read.self",
    "Scope.USERS_WRITE_SELF": "users.write.self",
    "Scope.USERS_WRITE": "users.write",
}

ACCEPTABLE_OVERRIDES: dict[tuple[str, str], tuple[int, ...]] = {
    ("GET", "/server/ssh_keys"): (200, 403),
    ("GET", "/motors/engaged"): (200, 500),
    ("GET", "/maintenance_runs/current_run"): (200, 404),
    ("GET", "/calibration/pipette_offset"): (200, 403),
    ("GET", "/calibration/tip_length"): (200, 403),
    ("GET", "/settings/pipettes"): (200, 403),
    ("GET", "/settings/pipettes/{pipette_id}"): (200, 403),
    ("GET", "/labware/calibrations"): (200, 410),
    ("GET", "/labware/calibrations/{calibrationId}"): (200, 404, 410),
    ("GET", "/auth/users/self"): (200, 401, 403, 404),
    ("GET", "/auth/users/byUsername/{username}"): (200, 401, 403, 404),
    ("GET", "/system/authorize"): (200, 401, 403, 422),
    ("GET", "/system/connected"): (200, 404),
    ("GET", "/audit/external/logPeriods"): (200, 404),
    ("GET", "/audit/external/settings"): (200, 404),
    ("GET", "/audit/internal/loggingEnabled"): (200, 404),
    ("GET", "/robot/positions"): (200, 403, 500),
}

NOTES_OVERRIDES = {
    ("GET", "/server/ssh_keys"): "Often 403 without elevated credentials.",
    ("GET", "/motors/engaged"): "Flex often returns 500; treat as known soft failure.",
    ("GET", "/maintenance_runs/current_run"): "404 when no maintenance run is active.",
    ("GET", "/calibration/pipette_offset"): "Legacy OT-2 path; Flex often returns 403.",
    ("GET", "/calibration/tip_length"): "Legacy OT-2 path; Flex often returns 403.",
    ("GET", "/settings/pipettes"): (
        "OT-2 only (NotSupportedOnFlex); Flex returns 403 by design."
    ),
    ("GET", "/settings/pipettes/{pipette_id}"): (
        "OT-2 only (NotSupportedOnFlex); Flex returns 403 by design."
    ),
    ("GET", "/labware/calibrations"): (
        "Removed on Flex (LabwareCalibrationEndpointsRemoved); expect 410."
    ),
    ("GET", "/labware/calibrations/{calibrationId}"): (
        "Removed on Flex (LabwareCalibrationEndpointsRemoved); expect 410."
    ),
    ("GET", "/auth/users/byUsername/{username}"): (
        "Auth-server user lookup; CRS-off often 401/404 without a real user."
    ),
    ("GET", "/system/authorize"): (
        "Deprecated; bare GET without authenticationBearer header yields 422."
    ),
    ("PATCH", "/auth/settings/accessControlEnabled"): (
        "ONE-WAY CRS enable. Harness never calls this."
    ),
    ("GET", "/wifi/list"): "Wi-Fi scan; may be slow.",
    ("GET", "/robot/positions"): "Legacy control path; may 403/500 depending on build.",
    ("GET", "/runs/{runId}/commandsAsPreSerializedList"): (
        "Only available after a run has ended (PreSerializedCommandsNotAvailable "
        "while current/active). Tier B probes an ended run; do not soft-accept 503."
    ),
    (
        "GET",
        "/audit/external/logPeriods",
    ): "Audit-server; may be absent on older builds.",
    ("GET", "/audit/external/settings"): "Audit-server; may be absent on older builds.",
    ("GET", "/audit/internal/loggingEnabled"): (
        "Audit-server; may be absent on older builds."
    ),
}

TIMEOUT_OVERRIDES = {("GET", "/wifi/list"): 60.0}

DECO = re.compile(
    r'@(\w+)\.(get|post|put|patch|delete|head|options)\(\s*(?:path\s*=\s*)?["\']([^"\']+)["\']',
    re.M,
)
WRAP = re.compile(
    r'wrap_route\(\s*(\w+)\.(get|post|put|patch|delete)\s*,\s*path\s*=\s*["\']([^"\']+)["\']',
    re.M,
)
PATH_CONST = re.compile(
    r"wrap_route\(\s*(\w+)\.(get|post|put|patch|delete)\s*,\s*path\s*=\s*(\w+)",
    re.M,
)
ASSIGN_PATH = re.compile(r'^(\w+)\s*=\s*["\']([^"\']+)["\']', re.M)
ASSIGN_ROUTER = re.compile(r"(\w+)\s*=\s*(?:LightRouter|APIRouter)\(([^)]*)\)")


def group_for(path: str) -> str:
    if path.startswith("/auth") or path.startswith("/oauth2"):
        return "auth"
    if path.startswith("/audit"):
        return "audit"
    if path.startswith("/server"):
        return "update"
    if path.startswith("/system") or path == "/health":
        return "system"
    if path.startswith(
        (
            "/runs",
            "/protocols",
            "/maintenance_runs",
            "/commands",
            "/sessions",
            "/dataFiles",
        )
    ):
        return "protocols"
    if path in {"/instruments", "/modules", "/pipettes"}:
        return "hardware"
    if path.startswith(
        ("/robot", "/motors", "/subsystems", "/instruments", "/modules", "/pipettes")
    ):
        return "robot"
    if path.startswith(
        ("/calibration", "/labware", "/labwareOffsets", "/deck_configuration")
    ):
        return "calibration"
    if path.startswith("/camera"):
        return "camera"
    if path.startswith(("/wifi", "/networking")):
        return "network"
    if path.startswith(
        ("/settings", "/accessControl", "/errorRecovery", "/clientData")
    ):
        return "settings"
    if path.startswith("/logs"):
        return "logs"
    return "other"


def risk_for(method: str, path: str) -> tuple[str, bool]:
    key = (method, path)
    if key in BLOCKED:
        return "DISRUPTIVE", True
    if method in ("GET", "HEAD", "OPTIONS"):
        return "READ_ONLY", False
    if key in PHYSICAL:
        return "PHYSICAL_MOTION", False
    if key in INSTALLATION:
        return "INSTALLATION", False
    if key in DESTRUCTIVE:
        return "DESTRUCTIVE", False
    if key in DISRUPTIVE:
        return "DISRUPTIVE", False
    return "REVERSIBLE_MUTATION", False


def name_for(method: str, path: str) -> str:
    slug = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", slug)
    return f"{method.lower()}_{slug}" if slug else f"{method.lower()}_root"


def collect_routes() -> dict[tuple[str, str, str], tuple[str, str]]:
    if not MONOREPO.is_dir():
        raise SystemExit(f"Monorepo not found at {MONOREPO}")

    roots = {
        "robot-server": MONOREPO / "robot-server" / "robot_server",
        "auth-server": MONOREPO / "auth-server" / "auth_server",
        "system-server": MONOREPO / "system-server" / "system_server",
        "audit-server": MONOREPO / "audit-server",
    }
    seen: dict[tuple[str, str, str], tuple[str, str]] = {}

    def add(svc: str, method: str, path: str, scopes: str, source: str) -> None:
        if path == "/some/path":
            return
        key = (svc, method.upper(), path)
        prev = seen.get(key)
        if prev is None or (scopes and not prev[0]):
            seen[key] = (scopes, source)

    for svc, root in roots.items():
        if not root.exists():
            print(f"warning: missing {root}", file=sys.stderr)
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            prefixes: dict[str, str] = {}
            for m in ASSIGN_ROUTER.finditer(text):
                var, args = m.group(1), m.group(2)
                pm = re.search(r'prefix\s*=\s*["\']([^"\']+)["\']', args)
                prefixes[var] = pm.group(1) if pm else ""
            consts = dict(ASSIGN_PATH.findall(text))
            rel = str(path.relative_to(MONOREPO))
            for rx in (DECO, WRAP):
                for m in rx.finditer(text):
                    var, method, route = m.group(1), m.group(2), m.group(3)
                    pref = prefixes.get(var, "")
                    full = f"{pref.rstrip('/')}/{route.lstrip('/')}" if pref else route
                    full = "/" + full.lstrip("/")
                    while "//" in full:
                        full = full.replace("//", "/")
                    if full != "/" and full.endswith("/"):
                        full = full[:-1]
                    chunk = text[
                        max(0, m.start() - 1000) : min(len(text), m.end() + 600)
                    ]
                    scopes = "; ".join(
                        dict.fromkeys(
                            s.strip()
                            for s in re.findall(r"require_scopes\(([^)]+)\)", chunk)
                        )
                    )
                    add(svc, method, full, scopes, rel)
            for m in PATH_CONST.finditer(text):
                var, method, const = m.group(1), m.group(2), m.group(3)
                if const not in consts:
                    continue
                route = consts[const]
                pref = prefixes.get(var, "")
                full = f"{pref.rstrip('/')}/{route.lstrip('/')}" if pref else route
                full = "/" + full.lstrip("/")
                while "//" in full:
                    full = full.replace("//", "/")
                chunk = text[max(0, m.start() - 1000) : min(len(text), m.end() + 600)]
                scopes = "; ".join(
                    dict.fromkeys(
                        s.strip()
                        for s in re.findall(r"require_scopes\(([^)]+)\)", chunk)
                    )
                )
                add(svc, method, full, scopes, rel)

    oe = MONOREPO / "update-server" / "otupdate" / "openembedded" / "__init__.py"
    if oe.exists():
        text = oe.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(
            r'web\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', text
        ):
            add(
                "update-server",
                m.group(1),
                m.group(2),
                "",
                "update-server/otupdate/openembedded/__init__.py",
            )
    return seen


def main() -> None:
    seen = collect_routes()
    svc_enum = {
        "robot-server": "ApiService.ROBOT_SERVER",
        "auth-server": "ApiService.AUTH_SERVER",
        "update-server": "ApiService.UPDATE_SERVER",
        "system-server": "ApiService.SYSTEM_SERVER",
        "audit-server": "ApiService.AUDIT_SERVER",
    }
    entries: list[tuple[object, ...]] = []
    for (svc, method, path), (scopes_raw, _source) in sorted(seen.items()):
        risk, blocked = risk_for(method, path)
        group = group_for(path)
        scopes: list[str] = []
        for tok in re.findall(r"Scope\.[A-Z_]+", scopes_raw):
            if tok in SCOPE_API and SCOPE_API[tok] not in scopes:
                scopes.append(SCOPE_API[tok])
        scopes_t = tuple(scopes)
        param = "{" in path
        if method == "GET":
            acc = ACCEPTABLE_OVERRIDES.get((method, path), (200,))
        else:
            acc = (200, 201, 204)
        notes = NOTES_OVERRIDES.get((method, path), "")
        timeout = TIMEOUT_OVERRIDES.get((method, path), 30.0)
        entries.append(
            (
                name_for(method, path),
                method,
                path,
                svc,
                group,
                risk,
                scopes_t,
                param,
                blocked,
                notes,
                acc,
                timeout,
            )
        )

    name_counts = Counter(e[0] for e in entries)
    final: list[tuple[object, ...]] = []
    used: Counter[str] = Counter()
    for entry in entries:
        name = str(entry[0])
        if name_counts[name] > 1:
            used[name] += 1
            name = f"{name}_{used[name]}"
        final.append((name, *entry[1:]))

    lines = [
        '"""Flex HTTP API endpoint catalog derived from the monorepo.',
        "",
        "Source services: robot-server, auth-server, update-server (OE),",
        "system-server, audit-server.",
        "",
        "Regenerate with:",
        "  uv run python scripts/generate_endpoint_catalog.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from dataclasses import dataclass",
        "from enum import StrEnum",
        "",
        "from flex_testing_agent.models.risk import RiskLevel",
        "",
        "",
        "class HttpMethod(StrEnum):",
        '    """HTTP methods exercised by the CRS endpoint matrix."""',
        "",
    ]
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        lines.append(f'    {method} = "{method}"')
    lines.extend(
        [
            "",
            "",
            "class ApiService(StrEnum):",
            '    """Owning Flex HTTP service."""',
            "",
            '    ROBOT_SERVER = "robot-server"',
            '    AUTH_SERVER = "auth-server"',
            '    UPDATE_SERVER = "update-server"',
            '    SYSTEM_SERVER = "system-server"',
            '    AUDIT_SERVER = "audit-server"',
            "",
            "",
            "@dataclass(frozen=True)",
            "class EndpointSpec:",
            '    """One Flex HTTP endpoint for CRS-off / CRS-on matrix testing."""',
            "",
            "    name: str",
            "    method: HttpMethod",
            "    path: str",
            "    service: ApiService",
            "    group: str",
            "    risk_level: RiskLevel",
            "    required_scopes: tuple[str, ...] = ()",
            "    parameterized: bool = False",
            "    blocked: bool = False",
            '    notes: str = ""',
            "    crs_off_acceptable_status: tuple[int, ...] = (200,)",
            "    timeout_seconds: float = 30.0",
            "",
            "",
            "FLEX_HTTP_ENDPOINTS: tuple[EndpointSpec, ...] = (",
        ]
    )
    for (
        name,
        method,
        path,
        svc,
        group,
        risk,
        scopes,
        param,
        blocked,
        notes,
        acc,
        timeout,
    ) in final:
        scope_lit = ", ".join(f'"{s}"' for s in scopes)  # type: ignore[arg-type]
        acc_lit = ", ".join(str(x) for x in acc)  # type: ignore[arg-type]
        notes_esc = str(notes).replace("\\", "\\\\").replace('"', '\\"')
        lines.append("    EndpointSpec(")
        lines.append(f'        name="{name}",')
        lines.append(f"        method=HttpMethod.{method},")
        lines.append(f'        path="{path}",')
        lines.append(f"        service={svc_enum[str(svc)]},")
        lines.append(f'        group="{group}",')
        lines.append(f"        risk_level=RiskLevel.{risk},")
        if scopes:
            lines.append(f"        required_scopes=({scope_lit},),")
        if param:
            lines.append("        parameterized=True,")
        if blocked:
            lines.append("        blocked=True,")
        if notes:
            lines.append(f'        notes="{notes_esc}",')
        if acc != (200,):
            lines.append(f"        crs_off_acceptable_status=({acc_lit},),")
        if timeout != 30.0:
            lines.append(f"        timeout_seconds={timeout},")
        lines.append("    ),")
    lines.extend(
        [
            ")",
            "",
            "",
            "def endpoints_for_crs_off_get_probe() -> tuple[EndpointSpec, ...]:",
            '    """Parameter-free GET endpoints for unauthenticated CRS-off probing."""',
            "    return tuple(",
            "        ep",
            "        for ep in FLEX_HTTP_ENDPOINTS",
            "        if ep.method == HttpMethod.GET",
            "        and not ep.parameterized",
            "        and not ep.blocked",
            '        and "redoc" not in ep.path',
            "    )",
            "",
            "",
            "def endpoint_count_by_method() -> dict[str, int]:",
            '    """Return counts of catalogued endpoints by HTTP method."""',
            "    counts: dict[str, int] = {}",
            "    for ep in FLEX_HTTP_ENDPOINTS:",
            "        key = ep.method.value",
            "        counts[key] = counts.get(key, 0) + 1",
            "    return counts",
            "",
        ]
    )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(final)} endpoints to {OUT.relative_to(REPO_ROOT)}")
    print("By method:", dict(Counter(str(e[1]) for e in final)))


if __name__ == "__main__":
    main()
