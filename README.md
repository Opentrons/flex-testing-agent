# flex-testing-agent

Local, agentic robot-testing harness for a physical Opentrons Flex robot (**KansasFLEX**).

The core product is a reusable Python harness. Cursor, MCP, and other agent runtimes are optional adapters, not foundations.

**License:** [Apache-2.0](LICENSE)  
**Published test suggestions:** [opentrons.github.io/flex-testing-agent](https://opentrons.github.io/flex-testing-agent/)

## Purpose

- Connect to and inspect a local Flex robot
- Interact with existing robot HTTP APIs and services
- Detect access-control state (read-only in milestone 1)
- Understand published Flex robot OS versions (internal vs external; alpha/beta/stable)
- Persist runs, snapshots, evidence, and findings
- Support deterministic scenarios now, and bounded agent exploration later

## Current scope (milestone 1)

Implemented:

- Typed configuration via environment / `.env`
- Async atomic clients: health, update health, access-control detection
- `FlexRobot` + `inspect_robot` capability
- CLI: `uv run flex-test inspect`
- CLI: `uv run flex-test releases` (latest internal/external robot OS builds)
- CLI: `uv run flex-test put <version>` / `install` (robot OS install; requires `ALLOW_MUTATIONS=true`)
- SQLite persistence + Alembic migrations
- Evidence capture under `ARTIFACT_DIRECTORY`
- Unit and mocked integration tests
- Local reference clones under `upstream/` (gitignored): `opentrons`, `robot-stack`

Not implemented yet:

- Enabling access control (intentionally blocked; one-way on robot)
- User provisioning / authorization matrix
- Software build installation onto Kansas
- Physical motion
- Autonomous agent runtime
- Local web UI
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

See [docs/architecture.md](docs/architecture.md).

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
| `ROBOT_HOST` | Flex IP or hostname |
| `ROBOT_NAME` | Display name (default `Kansas`) |
| `OPENTRONS_REPO_PATH` | Local Opentrons monorepo path |
| `ROBOT_STACK_REPO_PATH` | Local robot-stack clone (release docs) |
| `ALLOW_MUTATIONS` | Must stay `false` unless you intentionally allow mutations |
| `DATABASE_URL` | Default SQLite under `./artifacts` |
| `ARTIFACT_DIRECTORY` | Evidence and lock files |

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

Expected summary fields:

- Robot name / host
- Connectivity
- Installed software and service versions
- Access-control state (`disabled` / `enabled` / `unknown` / `unsupported`)
- Health status
- Run identifier
- Evidence directory

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
```

This downloads the published `ot3-system.zip` for that version, uploads it through update-server (`/server/update/*`), commits, restarts, and verifies `system_version`.

## Running robot integration tests

```bash
# Requires ROBOT_HOST and a reachable Flex
uv run pytest -m requires_robot
```

These tests are read-only. No test mutates a physical robot unless explicitly selected with `mutates_robot` (none are shipped in milestone 1).

## Safety warnings

- This harness talks to a **real robot**.
- Access control (`PATCH /auth/settings/accessControlEnabled`) is **one-way**. This harness never enables it.
- Mutations are disabled by default (`ALLOW_MUTATIONS=false`).
- Physical motion capabilities are out of scope.
- Prefer dry-run and read-only inspect while developing.

See [docs/safety-model.md](docs/safety-model.md).

## Current limitations

- HTTP by default; HTTPS CA bootstrap deferred
- Access-control dual-mode is prepared (optional bearer token), but inspect assumes AC off for unauthenticated reads
- Lockdown smoke scenario YAML exists as a documented placeholder only
- Agent session / tool / token tables exist but are unused

## Roadmap

See [docs/development-plan.md](docs/development-plan.md).

Next focus: dual-mode auth session hardening and scenario-runner polish, still without enabling access control.

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
- [Robot versions and releases](docs/robot-versions.md)
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
