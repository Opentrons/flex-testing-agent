---
name: operate-kansasflex
description: >-
  Operates the local Opentrons Flex KansasFLEX through flex-testing-agent CLI
  and Python APIs only (never curl/ad-hoc robot HTTP). Use when inspecting
  robot state, status (instruments/door/subsystems), waiting for health after
  install, probing read-only endpoints, taking camera pictures, listing Flex
  OS releases, installing a robot OS build with ALLOW_MUTATIONS, running Pyro
  / protocol-subprocess validation, using the FTDI serial console
  (`flex-test serial`) instead of Tabby, or archiving/reviewing diagnostic
  robot logs after seed-runs / api-suite (`flex-test logs archive`).
---

# Operate KansasFLEX

## Hard rule: no ad-hoc robot HTTP

**Do not** `curl`, `wget`, or raw `httpx` against `ROBOT_HOST` / robot ports.
**Do not** invent robot URLs in agent glue.

Use only:

1. `uv run flex-test …` CLI, or
2. Typed clients / capabilities via `FlexRobot` (`clients/` → `capabilities/`)

If a needed call is missing, **extend the harness** (skill
`extend-flex-harness`) instead of shelling out.

| Need | Use |
|------|-----|
| Reachability / versions / CRS detect | `flex-test inspect` |
| Instruments, door, subsystems | `flex-test status` |
| Post-install / reboot wait for `/health` | `flex-test wait-health` |
| Broad read-only GETs + optional picture | `flex-test probe` |
| Run presence | `flex-test run-state` |
| OS install | `flex-test put …` |
| Logs | `flex-test logs list\|archive` |
| CRS audit periods | `flex-test audit list\|download` |
| Boot / DHCP / SSH down | `flex-test serial …` (not HTTP) |

## Prerequisites

- `.env` with `ROBOT_HOST` (and usually `ROBOT_NAME=KansasFLEX`)
- Optional `ROBOT_HOST_CANDIDATES=192.168.0.21,192.168.0.20` (defaults in settings)
- `uv sync --all-extras`
- Mutations only when `.env` has `ALLOW_MUTATIONS=true`
- CLI/runners **probe candidates** via `GET /health` and bind the live host
  (DHCP has moved KansasFLEX between `.20` and `.21`)
- CRS on: set `ROBOT_USERNAME` / `ROBOT_PASSWORD` so mutating CLIs can OAuth

## Preferred commands

