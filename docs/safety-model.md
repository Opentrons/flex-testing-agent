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

Future CRS-on testing requires a documented restore path (for example serial /
lab wipe per EXEC-2176) before any enable capability is considered.

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
