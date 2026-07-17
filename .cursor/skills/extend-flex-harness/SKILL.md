---
name: extend-flex-harness
description: >-
  Extends the flex-testing-agent harness by adding typed robot API clients,
  capabilities, CLI commands, and read-only endpoint coverage. Use when adding
  Flex HTTP endpoints, new inspect/probe/install behavior, camera features,
  release tooling, or when the user asks to grow the harness instead of
  calling the robot ad hoc.
---

# Extend the Flex testing harness

## Goal

Grow `flex-testing-agent` through the existing layers. Do not bypass clients with one-off httpx/curl in capabilities or agent glue.

## Workflow

1. **Find the source of truth** in `upstream/opentrons` (robot-server / update-server / auth-server routers) or `docs/source-research.md`.
2. **Add or extend an atomic client** under `src/flex_testing_agent/clients/`.
   - Reuse `RobotHttpSession` (`get_json` / `post_json` / `get_bytes` / `post_bytes`).
   - Keep methods small and named after API paths.
   - Export from `clients/__init__.py` when it is part of the public client surface.
3. **Wire onto `FlexRobot`** (`robots/flex.py`) if operators should access it via the facade.
4. **For GET coverage**, add a `ReadonlyEndpoint` to `READONLY_ENDPOINTS` in `clients/readonly.py`.
   - Use `acceptable_status` for expected 403/404 (document in `notes`).
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
| JSON GET client | `clients/health.py` |
| Binary POST (JPEG) | `clients/camera.py` |
| Read-only catalog | `clients/readonly.py` |
| Capability + summary | `capabilities/probe.py`, `capabilities/inspect.py` |
| Mutating install | `capabilities/install.py` + `orchestration/gates.py` |
| Release catalog | `releases/` |

## Checklist

```
- [ ] Client method(s) added; no ad-hoc HTTP elsewhere
- [ ] Capability descriptor + gates if user-facing operation
- [ ] READONLY_ENDPOINTS updated for new GETs
- [ ] FlexRobot / CLI wired if operators need it
- [ ] Unit tests for client/capability
- [ ] make lint && make test pass
```

## References

- Architecture: `docs/architecture.md`
- Safety: `docs/safety-model.md`
- Versions: `docs/robot-versions.md`
