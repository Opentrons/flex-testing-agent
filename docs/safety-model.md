# Safety model

This harness operates against a physical Flex robot. Safety is enforced in code and policy.

## Hard rules (milestone 1)

1. **Explicit timeouts** on all HTTP calls (`ROBOT_REQUEST_TIMEOUT_SECONDS`, `ROBOT_HEALTH_TIMEOUT_SECONDS`).
2. **Exclusive robot lock** per host under `ARTIFACT_DIRECTORY/locks/`.
3. **Mutations disabled by default** (`ALLOW_MUTATIONS=false`).
4. **Dry-run blocks mutations** (`DRY_RUN=true`).
5. **Physical motion is gated** (`PHYSICAL_MOTION` requires `ALLOW_MUTATIONS=true`
   and an explicit operator request). The supported entrypoint is
   `flex-test seed-runs` ([known-state-and-latency.md](known-state-and-latency.md)).
   Do not invent ad-hoc motion URLs or ungated home/move CLI commands.
6. **No arbitrary shell / HTTP / URL construction** for agents.
7. **Credential redaction** in evidence writers.
8. **Access control must not be enabled** by this harness.

## Access control / CRS

**CRS** (Compliance Ready Software) maps to `accessControlEnabled`. Enabling via
`PATCH /auth/settings/accessControlEnabled` accepts only `true` and cannot be
undone through the public API. Treat enablement as `DISRUPTIVE`.

Harness policy:

- Detect via GET only
- Capability `enable_access_control` is unimplemented and blocked
- Prefer thorough testing with CRS **off** first ([crs-testing.md](crs-testing.md))
- Do **not** enable CRS from the harness until operators accept lockout risk and
  know both restore paths below

### Restore paths when CRS is on

1. **Remote-access carveout (QA, keeps CRS on):** FTDI serial remount + touch
   `/etc/opentrons-allow-remote-access` + restart `opentrons-remote-access-allowed`
   so SSH / Jupyter / devtools work again. Harness:
   `ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access`.
   Cleared on the next OS update. Details: [crs-testing.md](crs-testing.md).
2. **Full CRS exit (turn CRS off):** EXEC-2176 / assisted wipe (not automated here).

On edge / 10.0 alphas with remote-access disable: CRS off leaves SSH/Jupyter
alone; CRS on disables them unless the allow file exists (auth-server check fails
closed).

## Risk levels

```text
READ_ONLY
REVERSIBLE_MUTATION
DISRUPTIVE
INSTALLATION
DESTRUCTIVE
PHYSICAL_MOTION
```

First agent-accessible surface should be `READ_ONLY` plus carefully controlled reversible operations only.

## Cancellation and retries

Milestone 1 uses httpx timeouts and fails clearly. Maximum retry policy for mutating install/mode flows will be added with those capabilities. Safe cancellation for long install sessions is deferred.

## Audit

Every inspect run persists:

- Test run + phases
- Capability execution
- State snapshot
- Evidence artifact paths

Agent session / tool invocation / token usage tables exist as placeholders for future audited agent runs.
