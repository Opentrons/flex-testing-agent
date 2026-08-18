---
name: extend-flex-harness
description: >-
  Extends the flex-testing-agent harness by adding typed robot API clients,
  capabilities, CLI commands, and read-only endpoint coverage. Use when adding
  Flex HTTP endpoints, new inspect/probe/install/status/wait-health behavior,
  camera features, release tooling, or when the user asks to grow the harness
  instead of calling the robot ad hoc (no curl).
---

# Extend the Flex testing harness

## Goal

Grow `flex-testing-agent` through the existing layers. Do not bypass clients with
one-off httpx/curl in capabilities, CLI, or agent sessions.

**Agents operating KansasFLEX must not curl the robot.** If the CLI/capability
is missing, add it here first, then use it.

## Workflow

1. **Find the source of truth** in `upstream/opentrons` (robot-server / update-server / auth-server routers) or `docs/source-research.md`.
2. **Add or extend an atomic client** under `src/flex_testing_agent/clients/`.
   - Reuse `RobotHttpSession` (`get_json` / `post_json` / `get_bytes` / `post_bytes`).
   - Keep methods small and named after API paths.
   - Export from `clients/__init__.py` when it is part of the public client surface.
3. **Wire onto `FlexRobot`** (`robots/flex.py`) if operators should access it via the facade.
4. **For HTTP coverage**, update the CRS catalog (preferred) then probe GETs:
   - Regenerate or extend `catalog/endpoints.py` (`scripts/generate_endpoint_catalog.py`)
   - Parameter-free GETs flow into `READONLY_ENDPOINTS` via `endpoints_for_crs_off_get_probe`
   - Use `crs_off_acceptable_status` / notes for expected 403/404
   - See `docs/crs-testing.md`
5. **For an operation**, add a capability in `capabilities/`:
   - `CapabilityDescriptor` with risk level and evidence list
   - Call `ensure_mutation_allowed` when risk is mutating
   - Store useful payloads on `robot.raw_evidence`
6. **Expose via CLI** only as a thin Typer command in `cli/main.py` (`flex-test …`).
7. **Tests**: unit tests with `respx` under `tests/unit/`; mark live tests `requires_robot`.
8. **Quality**: run `make lint` and `make test`. Both must pass.

## Patterns to copy

| Task | Copy from |
|------|-----------|
| JSON GET client | `clients/health.py`, `clients/instruments.py` |
| Binary POST (JPEG) | `clients/camera.py` |
| Read-only catalog | `clients/readonly.py` |
| Capability + summary | `capabilities/probe.py`, `capabilities/inspect.py`, `capabilities/robot_status.py` |
| Post-install health wait | `capabilities/wait_health.py` → `flex-test wait-health` |
| CRS-on OAuth for CLI | `orchestration/crs_auth.py` (`optional_access_token`) |
| CRS-on lockdown / matrix | `capabilities/crs_on_lockdown.py`, `capabilities/crs_on_matrix.py` |
| CRS-on settings / users | `capabilities/crs_auth_settings_suite.py`, `capabilities/user_management_suite.py` |
| Audit periods | `clients/audit.py` → `flex-test audit` |
| Mutating install | `capabilities/install.py` + `orchestration/gates.py` |
| LPC jog timing | `capabilities/lpc_jog_timing.py` + `fixtures/lpc_jog_space.py` |
| Release catalog | `releases/` |

## Checklist

```
- [ ] Client method(s) added; no ad-hoc HTTP elsewhere
- [ ] Capability descriptor + gates if user-facing operation
- [ ] CLI wired so agents never need curl for this path
- [ ] READONLY_ENDPOINTS updated for new GETs
- [ ] FlexRobot / CLI wired if operators need it
- [ ] Unit tests for client/capability
- [ ] make lint && make test pass
```

## Natural next surfaces (learned from Pyro testing)

Do **not** add ad-hoc SSH/curl from agents. When growing the harness for
Pyro / protocol-subprocess work (`docs/pyro-testing.md`), prefer:

| Gap | Suggested layering |
|-----|--------------------|
| Protocol upload / analyze / create-run / sign-off | typed clients → gated capabilities → `flex-test protocol …` |
| Pyro / nameserver status | read-only capability (+ optional SSH later), not raw shell |
| Run play / tip smoke | `PHYSICAL_MOTION` risk; only with explicit gates + operator request |
| LPC jog latency | `flex-test lpc-jog-timing --confirm-clear-deck` (high-Z box; never toward deck) |

`flex-test status` and `flex-test wait-health` already cover instruments/door/subsystems
and post-install `/health` polling.

[oe-core#373](https://github.com/Opentrons/oe-core/pull/373) grouped systemd
`PartOf=` restart closed RQA-5789 / RQA-5790 on `v10.0.0-alpha.3`. Prefer
documenting **full robot reboot** as operator recovery. Do not
paper over product issues by silently restarting services unless the user asks
for recovery.

## References

- Architecture: `docs/architecture.md`
- Safety: `docs/safety-model.md`
- CRS dual-mode: `docs/crs-testing.md`, `docs/crs-on-setup.md`
- Versions: `docs/robot-versions.md`
- Pyro / subprocess testing: `docs/pyro-testing.md`
