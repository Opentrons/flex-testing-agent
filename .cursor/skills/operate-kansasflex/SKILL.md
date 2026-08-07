---
name: operate-kansasflex
description: >-
  Operates the local Opentrons Flex KansasFLEX through flex-testing-agent CLI
  and Python APIs. Use when inspecting robot state, probing read-only endpoints,
  taking camera pictures, listing Flex OS releases, installing a robot OS build
  with ALLOW_MUTATIONS, running Pyro / protocol-subprocess validation on
  internal Flex builds, or using the FTDI serial console (`flex-test serial`)
  instead of Tabby.
---

# Operate KansasFLEX

## Prerequisites

- `.env` with `ROBOT_HOST` (and usually `ROBOT_NAME=KansasFLEX`)
- Optional `ROBOT_HOST_CANDIDATES=192.168.0.21,192.168.0.20` (defaults in settings)
- `uv sync --all-extras`
- Mutations only when `.env` has `ALLOW_MUTATIONS=true`
- CLI/runners **probe candidates** via `GET /health` and bind the live host
  (DHCP has moved KansasFLEX between `.20` and `.21`)

## Preferred commands

```bash
# Read-only snapshot (also confirms host reachability)
uv run flex-test inspect

# Protocol-run presence (suites verify this; see docs/crs-testing.md)
uv run flex-test run-state
ALLOW_MUTATIONS=true uv run flex-test run-state --ensure no-current
ALLOW_MUTATIONS=true uv run flex-test run-state --ensure current-idle

# Full read-only endpoint probe + optional camera JPEG (default: no-current)
uv run flex-test probe
uv run flex-test probe --ensure-run-state   # uncurrent if needed
uv run flex-test probe --no-picture
uv run flex-test probe --picture ./artifacts/camera/kansasflex.jpg

# CRS-off A+B+C suite (fixtures + reversible mutations; docs/crs-testing.md)
ALLOW_MUTATIONS=true uv run flex-test api-suite
ALLOW_MUTATIONS=true uv run flex-test crs-off-b --create-fixtures
ALLOW_MUTATIONS=true uv run flex-test crs-off-c

# Seed succeeded/paused/failed/LPC history for Tier B (physical motion)
ALLOW_MUTATIONS=true uv run flex-test seed-runs

# Published Flex robot OS versions (CDN manifests)
uv run flex-test releases
uv run flex-test releases --channel internal

# Install OS build (mutates; needs ALLOW_MUTATIONS=true); records timing JSON
ALLOW_MUTATIONS=true uv run flex-test put 9.1.2-alpha.5 --channel external
# Internal / ot3@ stack (Pyro subprocess builds):
ALLOW_MUTATIONS=true uv run flex-test put 4.0.0-alpha.10 --channel internal

# Known-state baseline (clear robot-server DB + Kansas deck; no play)
ALLOW_MUTATIONS=true uv run flex-test reset-data
ALLOW_MUTATIONS=true uv run flex-test known-state
uv run flex-test timing
# Design: docs/known-state-and-latency.md
```

## FTDI serial console (no Tabby)

Setup + agent rules: [docs/serial-console.md](../../docs/serial-console.md).
Hardware photos / orientation:
[Confluence FTDI guide](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex).

Prefer HTTP/`inspect`/`probe` when the network works. Use serial for boot logs,
DHCP loss, or SSH unreachable. **Close Tabby first** (port is exclusive).