```bash
# Read-only snapshot (also confirms host reachability)
uv run flex-test inspect

# Compact instruments / door / subsystems (typed clients; OAuth if CRS on)
uv run flex-test status

# After put/reboot while nginx may still 502: poll until /health 200
uv run flex-test wait-health
uv run flex-test wait-health --timeout 1200 --interval 5

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

# After seed / api-suite / install verification: archive + review diagnostic logs
uv run flex-test logs list
uv run flex-test logs archive
# Then complete Post-suite log archive and review (below)

# Published Flex robot OS versions (CDN manifests)
uv run flex-test releases
uv run flex-test releases --channel internal

# Install OS build (mutates; needs ALLOW_MUTATIONS=true); records timing JSON
ALLOW_MUTATIONS=true uv run flex-test put 9.1.2-alpha.5 --channel external
# Current Pyro / protocol-subprocess line (external 10.0.0-alpha.* =
# former internal 4.0.0-alpha.*). Parent bug epic: RQA-5831.
ALLOW_MUTATIONS=true uv run flex-test put 10.0.0-alpha.0 --channel external
# When CRS (access control) is on, set ROBOT_USERNAME / ROBOT_PASSWORD so put
# can OAuth; otherwise update-server returns 401.

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

Enter / exit CRS (manual operator flow; harness never enables CRS):

- Password for enter CRS and for `opentrons_disable_crs`: `{robot_serial}-0000`
- Create `testadmin` / `testuser` yourself after enter CRS (no longer auto-created)
- Disable: root SSH or serial `opentrons_disable_crs` (not a protocol subprocess)

## Robot logs (audit / diagnostic / protocol run)

Chooser + definitions: [docs/robot-logs.md](../../docs/robot-logs.md).

- **Audit** (CRS on only): signed periods; who did what / who ran a protocol
- **Diagnostic**: usual support logs (HTTP access, errors, robot-server / CAN / ODD, …)
- **Protocol run**: command timeline for app/ODD run UI (may include source / RTP)

Do not confuse those with FTDI harness tees in `artifacts/serial/`.

```bash
uv run flex-test logs list
uv run flex-test logs archive
```

## Post-suite log archive and review

**Required** after live `seed-runs`, `api-suite`, or install verification (and
whenever the user asks to verify a build and file bugs on an RQA epic).

1. Archive diagnostic logs:

```bash
uv run flex-test logs archive
```

2. Optionally note recent FTDI transcript paths under `artifacts/serial/` in the
   review note. Do **not** treat harness FTDI tees as robot `serial.log`.
3. Scan archived files for investigate signals:
   - `ERROR`, `CRITICAL`, `Traceback`, `Exception`
   - `Application startup failed`, `CommunicationError`
   - Clustered nginx 502 / 5xx after `/health` has recovered
   - Unexpected Pyro / `hardware-api` activity when
     `enableHardwareSubprocess` / `enableProtocolSubprocess` are false
4. Write `review.md` in the archive directory: clean vs suspects, file paths,
   timestamps, robot version / host.
5. If clear product defects and the user named a parent epic (for example
   RQA-5819): create RQA **Bugs** with `parent` set to that epic. Otherwise
   summarize in chat and/or an epic comment. Do not open noise bugs for expected
   post-reboot 502 while firmware flashes.
6. **Always attach log evidence to every bug filed from this review** (required):
   1. Build a focused pack under the archive:
      `evidence-<ISSUE_KEY>/` with the relevant excerpts (not necessarily the
      full multi-MB `serial.log` / `can_bus.log`), plus `review.md` and
      `manifest.json`, and zip it as `evidence-<ISSUE_KEY>.zip`.
   2. Put that evidence on the Jira issue **before** considering the bug done:
      - Prefer native Jira **file attachments** when available (UI upload or
        REST with `JIRA_API_TOKEN` / email basic auth).
      - If binary attach is unavailable (Atlassian MCP has no attachment API),
        paste the focused excerpts into an issue **comment** (full traceback +
        occurrence index) and note the local pack path / zip in that comment.
   3. Never leave a log-review bug with only a summary and no log excerpts on
      the ticket.

## Post-install recovery (Pyro / 10.0.0-alpha.* builds)

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

3. If still broken after FW idle: **full robot reboot** (power cycle or `reboot`),
   then wait for `/health` 200 again. Do **not** prescribe ordered
   `systemctl restart` of nameserver / hardware-api / robot-server as the
   operator recovery path (those gaps are Low / expected: RQA-5789 / RQA-5790).

Full validation narrative: `docs/pyro-testing.md`. Checklist YAML:
`docs/test-suggestions/10.0.0-alpha.0-pyro-subprocess.yaml`.
Bug epic for `10.0.0-alpha.1`: [RQA-5847](https://opentrons.atlassian.net/browse/RQA-5847)
(alpha.0: [RQA-5831](https://opentrons.atlassian.net/browse/RQA-5831)).
Triage / priority:
[RBARM 10.0.0-alpha.1 triaging](https://opentrons.atlassian.net/wiki/spaces/RBARM/pages/6405062721).

### Filing bugs

- Parent under RQA-5847 for alpha.1 (or the epic the user names).
- **Do not file duplicates.** Search the triage page + open RQA bugs first; if a
  match exists, **comment with evidence** on that ticket instead.
- Write for **product developers**, not harness maintainers:
  - Reproduction steps as **HTTP API calls** (method, path, headers, body).
  - Paste **real response bodies** and relevant **server log excerpts** (journal,
    robot-server, audit-server).
  - Include **robot build**, CRS/access-control state, and robot serial when known.
  - **Attach** protocol files, request payloads, and sample responses (Jira
    attachments or inline in the description/comment when upload is unavailable).
  - PR links are fine for **context**; do not rely on them as the repro.
- Avoid harness-only vocab in Jira (`A4`/`C6`, `flex-test`, `api-suite`, CRS suite
  letters, artifact paths under `artifacts/`).
- Mention **full robot reboot** as recovery / workaround when relevant.

## Pyro / protocol-subprocess smoke

On external `10.0.0-alpha.*` (and historical internal `4.0.0-alpha.*`) builds with
`enableHardwareSubprocess` / `enableProtocolSubprocess` default on
(`/data/feature_flags.json`):

- Prefer product HTTP (`/health`, `/instruments`, `/runs`, door status) over raw
  Pyro `Proxy` without the Opentrons Serpent type registry.
- Store protocol/run IDs as **bare UUIDs** only (never `PROTO_ID=<uuid>` in files
  you `cat` into JSON).
- Default checks: NS health, door, upload/analyze/create-run, uncurrent leak
  (RQA-5791), serialization. **Skip** nameserver/hardware-api service-restart
  experiments unless regressing a fix (see `docs/pyro-testing.md`).
- On-robot Serpent registry over SSH: use writable `HOME` (e.g. `/tmp/ot-home`);
  `/root/.opentrons` is often read-only.
- Helper: `scripts/run_pyro_d_suite.sh` (full reboot if orphan processes linger).

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
