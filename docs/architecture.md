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

Clients are independent of scenarios and agents. They raise explicit timeout/API errors.

### Release catalog (robot-stack aligned)

`src/flex_testing_agent/releases/` fetches Flex robot OS `ot3-oe/releases.json` from the internal and external CDN hosts documented by Opentrons/robot-stack. It classifies **stable / alpha / beta** and maps bare manifest keys to stack tags (`ot3@…` internal, `v…` external). This is separate from robot mutation: it only reads public manifests. See [robot-versions.md](robot-versions.md).

### 2. Robot capabilities

Capabilities in `src/flex_testing_agent/capabilities/` compose client calls into meaningful operations with:

- Preconditions / postconditions
- Risk level metadata
- Evidence production
- Mutation-gate checks

Milestone 1 ships `inspect_robot` (`READ_ONLY`). Enabling access control is explicitly blocked.

### 3. Scenarios and orchestration

YAML under `scenarios/` describes metadata only. Execution is typed Python (`scenarios/runner.py`).

Orchestration owns:

- Exclusive robot lock (`filelock` per host)
- Run context / IDs
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

## Dual-mode access control

When `accessControlEnabled` is false (default on many robots), protected endpoints allow unauthenticated access. Inspect runs without credentials.

When access control is enabled later, `RobotHttpSession` can attach an optional bearer token. Milestone 1 does not implement login or enablement. Testing with AC off remains the primary path.

## Future agent integration

Capability descriptors (`CapabilityDescriptor`) already carry name, description, risk, schemas, and evidence lists. A future bounded agent may only call allowlisted `READ_ONLY` and carefully controlled reversible capabilities. Arbitrary shell, arbitrary HTTP, and arbitrary robot URLs stay forbidden.
