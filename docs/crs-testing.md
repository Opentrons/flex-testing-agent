# CRS (Compliance Ready Software) testing

CRS is the product name for what the robot API still calls **access control**
(`accessControlEnabled`). Formerly ACM / RCS in some docs.

Primary product docs:

- [Approved PRD - Compliance Readiness Software V2](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5339512880)
- [Access Control Mode Overview (PER)](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5433393193)
- [QA Test Checklist for RCS (formerly ACM)](https://opentrons.atlassian.net/wiki/spaces/~712020ac583a1878a5430aaf1db6793f399ca1/pages/6195970453)
- Exit / restore: [EXEC-2176](https://opentrons.atlassian.net/browse/EXEC-2176) (serial / assisted wipe)

This harness treats CRS as a **dual-mode** problem:

1. **CRS off** (default for KansasFLEX lab work): unauthenticated HTTP works; build a
   complete endpoint exercise suite here first.
2. **CRS on** (later): same catalog, plus OAuth login, roles/scopes, and expected
   401/403 matrix. Enablement stays **blocked** in the harness until a restore path
   is documented and rehearsed.

## Goal

When CRS is off, the client catalog and suite can exercise **every** Flex HTTP
endpoint the monorepo exposes (robot-server, auth-server, update-server,
system-server, audit-server), with risk gates. When CRS is on later, the same
catalog drives an authorization matrix without inventing ad-hoc URLs.

## Architecture

```text
docs/crs-testing.md          design SSOT
catalog/endpoints.py         method × path inventory + risk + scopes
clients/*                    typed HTTP wrappers (reuse RobotHttpSession)
capabilities/probe.py        CRS-off Tier A (parameter-free GETs)
capabilities/crs_off.py      CRS-off Tier B / Tier C
flex-test probe|crs-off-b|crs-off-c|inspect
```

### Endpoint catalog

`src/flex_testing_agent/catalog/endpoints.py` is the inventory:

| Field | Purpose |
|-------|---------|
| `method` / `path` / `service` | Identity |
| `group` | Summary bucketing |
| `risk_level` | Gate for live calls |
| `required_scopes` | CRS-on expectations (from `require_scopes`) |
| `parameterized` | Needs fixture IDs before live call |
| `blocked` | Never call (`PATCH .../accessControlEnabled`) |
| `crs_off_acceptable_status` | Soft failures when probing CRS-off |

Regenerate from a local monorepo clone:

```bash
uv run python scripts/generate_endpoint_catalog.py
```

Approximate surface (regenerate to refresh counts): ~180 unique routes,
~50 parameter-free GETs for the unauthenticated CRS-off probe.

### Layering for clients

Prefer domain clients over a single mega-client:

| Domain | Client | Notes |
|--------|--------|-------|
| Health / update health | exists | |
| Auth settings detect | exists | GET only; never enable |
| Camera | exists | |
| Modules | exists | |
| Readonly / probe | exists | Driven by catalog GETs |
| Protocols / runs / data files | exists | Tier B fixtures + upload |
| Client data / robot lights | exists | Tier C reversible mutations |
| OAuth token | next (CRS-on) | `POST /oauth2/token` |
| Users | next (CRS-on) | `/auth/users/*` |
| Audit | next | `/audit/*` |

## Run state matrix (required preflight)

Protocol-run **presence** changes HTTP behavior (camera, some run GETs, Pyro
`ot-protocol` process). Suites must **declare**, **verify**, and optionally
**ensure** run state before exercising endpoints. Do not assume leftover robot
state from a prior session.

| Desired state | Meaning | Why it matters |
|---------------|---------|----------------|
| `no-current` | No run with `current=true` | Baseline GETs; `POST /camera/picture` and preview succeed ([RQA-5807](https://opentrons.atlassian.net/browse/RQA-5807) clarity when current) |
| `current-idle` | One current run, `status=idle` (created, not played) | Parameterized `/runs/{id}/…` GETs; preview correctly returns 422 “run is active” |
| `any` | Snapshot only | Inspect / operator debug |

Orchestration: `orchestration/run_state.py` (`snapshot_run_state`,
`ensure_run_state`). CLI:

```bash
uv run flex-test run-state
ALLOW_MUTATIONS=true uv run flex-test run-state --ensure no-current
ALLOW_MUTATIONS=true uv run flex-test run-state --ensure current-idle
```

Suite commands accept `--run-state` and `--ensure-run-state` (mutations gated).
Without `--ensure-run-state`, a mismatch fails fast with the observed state.

| Suite / group | Default desired state | Ensure behavior |
|---------------|----------------------|-----------------|
| Tier A `probe` (+ camera picture) | `no-current` | Off unless `--ensure-run-state` |
| Tier B `crs-off-b` | `current-idle` | On with `--create-fixtures` or `--ensure-run-state` |
| Tier C `crs-off-c` | `no-current` | On by default (`--no-ensure-run-state` to skip) |

Future groups (same machinery): `current-running` / post-play `succeeded` only
with explicit operator request (physical motion / play gates).

## CRS-off suite tiers

Run only against a robot with `accessControlEnabled: false` (confirm via
`flex-test inspect`). Confirm run presence via `flex-test run-state` or the
suite preflight.

| Tier | What | Gate / CLI | Default run state |
|------|------|------------|-------------------|
| **A** | All parameter-free GETs (+ known soft statuses) | `flex-test probe` | `no-current` |
| **B** | Parameterized GETs using protocol/run/data-file/subsystem/log/clientData fixtures | `flex-test crs-off-b` (`--create-fixtures` needs `ALLOW_MUTATIONS`) | `current-idle` |
| **C** | Reversible mutations (lights, clientData, camera, errorRecovery, labwareOffsets, throwaway protocol/run delete) | `ALLOW_MUTATIONS`; `flex-test crs-off-c` | `no-current` |
| **A+B+C** | Full CRS-off API pass with timing JSON | `ALLOW_MUTATIONS`; `flex-test api-suite` | A/C `no-current`, B `current-idle` |
| **D** | Disruptive / install / destructive | Explicit capability + mutations | declare per capability |
| **E** | Physical motion (home, move, run play) | Explicit operator request only | declare per scenario |
| **Blocked** | `PATCH /auth/settings/accessControlEnabled` | Always refused | n/a |

Tier B uses existing robot resources when present (after `seed-runs`, history
usually supplies commands + annotations). Pass `--create-fixtures` to upload
`docs/test-suggestions/protocols/pyro_smoke_no_motion.py`, a tiny CSV,
clientData key, a short maintenance-run command fixture, and ensure a
**current idle** run when fixtures / run state are missing.

Path-param sources:

| Token | Source |
|-------|--------|
| `{runId}` (most run GETs) | Current-idle suite run |
| `{runId}` + `{commandId}` under `/runs/…/commands/…` | Historical seeded run that has commands (`command_run_id`) |
| `{commandId}` under `/commands/…` | Simple command store (`GET /commands`) |
| `{commandAnnotationId}` | Seeded `simple_home_move` (`group_steps`, apiLevel 2.29) |
| `{key}`, `{log_identifier}`, `{subsystem}`, update `{id}`, `{pipette_id}`, `{username}` | Robot inventory / clientData put |
| maintenance `{runId}` / `{commandId}` | Current maintenance run, or throwaway create+`waitForDuration(0)` |
| `{calibrationId}`, update `{session}` | Placeholders (Flex removed labware calibrations; no install session) → soft 404/410 |

`GET /runs/{runId}/commandsAsPreSerializedList` returns **503**
`PreSerializedCommandsNotAvailable` while the run is still current/active
(robot-server: only after a run has ended). Tier B resolves this path against an
**ended** run id (historical non-current run, or uncurrent+recreate when
creating fixtures). Brief store-settle retries only; do not soft-accept 503.

Live CRS-off A+B+C on KansasFLEX (`v9.1.2-alpha.6`): Tier A 51/0, Tier B 35/0
(skipped=0), Tier C 7/0 via `flex-test api-suite`.

## CRS-on suite (deferred)

Prerequisites:

1. Documented restore for **disabling** CRS (lab wipe per EXEC-2176 / service
   procedure). The public API cannot turn CRS off.
2. Documented **remote-access carveout** (below) so QA can still use SSH /
   Jupyter / devtools while CRS stays on.
3. Dedicated robot or accepted lockout risk (not casually KansasFLEX).
4. OAuth client + role fixtures (Admin / User / Auditor / Service).

Then for each catalog entry:

- unauthenticated → expect 401/403 (except truly public routes)
- token without required scope → 403
- token with required scope → success (or resource-specific 404)

Still never implement a harness “enable CRS” happy path without restore.

## CRS-on remote-access carveout (QA)

Applies to robot builds on **edge** and **10.0 alphas** after the remote-access
disable merge (product behavior; confirm on the build under test).

| CRS state | Jupyter / SSH / devtools |
|-----------|--------------------------|
| Off | Unimpeded |
| On | Disabled unless the allow sentinel exists |

**Sentinel (read-only root FS):** `/etc/opentrons-allow-remote-access`  
**Unit:** `opentrons-remote-access-allowed`

Why this is a safe lab carveout:

1. File lives on the read-only root filesystem; automation does not create it.
2. Cleared / overridden on the next robot system update (must redo after `put`).
3. Root-owned; protocol code cannot alter it.
4. Remounting root RW is an explicit root hoop (serial console).
5. Starts disabled; first enable needs serial (SSH is already locked out).

Auth-server gate: “is CRS on?” is answered by the auth server. If auth does not
respond correctly, remote access **fails closed** (no SSH/Jupyter). Jupyter/SSH
may also come up a bit later after boot while that check runs.

### Manual (serial / Tabby)

After FTDI login as `root` ([serial-console.md](serial-console.md),
[Confluence FTDI guide](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex)):

```bash
mount -o remount,rw /
touch /etc/opentrons-allow-remote-access
systemctl restart opentrons-remote-access-allowed
```

One line:

```bash
mount -o remount,rw /; touch /etc/opentrons-allow-remote-access ; systemctl restart opentrons-remote-access-allowed
```

This restores SSH, Jupyter, and devtools. It does **not** turn CRS off. Redo
after every robot OS update.

### Harness CLI

```bash
# Close Tabby first (exclusive serial port)
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

`allow-remote-access` is `DISRUPTIVE` (remounts `/` RW) and requires
`ALLOW_MUTATIONS=true`. Prefer HTTP when network + CRS-off still work.

### Not the same as EXEC-2176

| Goal | Path |
|------|------|
| Keep CRS on, restore lab SSH/Jupyter/devtools | Serial allow-file carveout (this section) |
| Turn CRS **off** again | EXEC-2176 / assisted wipe (not this harness) |

## Safety

Unchanged from [safety-model.md](safety-model.md):

- Mutations default off
- Never enable CRS via API from this harness
- No first-class physical-motion CLI; live play only on explicit request
- Timeouts on all HTTP; redact secrets in evidence
- Re-check `ROBOT_HOST` (DHCP)

## Workstreams

1. **Catalog + Tier A**: done (`flex-test probe`).
2. **Domain clients + Tier B/C + api-suite**: done (`protocols` / `runs` /
   `data_files` / `client_data` / `robot_control` / `camera` /
   `error_recovery` / `labware_offsets` / `maintenance_runs`;
   `flex-test crs-off-b|crs-off-c|api-suite`).
3. **Run-state preflight**: done for Tier A/B/C (`flex-test run-state`,
   `--run-state` / `--ensure-run-state`). Expand matrix for played / succeeded
   groups when Tier E scenarios land.
4. **CRS-off Tier C expansion**: more of the ~57 reversible catalog mutations
   beyond the current 7 cleanup steps.
5. **CRS-off Tier D expansion**: more disruptive catalog coverage beyond install.
6. **OAuth + users clients**: prepare dual-mode session (no enable).
7. **CRS-on authorization matrix**: after remote-access carveout + EXEC-2176
   restore story; map to QA checklist sections (login, roles, settings, logs).
8. **Published test suggestions**: YAML under `docs/test-suggestions/` for operator runs.

## Related harness docs

- [architecture.md](architecture.md) (dual-mode AC note)
- [safety-model.md](safety-model.md)
- [robot-logs.md](robot-logs.md) (audit vs diagnostic vs protocol run logs)
- [serial-console.md](serial-console.md) (FTDI; used for allow-remote-access)
- [source-research.md](source-research.md)
- [development-plan.md](development-plan.md)
- [pyro-testing.md](pyro-testing.md) (orthogonal; robot may be unhealthy while this lands)
