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
- `AuthSettingsClient`: `GET /auth/settings/accessControlEnabled` (detect only)
- `ProtocolsClient` / `RunsClient` / `DataFilesClient`: protocol upload, run create
  (no play), CSV files for CRS-off Tier B fixtures
- `MaintenanceRunsClient` / `LabwareOffsetsClient`: scripted LPC seed + Tier B
  maintenance command fixtures
- `ClientDataClient` / `RobotControlClient` / `CameraClient` /
  `ErrorRecoveryClient`: reversible Tier C mutations (lights, clientData,
  camera enable/stream settings, errorRecovery)

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
`seed_runs` / `seed_lpc`, install, reset-data, and known-state. Enabling access
control is explicitly blocked.

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

**CRS** (Compliance Ready Software) is the product name for robot
`accessControlEnabled` (also called ACM / RCS in older docs). Design and suite
tiers: [crs-testing.md](crs-testing.md).

When CRS is off (default for KansasFLEX lab work), protected endpoints allow
unauthenticated access. Inspect and `flex-test probe` run without credentials.
The full HTTP inventory lives in `catalog/endpoints.py` (all methods); Tier A
CRS-off coverage is parameter-free GETs via `ReadonlyClient`.

When CRS is enabled later, `RobotHttpSession` can attach an optional bearer
token. This harness does not implement enablement (one-way API). CRS-on matrix
testing waits on restore: serial **remote-access carveout** for SSH/Jupyter while
CRS stays on (`flex-test serial allow-remote-access`), and EXEC-2176 wipe to turn
CRS off. See [crs-testing.md](crs-testing.md).

## Future agent integration

Capability descriptors (`CapabilityDescriptor`) already carry name, description, risk, schemas, and evidence lists. A future bounded agent may only call allowlisted `READ_ONLY` and carefully controlled reversible capabilities. Arbitrary shell, arbitrary HTTP, and arbitrary robot URLs stay forbidden.

## Related operator docs

- [Pyro / protocol-subprocess testing](pyro-testing.md) on internal Flex builds (SSH + HTTP suites; harness gaps)
- [FTDI serial console](serial-console.md) (`flex-test serial`; Tabby alternative)
- [Robot logs](robot-logs.md) (audit vs diagnostic vs protocol run logs)
- [Safety model](safety-model.md)
- Published checklists: [test-suggestions/](test-suggestions/)
