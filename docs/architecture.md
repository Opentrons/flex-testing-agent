# Architecture

## Core principle

The robot-testing harness is the product. Agent runtimes (Cursor, Claude, MCP, SDKs) are optional adapters that call into an allowlisted capability surface.

```text
Agent skills or test missions
        ↓
Robot capability harness
        ↓
Typed robot clients
        ↓
Flex robot APIs and services
```

## Layers

### 1. Atomic API clients

Small async `httpx` wrappers in `src/flex_testing_agent/clients/`:

- `RobotHttpSession`: shared headers (`Opentrons-Version: 3`), timeouts, optional bearer token
- `HealthClient`: `GET /health`
- `UpdateHealthClient`: `GET /server/update/health`
- `AuthSettingsClient`: GET detect plus GET/PATCH/DELETE `/auth/settings`;
  enable CRS only via gated `flex-test crs enable --confirm-one-way`
- `ProtocolsClient` / `RunsClient` / `DataFilesClient`: protocol upload, run create
  (no play), CSV files for CRS-off Tier B fixtures
- `MaintenanceRunsClient` / `LabwareOffsetsClient`: scripted LPC seed + Tier B
  maintenance command fixtures
- `ClientDataClient` / `RobotControlClient` / `CameraClient` /
  `ErrorRecoveryClient`: reversible Tier C mutations (lights, clientData,
  camera enable/stream settings, errorRecovery)
- `OAuthClient` / `UsersClient` / `AuditClient`: CRS-on ROPC, user CRUD, audit periods

Clients are independent of scenarios and agents. They raise explicit timeout/API errors.

### Release catalog (robot-stack aligned)

`src/flex_testing_agent/releases/` fetches Flex robot OS `ot3-oe/releases.json` from the internal and external CDN hosts documented by Opentrons/robot-stack. It classifies **stable / alpha / beta** and maps bare manifest keys to stack tags (`ot3@…` internal, `v…` external). This is separate from robot mutation: it only reads public manifests. See [robot-versions.md](robot-versions.md).

### Serial console (FTDI cable)

`src/flex_testing_agent/serial_console/` talks to the Flex SOM serial header over a
local USB FTDI adapter (not HTTP). CLI: `flex-test serial list|shell|run`. See
[serial-console.md](serial-console.md). This sits beside HTTP clients and the
release catalog as a lab debug transport (Tabby replacement).

### 2. Robot capabilities

Capabilities in `src/flex_testing_agent/capabilities/` compose client calls into meaningful operations with:

- Preconditions / postconditions
- Risk level metadata
- Evidence production
- Mutation-gate checks

Capabilities include `inspect`, `probe`, `crs_off` Tier B/C, `api_suite`,
CRS-on lockdown/matrix/probe/suite, `seed_runs` / `seed_lpc`, `lpc_jog_timing`,
install, reset-data, and known-state. Enabling access control is gated
(`flex-test crs enable --confirm-one-way`); catalog probes never call that PATCH.

### 3. Scenarios and orchestration

YAML under `scenarios/` describes metadata only. Execution is typed Python (`scenarios/runner.py`).

Orchestration owns:

- Exclusive robot lock (`filelock` per host)
- Run context / IDs
- Protocol-run presence preflight (`run_state.py`: verify / ensure
  `no-current` vs `current-idle` for CRS suites)
- Mutation and dry-run gates
- Persistence and evidence wiring

### Persistence

SQLAlchemy + Alembic + SQLite (`aiosqlite`). Domain code uses `SqlStore`; the URL can later point at PostgreSQL without rewriting capability logic.

### Evidence

Each run writes redacted JSON under `ARTIFACT_DIRECTORY/runs/<run_id>/`.

## Why MCP is optional

MCP is a transport for tools. The harness must remain usable from:

- Direct Python APIs
- CLI
- pytest
- A future local service API
- Optional MCP / Agent SDK adapters

Making MCP foundational would couple robot safety and auditability to one agent protocol. Instead, capability descriptors declare schemas and risk so any adapter can expose the same allowlist.

## Dual-mode CRS (access control)

**CRS** (Compliance Ready Software) is a robot **mode** that supplies 21 CFR
Part 11 *tooling* (identity, signed audit, HTTPS). A CRS-on Flex is **not**
itself Part 11 certified. API flag: `accessControlEnabled` (ACM / RCS in older
docs). Product model, documentation-required / 451, File Manager, and suite
tiers: [crs-testing.md](crs-testing.md).

When CRS is off (default for KansasFLEX lab work), protected endpoints allow
unauthenticated access. Inspect and `flex-test probe` run without credentials.
The full HTTP inventory lives in `catalog/endpoints.py` (all methods); Tier A
CRS-off coverage is parameter-free GETs via `ReadonlyClient`.

When CRS is on, `RobotHttpSession` attaches an optional bearer token (ROPC via
`clients/oauth.py`). Mutating requests also send `Opentrons-User-Notes`.
`/clientData` is an exception: App/ODD in-memory coordination, not under CRS
(unauthenticated PUT/DELETE 200 is expected; RQA-5918). Enablement is one-way
and gated: `flex-test crs enable --confirm-one-way`.
Restore: serial **remote-access carveout** for SSH/Jupyter while CRS stays on
(`flex-test serial allow-remote-access`), root-shell `opentrons_disable_crs`
(password `{robot_serial}-0000`) to turn CRS off, and EXEC-2176 wipe as
fallback. See [crs-testing.md](crs-testing.md) and
[crs-on-setup.md](crs-on-setup.md).

HTTP servers involved (frontend talks to this cluster):

```text
Frontend
   |
auth-server  <->  robot-server, system-server, update-server
audit-server <->  robot-server, system-server, update-server
key-server        (CAAM: TLS certs + audit signing)
```

A typical mutation: `POST /auth/oauth2/token` → resource `POST` with bearer →
resource `POST /auth/oauth2/introspect` → async audit event. Protocol execution
is a **separate** `ot-protocol` process ([pyro-testing.md](pyro-testing.md)) so
runs stay isolated from robot-server.

## Future agent integration

Capability descriptors (`CapabilityDescriptor`) already carry name, description, risk, schemas, and evidence lists. A future bounded agent may only call allowlisted `READ_ONLY` and carefully controlled reversible capabilities. Arbitrary shell, arbitrary HTTP, and arbitrary robot URLs stay forbidden.

## Related operator docs

- [CRS testing](crs-testing.md) (product model + dual-mode SSOT + PRD coverage)
- [CRS-on setup](crs-on-setup.md)
- [Pyro / protocol-subprocess testing](pyro-testing.md) (CRS isolation of runs)
- [FTDI serial console](serial-console.md) (`flex-test serial`; Tabby alternative)
- [Robot logs](robot-logs.md) (audit vs diagnostic vs protocol run logs)
- [Safety model](safety-model.md)
- Published checklists: [test-suggestions/](test-suggestions/)