```bash
uv run flex-test serial list
uv run flex-test serial shell
uv run flex-test serial watch --seconds 30
uv run flex-test serial run "systemctl is-active opentrons-robot-server"
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

CRS-on: `allow-remote-access` restores SSH/Jupyter/devtools via
`/etc/opentrons-allow-remote-access` (does **not** turn CRS off; redo after OS
update). Kernel printk on the FTDI console is expected and useful
([docs/serial-console.md](../../docs/serial-console.md)). Details:
[docs/crs-testing.md](../../docs/crs-testing.md).

## Robot logs (audit / diagnostic / protocol run)

Chooser + definitions: [docs/robot-logs.md](../../docs/robot-logs.md).

- **Audit** (CRS on only): signed periods; who did what / who ran a protocol
- **Diagnostic**: usual support logs (HTTP access, errors, robot-server / CAN / ODD, …)
- **Protocol run**: command timeline for app/ODD run UI (may include source / RTP)

Do not confuse those with FTDI harness tees in `artifacts/serial/`.

## Post-install recovery (internal / Pyro builds)

After `put`, update-server may already show the new version while nginx `/health`
returns **502** for several minutes (firmware flash + robot-server Pyro startup).
That is often expected; see [RQA-5787](https://opentrons.atlassian.net/browse/RQA-5787).

1. Wait for `/health` 200, or SSH / serial and watch services / FW progress.
2. SSH (lab key, not committed), or FTDI serial when DHCP/network is down:

```bash
ssh -i ~/.ssh/robot_key -o IdentitiesOnly=yes root@$ROBOT_HOST

# Alternative: Flex FTDI console (docs/serial-console.md; close Tabby first)
uv run flex-test serial shell
uv run flex-test serial run "systemctl is-active opentrons-robot-server"
```

3. Ordered recovery if still broken after FW idle:

```text
opentrons-pyro-nameserver → opentrons-hardware-api → wait OT3API in NS → opentrons-robot-server
```

Full suite, SSH checks, restart failure modes, and live tip smoke:
`docs/pyro-testing.md`. Checklist YAML:
`docs/test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml`.

## Pyro / protocol-subprocess smoke

On internal builds with `enableHardwareSubprocess` / `enableProtocolSubprocess`
default on (`/data/feature_flags.json`):

- Prefer product HTTP (`/health`, `/instruments`, `/runs`, door status) over raw
  Pyro `Proxy` without the Opentrons Serpent type registry.
- Store protocol/run IDs as **bare UUIDs** only (never `PROTO_ID=<uuid>` in files
  you `cat` into JSON).
- Suites A–D: NS health, restart recovery (RQA-5789/5790), door, upload/analyze/create-run,
  uncurrent leak (RQA-5791), serialization (see `docs/pyro-testing.md`).
- On-robot Serpent registry over SSH: use writable `HOME` (e.g. `/tmp/ot-home`);
  `/root/.opentrons` is often read-only.
- Helper: `scripts/run_pyro_d_suite.sh` (needs recovery if orphan `ot-protocol` processes linger).

## Live protocol play (physical motion)

The harness has **no first-class motion capability**. Do **not** invent one or
play protocols unless the user **explicitly** asks for live motion / tip smoke.

When explicitly requested:

1. Confirm deck/instruments (tiprack position, clear deck, door closed, estop clear).
2. Use a documented protocol under `docs/test-suggestions/protocols/`.
3. Drive play via robot HTTP run actions (or future gated capability), not ad-hoc shell.
4. Prefer `return_tip` when no trash is loaded.

## Python entrypoints

```python
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.robots.flex import FlexRobot
from flex_testing_agent.capabilities.probe import probe_robot
from flex_testing_agent.capabilities.inspect import inspect_robot
```

Use `FlexRobot` as async context manager. Prefer capabilities over raw clients for multi-step work.

## Safety reminders

- Never enable access control
- Do not implement harness motion capabilities; live play only on explicit user request
- Default pytest excludes `requires_robot` / `mutates_robot`
- Live robot tests: `uv run pytest -m requires_robot`
- Service restarts and run mutations may need operator approval in agent sessions

## Artifacts

Evidence and photos land under `ARTIFACT_DIRECTORY` (default `./artifacts/`).
Local pyro notes often under `artifacts/pyro-tests/` (gitignored).

## Test suggestions (GitHub Pages)

Author YAML under `docs/test-suggestions/`. Preview with `make pages`. Pushing to `main` publishes https://opentrons.github.io/flex-testing-agent/.
