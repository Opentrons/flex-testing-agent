# CLAUDE.md — flex-testing-agent

Guidance for Claude (and other coding agents) working in this repository.

## What this repo is

A **local Python harness** for testing a physical Opentrons Flex robot named **KansasFLEX**. Package: `flex_testing_agent`. CLI: `flex-test`. Python 3.12+, managed with **`uv`**.

The harness is the product. Agent runtimes are optional adapters that should call allowlisted capabilities, not invent their own robot HTTP clients.

## Read these first

- [README.md](README.md) — setup, CLI, safety warnings
- [docs/architecture.md](docs/architecture.md) — layers and extension model
- [docs/safety-model.md](docs/safety-model.md) — mutation gates, AC one-way rule
- [docs/robot-versions.md](docs/robot-versions.md) — Flex OS releases / channels
- [docs/pyro-testing.md](docs/pyro-testing.md) — Pyro5 / protocol-subprocess on internal Flex builds
- [docs/serial-console.md](docs/serial-console.md) — FTDI console setup (humans + agents; Tabby alternative)
- [docs/robot-logs.md](docs/robot-logs.md) — audit vs diagnostic vs protocol run logs
- Cursor rules under [`.cursor/rules/`](.cursor/rules/)
- Skills under [`.cursor/skills/`](.cursor/skills/) (`extend-flex-harness`, `operate-kansasflex`)

## Quality gates (always)

**All code must be typechecked and linted before you finish a change.**

```bash
make lint   # ruff check + ruff format --check + mypy (strict)
make test   # pytest (excludes requires_robot / mutates_robot by default)
```

Do not weaken mypy/ruff config or leave failing checks. Prefer `make format` then re-lint.

## How to extend (required pattern)

```text
clients/  →  capabilities/  →  scenarios or CLI
```

1. Add typed async clients in `src/flex_testing_agent/clients/` using `RobotHttpSession`
2. Compose operations as capabilities with `CapabilityDescriptor` + risk + `ensure_mutation_allowed`
3. For HTTP coverage, update `catalog/endpoints.py` (CRS matrix); GETs feed `READONLY_ENDPOINTS`
4. Wire `FlexRobot` and/or `flex-test` CLI thinly
5. Add `respx` unit tests; use `@pytest.mark.requires_robot` only for live tests

See skill: `.cursor/skills/extend-flex-harness/SKILL.md`.

## What already exists

| Capability | Entry |
|------------|--------|
| Inspect snapshot | `flex-test inspect` / `capabilities/inspect.py` |
| Probe / CRS-off A+B+C | `flex-test probe\|crs-off-b\|c\|api-suite` |
| Seed run history / LPC | `flex-test seed-runs` / `capabilities/seed_runs.py` |
| Camera JPEG | `clients/camera.py` (via probe) |
| Release catalog | `flex-test releases` / `releases/` |
| Install robot OS | `flex-test put\|install` / `capabilities/install.py` |
| AC detect only | `clients/auth_settings.py` (never PATCH-enable) |
| FTDI serial console | `flex-test serial` / `serial_console/` ([docs/serial-console.md](docs/serial-console.md)) |
| Diagnostic logs archive | `flex-test logs list\|archive` / `clients/logs.py` ([docs/robot-logs.md](docs/robot-logs.md)) |

Reference clones (gitignored):

- `upstream/opentrons` — the **monorepo** (`opentrons/opentrons`)
- `upstream/robot-stack` — Flex OS tagging / `releases.json`

Point-release branch pattern (`chore_release-X.Y.Z`, cherry-picks, PD mergebacks): [docs/monorepo-releases.md](docs/monorepo-releases.md).

Published test suggestions (YAML → GitHub Pages on `main`): [docs/test-suggestions/](docs/test-suggestions/). Preview with `make pages`.

## Safety (non-negotiable)

- Mutations off unless `ALLOW_MUTATIONS=true`
- Never enable access control (API is one-way)
- No first-class physical motion capabilities; live protocol play only if the user explicitly asks (see `docs/pyro-testing.md`)
- Timeouts on all robot HTTP
- Do not commit `.env` or secrets
- Re-check `ROBOT_HOST` (DHCP can move KansasFLEX)

## Common commands

```bash
uv sync --all-extras
cp .env.example .env   # set ROBOT_HOST
uv run flex-test inspect
uv run flex-test probe
uv run flex-test releases
ALLOW_MUTATIONS=true uv run flex-test api-suite
ALLOW_MUTATIONS=true uv run flex-test seed-runs
ALLOW_MUTATIONS=true uv run flex-test put <version>
# Internal / Pyro stack:
ALLOW_MUTATIONS=true uv run flex-test put 4.0.0-alpha.10 --channel internal
# FTDI serial console (Tabby alternative; close Tabby first if port busy):
uv run flex-test serial list
uv run flex-test serial shell
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
# After seed / api-suite / install verification:
uv run flex-test logs archive
```

Operate against the robot via skill: `.cursor/skills/operate-kansasflex/SKILL.md`.
Pyro validation checklist: `docs/test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml`.
