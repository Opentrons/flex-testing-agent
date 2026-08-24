# flex-testing-agent

Local, agentic robot-testing harness for a physical Opentrons Flex robot (**KansasFLEX**).

The core product is a reusable Python harness. Cursor, MCP, and other agent runtimes are optional adapters, not foundations.

**License:** [Apache-2.0](LICENSE)  
**Published test suggestions:** [opentrons.github.io/flex-testing-agent](https://opentrons.github.io/flex-testing-agent/)

## Purpose

- Connect to and inspect a local Flex robot
- Interact with existing robot HTTP APIs and services
- Detect access-control state; CRS-off and CRS-on HTTP suites
- Understand published Flex robot OS versions (internal vs external; alpha/beta/stable)
- Persist runs, snapshots, evidence, and findings
- Support deterministic scenarios now, and bounded agent exploration later

## Current scope

Implemented:

- Typed configuration via environment / `.env`
- Async clients: health, update, protocols/runs, camera, offsets, maintenance, etc.
- CLI: `inspect`, `probe`, `releases`, `put`/`install`, `run-state`, `crs-off-b|c`, `api-suite`,
  `crs` (enable/trust-ca/lockdown/matrix/probe/suite/settings/users-api), `audit`,
  `serial` (FTDI console)
- Known-state + seed history: `reset-data`, `known-state`, `seed-runs` (motion; gated)
- LPC jog latency: `lpc-jog-timing --confirm-clear-deck` (high-Z safe box; gated)
- SQLite persistence + Alembic migrations; evidence under `ARTIFACT_DIRECTORY`
- Unit and mocked integration tests
- Local reference clones under `upstream/` (gitignored): `opentrons`, `robot-stack`
- FTDI USB serial console client (`flex-test serial`) as a Tabby alternative

Not implemented yet:

- Full catalog mutation coverage beyond Tier C sample
- Logout/revoke API (no auth-server route in the catalog)
- Dedicated assertion that CRS blocks DELETE of protocol run records
- Autonomous agent runtime / local web UI
- OEM / factory mode (ignored by design)

## Architecture overview

```text
Agent skills or test missions
        ↓
Robot capability harness
        ↓
Typed robot clients
        ↓
Flex robot APIs and services
```

See [docs/architecture.md](docs/architecture.md). How operators/agents choose
HTTPS vs SSH vs serial: [docs/interaction-layers.md](docs/interaction-layers.md).

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
cp .env.example .env
# Edit ROBOT_HOST (and optional reference clone paths)

uv sync --all-extras
```

Keep local read-only clones for research (common layout, gitignored):

- `OPENTRONS_REPO_PATH=./upstream/opentrons`
- `ROBOT_STACK_REPO_PATH=./upstream/robot-stack` (release tagging + `releases.json` docs)

This harness does not modify those clones. Version/channel knowledge is summarized in [docs/robot-versions.md](docs/robot-versions.md).

## Configuration

See [.env.example](.env.example). Important keys:

| Variable | Purpose |
|----------|---------|
| `ROBOT_HOST` | Preferred Flex IP or hostname |
| `ROBOT_HOST_CANDIDATES` | Comma-separated fallbacks (default `192.168.0.21,192.168.0.20`) |
| `ROBOT_NAME` | Display name (default `KansasFLEX`) |
| `OPENTRONS_REPO_PATH` | Local Opentrons monorepo path |
| `ROBOT_STACK_REPO_PATH` | Local robot-stack clone (release docs) |
| `ALLOW_MUTATIONS` | Must stay `false` unless you intentionally allow mutations |
| `DATABASE_URL` | Default SQLite under `./artifacts` |
| `ARTIFACT_DIRECTORY` | Evidence and lock files |
| `SERIAL_PORT` | Optional FTDI device path (empty = auto-detect) |
| `SERIAL_BAUD_RATE` | Serial console baud (default `115200`) |

Do not commit credentials.

## Running unit tests

```bash
make test
# or
uv run pytest
```

Default pytest selection excludes `requires_robot` and `mutates_robot`.

## Running the inspection command

```bash
uv run flex-test inspect
```

Expected summary fields: robot name/host, connectivity, installed versions,
access-control state, health, run id, evidence directory.

## CRS-off API suite and seed history

```bash
# Read-only Tier A catalog probe
uv run flex-test probe

# Full A+B+C with timing (mutations + fixtures; see docs/crs-testing.md)
ALLOW_MUTATIONS=true uv run flex-test api-suite

# Seed succeeded/paused/failed/LPC history for Tier B (physical motion)
ALLOW_MUTATIONS=true uv run flex-test seed-runs

# LPC-like random jogs in a high-Z safe box (C2 empty; latency JSON)
ALLOW_MUTATIONS=true uv run flex-test lpc-jog-timing --confirm-clear-deck
```

## CRS-on API suite

Requires access control enabled, HTTPS CA trust, and fixture users. See
[docs/crs-on-setup.md](docs/crs-on-setup.md), [docs/crs-testing.md](docs/crs-testing.md),
and the transport ladder in [docs/interaction-layers.md](docs/interaction-layers.md).
CRS-on API calls use HTTPS `:32313` only (plaintext `:31950` may still answer;
do not use it).

```bash
ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way
ALLOW_MUTATIONS=true uv run flex-test crs trust-ca --password 'word-word-word'
# Then set ROBOT_USE_HTTPS=true in .env

ROBOT_USE_HTTPS=true uv run flex-test crs lockdown --show-failures
ROBOT_USE_HTTPS=true uv run flex-test crs auth-matrix
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs suite --include-lockdown
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs settings-suite
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs users-api
uv run flex-test audit list
```

## Listing published Flex releases

```bash
uv run flex-test releases
uv run flex-test releases --channel internal
uv run flex-test releases --channel external
uv run flex-test releases --installed 4.0.0-alpha.5
```

This reads public `ot3-oe/releases.json` manifests (internal + external hosts from robot-stack) and prints the latest **stable**, **alpha**, and **beta** robot OS versions per channel. See [docs/robot-versions.md](docs/robot-versions.md).

## Installing a robot OS version (mutates robot)

```bash
# Requires ALLOW_MUTATIONS=true in .env
uv run flex-test put 9.1.2-alpha.0
# equivalent:
uv run flex-test install 9.1.2-alpha.0 --channel external
# Current Pyro / protocol-subprocess line (external; same stack as former
# internal 4.0.0-alpha.*). See docs/robot-versions.md and docs/pyro-testing.md.
uv run flex-test put 10.0.0-alpha.0 --channel external
```

This downloads the published `ot3-system.zip` for that version, uploads it through update-server (`/server/update/*`), commits, restarts, and verifies `system_version`.

When CRS (access control) is enabled, set `ROBOT_USERNAME` / `ROBOT_PASSWORD` so `put` can obtain an OAuth bearer token; otherwise update-server returns 401.

On Pyro builds (`10.0.0-alpha.*`), `/health` may return nginx **502** for several minutes after commit while firmware flashes and robot-server attaches to the nameserver. Prefer **full robot reboot** if still unhealthy after firmware is idle. See [docs/pyro-testing.md](docs/pyro-testing.md).

## Lab SSH and FTDI serial

How to pick HTTPS vs SSH vs serial: [docs/interaction-layers.md](docs/interaction-layers.md).
Serial hardware: [docs/serial-console.md](docs/serial-console.md).
[Confluence FTDI guide](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex).

```bash
uv run flex-test ssh status
uv run flex-test ssh run "systemctl is-active opentrons-robot-server"
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
uv run flex-test serial list
uv run flex-test serial shell
```

## Robot logs

Audit vs diagnostic vs protocol run logs (and how they differ from FTDI
transcripts): [docs/robot-logs.md](docs/robot-logs.md).

```bash
uv run flex-test logs list
uv run flex-test logs archive   # ARTIFACT_DIRECTORY/logs/<stamp>-<host>/
```

After `seed-runs` / `api-suite` / install verification, agents should archive
logs and review them (see operate-kansasflex skill).

## Running robot integration tests

```bash
# Requires ROBOT_HOST and a reachable Flex
uv run pytest -m requires_robot
```

These tests are read-only. No test mutates a physical robot unless explicitly selected with `mutates_robot` (none are shipped in milestone 1).

## Safety warnings

- This harness talks to a **real robot**.
- Access control (`PATCH /auth/settings/accessControlEnabled`) is **one-way**.
  Enable only via `ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way`.
  Catalog probes never call that PATCH.
- Mutations are disabled by default (`ALLOW_MUTATIONS=false`).
- First-class physical motion capabilities are out of scope; live protocol play only with explicit operator request and deck preflight.
- Prefer dry-run and read-only inspect while developing.
- Re-check `ROBOT_HOST` before installs (lab DHCP can move the robot).

See [docs/safety-model.md](docs/safety-model.md). For internal Pyro / protocol-subprocess validation on KansasFLEX, see [docs/pyro-testing.md](docs/pyro-testing.md).

## Current limitations

- HTTP when CRS is off; HTTPS when CRS is on (forced after `flex-test crs trust-ca`)
- Access-control dual-mode is implemented (optional bearer token + CRS-on suites)
- Lockdown smoke scenario YAML is a historical placeholder; use `flex-test crs lockdown`
- Agent session / tool / token tables exist but are unused

## Roadmap

See [docs/development-plan.md](docs/development-plan.md).

Next focus: remaining CRS gaps in [docs/crs-testing.md](docs/crs-testing.md)
(logout/revoke, DELETE-run-in-CRS, reason-for-interaction API) and scenario-runner polish.

## Publishing test suggestions (GitHub Pages)

Release-driven robot test plans live as YAML in [`docs/test-suggestions/`](docs/test-suggestions/). Pushing to `main` builds and deploys the public site via [`.github/workflows/pages.yml`](.github/workflows/pages.yml).

```bash
# Local preview
make pages
open pages/index.html
```

Authoring guide: [docs/test-suggestions/README.md](docs/test-suggestions/README.md).

## Docs

- [Architecture](docs/architecture.md)
- [Interaction layers](docs/interaction-layers.md) (HTTPS vs SSH vs serial)
- [Robot versions and releases](docs/robot-versions.md)
- [Pyro / protocol-subprocess testing](docs/pyro-testing.md)
- [Monorepo release pattern](docs/monorepo-releases.md) (`opentrons/opentrons` / `chore_release-*`)
- [Source research](docs/source-research.md)
- [Prior-art review](docs/prior-art-review.md)
- [Robot state model](docs/robot-state-model.md)
- [Safety model](docs/safety-model.md)
- [Development plan](docs/development-plan.md)
- [Test suggestions](docs/test-suggestions/README.md)

## For coding agents

- [CLAUDE.md](CLAUDE.md) — repo map, extension pattern, mandatory lint/typecheck
- Cursor rules: [`.cursor/rules/`](.cursor/rules/) (always apply; includes quality gates)
- Cursor skills: [`.cursor/skills/`](.cursor/skills/) (`extend-flex-harness`, `operate-kansasflex`)

After any code change: `make lint` (ruff + mypy) and `make test` must pass.
