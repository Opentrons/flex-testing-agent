# Safety model

This harness operates against a physical Flex robot. Safety is enforced in code and policy.

## Hard rules (milestone 1)

1. **Explicit timeouts** on all HTTP calls (`ROBOT_REQUEST_TIMEOUT_SECONDS`, `ROBOT_HEALTH_TIMEOUT_SECONDS`).
2. **Exclusive robot lock** per host under `ARTIFACT_DIRECTORY/locks/`.
3. **Mutations disabled by default** (`ALLOW_MUTATIONS=false`).
4. **Dry-run blocks mutations** (`DRY_RUN=true`).
5. **Physical motion is gated** (`PHYSICAL_MOTION` requires `ALLOW_MUTATIONS=true`
   and an explicit operator request). Supported entrypoints:
   `flex-test seed-runs` and `flex-test lpc-jog-timing --confirm-clear-deck`
   ([known-state-and-latency.md](known-state-and-latency.md)).
   Do not invent ad-hoc motion URLs or ungated home/move CLI commands.
6. **No arbitrary shell / HTTP / URL construction** for agents.
7. **Credential redaction** in evidence writers.
8. **Access control enable** is gated: only via
   ``flex-test crs enable --confirm-one-way`` (one-way API; see below).

## Access control / CRS

**CRS** (Compliance Ready Software) maps to `accessControlEnabled`. It is 21 CFR
Part 11 *tooling* on the robot, not a claim that the Flex is itself certified.
Enabling via `PATCH /auth/settings/accessControlEnabled` accepts only `true`
and cannot be undone through the public API. The App/ODD modal says the same
(permanent). Treat enablement as `DISRUPTIVE`. Product model:
[crs-testing.md](crs-testing.md#what-crs-is-product-model).

Harness policy:

- Detect via GET on all paths
- **Enable only** via `ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way`
  (creates bootstrap admin `flex_harness_admin`, provisions fixture users)
- Prefer thorough testing with CRS **off** first ([crs-testing.md](crs-testing.md))
- Before enable, operators must accept lockout risk and know restore paths below

Live protocol on CRS-on: App/ODD **Pause** waits for a documentation note
before the run actually pauses. That is expected. Use the door (or E-Stop).
Do not file it as a bug.

HTTP 451 on a mutation means documentation (reason) was required and missing.
On App/ODD that is usually a frontend bug. Direct HTTP may still succeed
without `Opentrons-User-Notes` ([RQA-5841](https://opentrons.atlassian.net/browse/RQA-5841)).

### Restore paths when CRS is on

Order: product HTTPS for API, then lab SSH for shell, then FTDI serial.
[interaction-layers.md](interaction-layers.md).

1. **Remote-access carveout (QA, keeps CRS on):** first enable needs FTDI
   serial (`ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access`).
   After that, prefer `flex-test ssh`. Sentinel
   `/etc/opentrons-allow-remote-access`. Cleared on the next OS update.
   Details: [crs-testing.md](crs-testing.md).
2. **Full CRS exit (turn CRS off, preferred lab path):** as root over **SSH**
   (or FTDI if SSH is down), run `opentrons_disable_crs` and enter password
   `{robot_serial}-0000` (same as enter-CRS). Do not run this from a protocol
   subprocess. Details: [crs-testing.md](crs-testing.md#enter--exit-crs-operator-notes).
3. **Full CRS exit (fallback):** EXEC-2176 / assisted wipe when
   `opentrons_disable_crs` is unavailable or fails (not automated here).

Enter-CRS lab note: robots no longer auto-create `testadmin` / `testuser`;
create those users yourself during the enter-CRS flow if you need them
([crs-testing.md](crs-testing.md#enter--exit-crs-operator-notes)).

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
