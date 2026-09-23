# CRS (Compliance Ready Software) testing

CRS is the product name for what the robot API still calls **access control**
(`accessControlEnabled`). Formerly ACM / RCS in some docs.

Primary product docs:

- [Approved PRD - Compliance Readiness Software V2](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5339512880)
- [Access Control Mode Overview (PER)](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5433393193)
- [QA Test Checklist for RCS (formerly ACM)](https://opentrons.atlassian.net/wiki/spaces/~712020ac583a1878a5430aaf1db6793f399ca1/pages/6195970453)
- Exit / restore: root `opentrons_disable_crs` (password `{serial}-0000`; see
  [Enter / exit CRS](#enter--exit-crs-operator-notes)), or
  [EXEC-2176](https://opentrons.atlassian.net/browse/EXEC-2176) wipe as fallback
- Harness Confluence mirror: [Flex testing harness: CRS endpoint matrix (RBARM)](https://opentrons.atlassian.net/wiki/spaces/RBARM/pages/6382649592)

This harness treats CRS as a **dual-mode** problem:

1. **CRS off** (default for KansasFLEX lab work): unauthenticated HTTP works; run
   `flex-test probe|crs-off-b|crs-off-c|api-suite`.
2. **CRS on**: HTTPS only (the harness will not use plaintext `:31950`), same
   catalog, plus OAuth, roles/scopes, 401/403 matrix, settings, user CRUD, and
   audit download. Enablement is **gated** (not casual): only
   `ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way`. Catalog
   probes never call `PATCH /auth/settings/accessControlEnabled`.

## What CRS is (product model)

CRS is a **mode**, not a certification. It exists so a customer lab can run
**21 CFR Part 11** style workflows on a Flex. A Flex with CRS on is **not**
itself 21 CFR Part 11 compliant; it supplies the tools (identity, signed audit
trail, HTTPS) for the *lab* to operate in a compliant way.

Product rules that follow from that:

- **Mutating HTTP** (`POST` / `PUT` / `PATCH` / `DELETE`) requires
  identification, is written to the audit trail, and is cryptographically
  signed. Reads (`GET`) stay open. Exception: `/clientData` is App/ODD
  in-memory coordination, not protocols/runs/users/audit, and is **not**
  under CRS. Unauthenticated PUT/DELETE returning 200 is expected
  ([RQA-5918](https://opentrons.atlassian.net/browse/RQA-5918) closed,
  no action required).
- **HTTPS for credentials**: QA checklist §9. With CRS on, clients must not
  send credentials (or any robot API) over plaintext HTTP. The harness
  enforces HTTPS. If `:31950` still serves `/health` or `/auth/oauth2/token`,
  lockdown fails `plaintext_http_*` (product gap on alpha.4 KansasFLEX;
  [RQA-5981](https://opentrons.atlassian.net/browse/RQA-5981) Closed Won't Do).
- The compliance **user** is the authenticated workflow identity (OAuth account
  / logged-in session), not whoever is standing at the robot. Login plus a
  reason-for-interaction on every mutating action is intentional; App/ODD UX is
  supposed to feel heavy.
- You **enter** CRS with a service PIN (`{robot_serial}-0000` on current
  builds) and **cannot exit through the public API**. The App/ODD enable modal
  says this is permanent. Lab restore is root `opentrons_disable_crs` or
  EXEC-2176 wipe.
- Secure, durable logs force low-level stack changes: protocol subprocess
  isolation ([pyro-testing.md](pyro-testing.md)), `key-server` / CAAM for TLS
  and log signing, SSH/Jupyter off, and **no auto-delete** of CRS records.

App/ODD shows a **Compliance Ready** badge on a CRS-on robot. Enable UI lives
under Robot Settings → Advanced → “Enable Compliance Ready Software” (red
warning that activation cannot be undone; service PIN field).

### How a mutating request actually flows

```text
Frontend
   │  POST /auth/oauth2/token  {username, password}
   ▼
auth-server  →  {accessToken}
   │
   │  POST /protocols  (or any mutation)  Authorization: Bearer …
   ▼
robot-server / system-server / update-server
   │  POST /auth/oauth2/introspect
   ▼
auth-server  →  {valid, user, scopes}
   │
   │  async audit event  ("protocol uploaded by Max", …)
   ▼
audit-server
```

`key-server` sits beside this path. It uses hardware CAAM and
`/var/lib/opentrons-key-server/ot-secure-volume` for **log signing** and
**TLS certs**. The ODD **Robot Encryption Key** (typed into the App when
trusting HTTPS) is a rotating symmetric key that proves the robot CA was not
swapped in transit. That is a different secret from the CRS service PIN.

Hubs: `auth-server` and `audit-server` talk to `robot-server`, `system-server`,
and `update-server`. Frontend talks to that cluster over HTTP(S).

### Protocol subprocess (why Pyro exists)

The stack used to run as one process under `opentrons-robot-server`. CRS needs
protocol execution **independent** of the HTTP server, so the default OS line
splits into:

| Process | Role | Privilege |
|---------|------|-----------|
| `opentrons-robot-server` | HTTP API, run setup, general interaction | root |
| `opentrons-hardware-api` | Pipettes, modules, door, motion interface | root |
| `ot-protocol` executor | Orchestrator + protocol engine for a run | `ot-protocol` user (limited) |

IPC is **Pyro5** (Python Remote Objects): each service exposes a
`PyroSynchronousObject`; callers use an `AsyncClientPyroObject` proxy.
Serialization is explicit for anything that is not a base Python type. See
[pyro-testing.md](pyro-testing.md).

Do not run `opentrons_disable_crs` (or remount `/`) from a protocol
subprocess. The `ot-protocol` user cannot, and product treats that as the
wrong place even for root.

### File Manager and retention

CRS robots **cannot auto-delete** protocol run records / audit periods to free
disk. Product File Manager (Desktop App and ODD Settings → “Download and
delete robot files”) is the operator surface for:

| Tab | What |
|-----|------|
| Audit Logs | Signed periods (protocol name, period start, period end) |
| Diagnostic Files | Support / service dumps |
| Protocol Run Records | Run JSON used by App/ODD UI |

Flows include per-row menus, **Download all** / **Delete all**, and on ODD a
USB picker (“Which USB device do you want to download all log periods to?”).
Storage warnings are expected as the disk fills. This harness covers HTTP
list/download of audit periods (`flex-test audit`) and diagnostic archives
(`flex-test logs archive`). File Manager UI and USB export are App/ODD (out of
scope here). Do not assume KansasFLEX CRS-on disks self-clean after suites.

### Documentation required (reason for interaction)

Product intent: every mutating robot action (every `POST`, and by the same
rule `PUT`/`PATCH`/`DELETE`) shows a **Documentation Required** modal before
the request is sent.

App/ODD shape:

- Note field labeled for the logged-in account (example: “Note for robot audit
  log by testadmin”)
- **Action list** in human language (“Toggling lights”, “Moving 0.1 mm along
  z axis”), not raw commandType
- Confirm stays disabled until a note is entered; **Cancel action** (or closing
  the modal) must restore the exact prior UI state with **no visible error**
- Login is always required for those actions

**Maintenance / LPC / jog** is a UX compromise: prompt at the **start**,
accumulate actions (`Launching labware position check`, load labware, relative
moves), then prompt again at the **end** instead of interrupting every jog.

**HTTP 451** `Unavailable for Legal Reasons` means a mutation expected
documentation and did not get it. On App/ODD that usually means the call
skipped `useDocumentedMutation` (frontend bug). Direct robot HTTP currently
may still succeed without `Opentrons-User-Notes` ([RQA-5841](https://opentrons.atlassian.net/browse/RQA-5841)).
The harness **sends** that header on CRS-on mutations (`ROBOT_USER_NOTES`) but
does **not** treat missing-header success as a suite pass for documentation
enforcement.

**Pause is not a bug.** In CRS mode, App/ODD Pause prompts for documentation
and does **not** pause until the modal is submitted. Open the **door** to
pause, or **E-Stop** in an emergency. Do not file this as an RQA bug.

**Protocol analysis does not require documentation or login** ([RQA-6012](https://opentrons.atlassian.net/browse/RQA-6012)).
Upload-time analysis and `POST /protocols/{protocolId}/analyses` (reanalysis)
are simulation-only. They bypass CRS auth and documentation-required flows
even when `requireReasonForInteraction` is true. App/ODD must not show the
documentation modal for analyze/reanalyze. Verify with
`uv run python scripts/retest_rqa6012.py` when CRS is on.

Human-readable action text comes from `useCommandTextString` (every
`RunTimeCommand` needs an explicit case, present gerund, no default). New
commands without a case break the Documentation Required list. That is
frontend/monorepo work, not this harness.

## Goal

When CRS is off, the client catalog and suite can exercise **every** Flex HTTP
endpoint the monorepo exposes (robot-server, auth-server, update-server,
system-server, audit-server, key-server), with risk gates. When CRS is on, the
same catalog drives an authorization matrix without inventing ad-hoc URLs.

**Product contract under test (API):** CRS gates **mutations**
(POST/PATCH/PUT/DELETE): login (bearer) plus audit. **GET** routes stay
reachable with or without a token (except auth-server user lookups that need
`users.read*`). That matches current robot-server / audit-server behavior on
10.0.0-alpha.1 ([RQA-5852](https://opentrons.atlassian.net/browse/RQA-5852),
[RQA-5850](https://opentrons.atlassian.net/browse/RQA-5850)) and the
robot-server rule of thumb (GET: no login / no reason; mutations: both). The
PRD phrase "login required for any action" is interpreted here as **mutating
actions**, not reads. If product later gates GETs, update lockdown/auth-matrix
expectations.

Some mutations need **different scopes depending on the body** (example:
`PATCH /runs/{runId}` for sign-off vs other fields). Auth-matrix and
settings-suite S9 must not assume one scope for every body.

### Testing implications (operators and agents)

| Product behavior | What to do in this lab |
|------------------|------------------------|
| CRS is 21 CFR *tooling*, not Flex certification | Do not treat “KansasFLEX is Part 11 compliant” as a pass/fail |
| Mutations need identity + audit; GETs stay open | `crs lockdown` / `auth-matrix` / `crs suite`; do not expect 401 on GETs |
| Enable is one-way in the UI | Only `flex-test crs enable --confirm-one-way`; know disable/wipe first |
| SSH/Jupyter off when CRS on | Serial carveout once, then SSH; does not turn CRS off |
| Protocol runs in `ot-protocol` (not root) | Pyro suite on CRS-off preferred; sign-off 409 is CRS, not IPC |
| No auto-delete of CRS records | Disk grows; File Manager is product UI; DELETE run-record still a harness gap |
| Documentation Required on App/ODD POSTs | Out of scope for HTTP suites; send `Opentrons-User-Notes` anyway |
| HTTP may omit reason and still succeed | Comment on [RQA-5841](https://opentrons.atlassian.net/browse/RQA-5841); do not file dupes |
| HTTP 451 on a mutation | Likely missing documentation on a path that *does* enforce it; investigate |
| Protocol analysis / reanalysis | No auth or documentation required ([RQA-6012](https://opentrons.atlassian.net/browse/RQA-6012)); `scripts/retest_rqa6012.py` |
| Pause waits for a note | Expected; door or E-Stop. Do not file as a bug |
| Cancel documentation modal | Must leave no error toast / no partial mutation |
| Audit periods rotate on boot and protocol end | After `probe-c` / a signed-off run, `flex-test audit list` should show periods |
| Desktop may require downloading the current period after a run | Product UX; harness can download any period id at any time |
| Body-dependent scopes | Spot-check `PATCH /runs/{id}` signedBy vs other patches |

## Architecture

```text
docs/interaction-layers.md   HTTPS vs SSH vs serial (operator/agent ladder)
docs/crs-testing.md          design SSOT (this file: product model + suites)
docs/crs-on-setup.md         CRS-on bootstrap (HTTPS, users, CLI)
docs/robot-logs.md           audit vs diagnostic vs protocol run logs
docs/pyro-testing.md         subprocess / Pyro (CRS isolation)
catalog/endpoints.py         method × path inventory + risk + scopes
clients/*                    typed HTTP wrappers (reuse RobotHttpSession)
capabilities/probe.py        CRS-off Tier A (parameter-free GETs)
capabilities/crs_off.py      CRS-off Tier B / Tier C
capabilities/crs_on_*.py     CRS-on lockdown, matrix, probe A/B/C, suite
flex-test probe|crs-off-b|crs-off-c|api-suite
flex-test crs …              CRS-on setup and suites
flex-test audit list|download
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
| `blocked` | Catalog probes never call (`PATCH .../accessControlEnabled`); enable only via `flex-test crs enable --confirm-one-way` |
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
| Auth settings | exists | GET detect + GET/PATCH/DELETE `/auth/settings`; enable only via gated CLI |
| Camera | exists | |
| Modules | exists | |
| Readonly / probe | exists | Driven by catalog GETs |
| Protocols / runs / data files | exists | Tier B fixtures + upload |
| Client data / robot lights | exists | Tier C reversible mutations |
| OAuth token | exists | `POST /auth/oauth2/token` + introspect (`clients/oauth.py`) |
| Users | exists | `/auth/users/*` (`clients/users.py`) |
| Audit | exists | `GET /audit/external/logPeriods[/{id}/download]` (`flex-test audit`) |
| Key / HTTPS CA | exists | `flex-test crs trust-ca` (Robot Encryption Key, not service PIN) |

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
| **Blocked in catalog probes** | `PATCH /auth/settings/accessControlEnabled` | Enable only via `flex-test crs enable --confirm-one-way` | n/a |

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

## Enter / exit CRS (operator notes)

The catalog still **never** probes
`PATCH /auth/settings/accessControlEnabled`. Operators enable CRS only via
`ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way` (or the
ODD / App product flow). Confirm behavior on the build under test; product may
still evolve.

### Service password (enter and disable CRS)

On **newer internal builds** (confirm on the robot under test), the password
used to **enter** CRS (App/ODD “Enter service PIN”) and to run
**`opentrons_disable_crs`** is the robot **serial number** with `-0000`
appended.

Example: if `GET /health` reports `robot_serial` `FLXA2020241021003`, the CRS
service PIN is `FLXA2020241021003-0000`.

This is **not** the same secret as the **Robot Encryption Key** used for HTTPS
CA trust (see [crs-on-setup.md](crs-on-setup.md)). On `ot3@4.0.0-alpha.12`
(KansasFLEX, verified 2026-08-07), `{serial}-0000` does **not** decrypt
`GET /keys/external/ca/encryptedCerts`.

Find the serial from inspect / health, the robot label, or ODD settings (not
from `ROBOT_NAME`).

### Create `testadmin` / `testuser` yourself

Robots that enter CRS **no longer auto-create** the legacy lab users
`testadmin` and `testuser`. Create them yourself as part of the enter-CRS /
onboarding flow if you still need those accounts (Postman, older QA scripts,
role matrix fixtures).

Typical lab credentials (when you create the users yourself):

| Username | Password (common lab convention) |
|----------|----------------------------------|
| `testadmin` | `testadminpassword` |
| `testuser` | `testuserpassword` |

Do not assume those users exist after enablement. Older docs (for example
[Postman setup](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/3814424622))
may still name them; treat creation as a required enter-CRS step now.

### Disable CRS from a root shell (`opentrons_disable_crs`)

On current builds you can turn CRS **off** from a **root** shell without a full
EXEC-2176 wipe:

```bash
opentrons_disable_crs
```

Requirements:

- Run as **root** over **SSH** (preferred when the QA carveout is on) or
  **FTDI serial** ([serial-console.md](serial-console.md);
  [interaction-layers.md](interaction-layers.md))
- Enter the same service password as enter-CRS: `{robot_serial}-0000`
- Do **not** invoke this as a protocol subprocess / in-protocol shell call; use
  an interactive (or scripted) root shell only

This is the preferred lab exit when available. Keep EXEC-2176 / assisted wipe as
the fallback when the binary is missing, the password path fails, or product
docs still require wipe.

Harness policy: do not wrap `opentrons_disable_crs` as a first-class mutation
capability. Document the manual path here. Enable stays gated behind
`--confirm-one-way`.

## CRS-on suite (implemented)

Prerequisites:

1. Documented restore for **disabling** CRS:
   `opentrons_disable_crs` from root SSH/serial (above), or lab wipe per
   EXEC-2176 / service procedure when that path is unavailable. The public HTTP
   API still cannot turn CRS off.
2. Documented **remote-access carveout** (below) so QA can still use SSH /
   Jupyter / devtools while CRS stays on.
3. Dedicated robot or accepted lockout risk (not casually KansasFLEX).
4. OAuth client + role fixtures (Admin / User / Auditor / Service) via
   `flex-test crs provision-users` (or manually created `testadmin` / `testuser`).

Catalog expectations when CRS is on:

- unauthenticated **GET** → expect success (CRS does not gate reads)
- unauthenticated **POST/PATCH/PUT/DELETE** → expect 401/403 (except public routes)
- token without required scope on **mutations** → 403
- token with required scope on mutations → success (or resource-specific 404)

Public routes: `GET /health`, `GET /server/update/health`,
`GET /auth/settings/accessControlEnabled`, `POST /auth/oauth2/token`,
and all `/clientData` verbs (not under CRS; see product rules above).

### OAuth sessions (harness vs App)

- **Access tokens** from `POST /auth/oauth2/token` (`grant_type=password`) have a
  fixed lifetime (`expires_in`). Authenticated API calls **do not** extend that
  lifetime or reset idle logout.
- **`idleLogout`** (seconds in API; minutes in App UI) invalidates a token after
  the client stops using it for that period. Inactivity means no new access token
  from a refresh flow, not “no HTTP requests.”
- **Opentrons App** keeps users signed in by exchanging **refresh tokens** for
  new access tokens. That behavior is App/ODD only; this harness does not
  implement refresh-token grants.
- **`flex-test crs enable`** PATCHes a high `idleLogout` (999 minutes) so long
  API suites are less likely to hit idle invalidation mid-run. When a token
  expires, capabilities re-authenticate via ROPC.

| Command | What it proves |
|---------|----------------|
| `flex-test crs lockdown` | Negative auth (no/bad/under-scoped credentials); DISRUPTIVE+ excluded |
| `flex-test crs auth-matrix` | Scoped GET allow/deny with valid role tokens |
| `flex-test crs probe` | Tier A authenticated GETs + user-management API |
| `flex-test crs probe-b` | Parameterized GETs with OAuth |
| `flex-test crs probe-c` | Reversible mutations with OAuth + `Opentrons-User-Notes` |
| `flex-test crs suite [--include-lockdown]` | Combined matrix + A+B+C (optional L1 lockdown) |
| `flex-test crs users-api` | Auth-server CRUD, role change, non-admin 403, password reset |
| `flex-test crs settings-suite` | QA checklist §8 tunables (S0–S12) |
| `flex-test crs idle-logout-inactivity` | Token inactive after idle wait (no API traffic) |
| `flex-test audit list\|download` | Audit log periods |

Bootstrap: [crs-on-setup.md](crs-on-setup.md). Published plans:
[crs-on-api-suite.yaml](test-suggestions/crs-on-api-suite.yaml),
[crs-on-lockdown-negative-auth.yaml](test-suggestions/crs-on-lockdown-negative-auth.yaml).

Enable only via `flex-test crs enable --confirm-one-way` after restore is rehearsed.

## PRD / QA checklist coverage (API)

Product SSOT: [Approved PRD - CRS V2](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5339512880).
QA checklist: [QA Test Checklist for RCS](https://opentrons.atlassian.net/wiki/spaces/~712020ac583a1878a5430aaf1db6793f399ca1/pages/6195970453).
This table is **HTTP / serial harness** coverage only. ODD and Desktop App UI
stay on Sara's checklist.

| QA / PRD | Harness proof | Status |
|----------|---------------|--------|
| Dual-mode: CRS off unauthenticated HTTP | `flex-test api-suite` / [crs-off-api-suite.yaml](test-suggestions/crs-off-api-suite.yaml) | Covered |
| Dual-mode: CRS on mutations gated, GETs open | `crs lockdown` + `crs auth-matrix` + `crs suite` / [crs-on-api-suite.yaml](test-suggestions/crs-on-api-suite.yaml) | Covered |
| §1 Activation | `flex-test crs enable --confirm-one-way` (gated) | Covered (one-way) |
| §1 Deactivation restores unauthenticated HTTP | Manual `opentrons_disable_crs`; then `flex-test api-suite` | Operator; not a capability |
| §2 Robot Encryption Key / HTTPS CA | `flex-test crs trust-ca` | Partial (rotation UX is ODD) |
| §3 Login success / fail | ROPC in OAuth client; `lockdown --actors bad_oauth`; [crs-user-management-onboarding.yaml](test-suggestions/crs-user-management-onboarding.yaml) U7 | API covered; modal is App/ODD |
| §4 Logout / revoke token | No `/auth/oauth2/logout` in catalog | Gap (App/ODD + idleLogout S6) |
| §5 Inactivity timeout | `crs settings-suite` S6 (`--include-slow`); `crs idle-logout-inactivity` | Covered (slow / standalone) |
| §6 User CRUD, role, rename, reset, delete | `flex-test crs users-api` | Covered |
| §6 Non-admin 403 on user mutations | `users-api` operator_patch/delete_forbidden | Covered |
| §6 Duplicate username | `users-api` post_duplicate_username_rejected | Covered |
| §6 Deactivate / reactivate | `settings-suite` S1 (lock via failed logins; PATCH `locked=false`) | Covered via S1 |
| §7 Temp password one-use / original rejected | `users-api` original_password_rejected + temp_password_rejected | Covered |
| §7 First-login prompt without password | App/ODD | Out of scope |
| §8 Settings tunables | `crs settings-suite` S0–S12 / [crs-auth-settings-behavior.yaml](test-suggestions/crs-auth-settings-behavior.yaml) | Covered (S5 often blocked) |
| §8 requireReasonForInteraction | Audit settings; [RQA-5841](https://opentrons.atlassian.net/browse/RQA-5841) | Known API bypass; not asserted as pass |
| §9 HTTPS for credentials | Discovery forces HTTPS when CRS is on; lockdown `plaintext_http_*` (HTTP `:31950` must not serve the API) | Harness enforced; product still served HTTP on KansasFLEX `v10.0.0-alpha.4` ([RQA-5981](https://opentrons.atlassian.net/browse/RQA-5981) Closed Won't Do). Do not use HTTP for CRS-on API work. |
| §10 Frontend UI state | App/ODD | Out of scope |
| §11 Audit logs | `flex-test audit list\|download` / [crs-audit-logs.yaml](test-suggestions/crs-audit-logs.yaml) | List/download covered; hash-chain viewer is product |
| §12 Test DB migration | Release engineering | Out of scope |
| PRD: SSH/Jupyter off when CRS on | `flex-test ssh status`; `flex-test serial remote-access-status` (SSH first) | Covered (status); carveout is lab-only |
| PRD: delete protocol run record removed in CRS | Not a dedicated suite step | Gap (spot-check DELETE `/runs/{id}` vs product) |
| PRD: Quick Transfer disabled | App/ODD | Out of scope |
| PRD: protocol sign-off | `settings-suite` S9 | Covered (HTTP PATCH signedBy) |
| PRD: requireAdminCreds for update / send protocol | `settings-suite` S7 / S8 / S10 | Covered |
| Product: 21 CFR tooling, not Flex certification | Narrative in this doc | Documented; not a suite |
| Product: Documentation Required on App/ODD mutations | `Opentrons-User-Notes` on CRS-on HTTP; 451 vs [RQA-5841](https://opentrons.atlassian.net/browse/RQA-5841) | Partial (UI out of scope) |
| Product: Analysis bypasses auth + documentation | [RQA-6012](https://opentrons.atlassian.net/browse/RQA-6012); `scripts/retest_rqa6012.py` | Covered (HTTP) |
| Product: Pause waits for a documentation note | Operator note; door / E-Stop | Expected; do not file as a bug |
| Product: File Manager / no auto-delete | `flex-test audit` + `logs archive`; USB/ODD UI out of scope | Partial |
| Product: subprocess isolation (`ot-protocol` user) | [pyro-testing.md](pyro-testing.md) | Covered (separate suite) |
| Product: `PATCH /runs/{id}` body-dependent scopes | `settings-suite` S9 signedBy | Partial |

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
   After that, prefer `flex-test ssh` over serial ([interaction-layers.md](interaction-layers.md)).

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
uv run flex-test ssh status
uv run flex-test serial remote-access-status   # SSH first, serial if SSH fails
# Close Tabby first (exclusive serial port) for first-time carveout:
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

`allow-remote-access` is `DISRUPTIVE` (remounts `/` RW) and requires
`ALLOW_MUTATIONS=true`. Use it only when SSH is locked out. After the
sentinel exists, use SSH for shell work.

### Not the same as disable / wipe

| Goal | Path |
|------|------|
| Keep CRS on, restore lab SSH/Jupyter/devtools | Serial allow-file carveout (this section), then SSH |
| Turn CRS **off** again (preferred lab path) | Root shell: `opentrons_disable_crs` with `{serial}-0000` (see Enter / exit CRS) |
| Turn CRS **off** when disable binary unavailable | EXEC-2176 / assisted wipe (not this harness) |

## Safety

Unchanged from [safety-model.md](safety-model.md):

- Mutations default off
- Enable CRS only via `flex-test crs enable --confirm-one-way` (catalog probes never PATCH it)
- No first-class physical-motion CLI; live play only on explicit request
- Timeouts on all HTTP; redact secrets in evidence
- Re-check `ROBOT_HOST` (DHCP)

## Workstreams

1. **Catalog + Tier A**: done (`flex-test probe`).
2. **Domain clients + Tier B/C + api-suite**: done (`flex-test crs-off-b|crs-off-c|api-suite`).
3. **Run-state preflight**: done for Tier A/B/C (`flex-test run-state`).
4. **CRS-off Tier C expansion**: more of the ~57 reversible catalog mutations
   beyond the current 7 cleanup steps.
5. **CRS-off Tier D expansion**: more disruptive catalog coverage beyond install.
6. **OAuth + users + enable**: done (`clients/oauth.py`, `clients/users.py`,
   gated `flex-test crs enable --confirm-one-way`).
7. **CRS-on authorization matrix + lockdown + A/B/C suite**: done
   (`flex-test crs lockdown|auth-matrix|probe|probe-b|probe-c|suite`).
8. **Auth settings behavior suite**: done (`flex-test crs settings-suite`;
   [crs-auth-settings-behavior.yaml](test-suggestions/crs-auth-settings-behavior.yaml)).
9. **User-management / password-reset API**: done (`flex-test crs users-api`;
   [crs-user-management-onboarding.yaml](test-suggestions/crs-user-management-onboarding.yaml)).
10. **Audit list/download**: done (`flex-test audit`;
    [crs-audit-logs.yaml](test-suggestions/crs-audit-logs.yaml)). Hash-chain
    viewer and delete-period remain product / DISRUPTIVE.
11. **Remaining gaps**: logout/revoke API (none in catalog); DELETE run-record
    blocked-in-CRS assertion; requireReasonForInteraction API (RQA-5841);
    ODD/App UI (QA §3–5, §9–10, Documentation Required, File Manager, USB
    export). Do not add “pause requires a note” as a gap; that is expected.

## Related harness docs

- [interaction-layers.md](interaction-layers.md)
- [crs-on-setup.md](crs-on-setup.md)
- [architecture.md](architecture.md) (dual-mode AC note)
- [safety-model.md](safety-model.md)
- [robot-logs.md](robot-logs.md) (audit vs diagnostic vs protocol run logs)
- [serial-console.md](serial-console.md) (FTDI; used for allow-remote-access)
- [source-research.md](source-research.md)
- [development-plan.md](development-plan.md)
- [pyro-testing.md](pyro-testing.md) (protocol subprocess exists so CRS can isolate runs)
- Published plans: [test-suggestions/](test-suggestions/)
