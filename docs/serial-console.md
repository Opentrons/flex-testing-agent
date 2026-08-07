# Flex FTDI serial console

**SSOT for this harness.** Hardware photos and cable orientation live in Confluence;
this page covers KansasFLEX lab setup and how humans/agents use `flex-test serial`
instead of [Tabby](https://tabby.sh/).

**Hardware guide (required reading once):**
[Using an FTDI cable to access a Flex](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex)
(RPDO / Confluence).

## What you get

Root Linux shell on the Flex **without network**, plus bootloader/kernel logs from
power-on. Same class of access as lab SSH. Not gated by `ALLOW_MUTATIONS`.

| Default | Value |
|---------|--------|
| Baud | `115200` |
| Login | `root` (no password on typical lab images) |
| Port | auto-detect FTDI / `usbserial` (prefer `/dev/cu.*` on macOS) |
| Cable | 5V FTDI USB/serial (e.g. Digi-Key TTL-232R-5V) |

## Hardware setup (once)

Do this with the Flex **powered off**. Details and photos: Confluence link above.

1. Remove the display-module back panel (4× M2.5 bolts).
2. Find the 5-pin serial header (bottom-left of the display board; remove rubber keeper if present).
3. Plug FTDI USB into the laptop; header end into the Flex with **black wire / GND on the left** (aligned with board `GND`). No exposed pins beside the connector.
4. Power the Flex on. Boot text scrolls on the console; wait for `… login:`.

Mis-wiring can damage the SOM. Prefer Confluence photos over memory.

## Software setup (this repo)

```bash
uv sync --all-extras
# optional in .env:
# SERIAL_PORT=/dev/cu.usbserial-…
# SERIAL_BAUD_RATE=115200
```

**Only one program may hold the port.** Close Tabby (or any other serial app) before
`flex-test serial`, or you will see `Resource busy` / errno 16.

## Commands

```bash
uv run flex-test serial list          # confirm FTDI shows as “likely Flex FTDI”
uv run flex-test serial shell         # interactive (Tabby replace); auto-login as root
uv run flex-test serial shell --no-login
uv run flex-test serial run "systemctl is-active opentrons-robot-server"

# CRS-on QA: restore SSH/Jupyter/devtools without turning CRS off
# (docs/crs-testing.md). Close Tabby first. allow-* needs ALLOW_MUTATIONS.
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

Interactive exit: **Ctrl+]** then **q**. Menu: **Ctrl+T**.

Kernel printk lines may interleave with typing and `run` output; that is expected.

## For agents

| Do | Do not |
|----|--------|
| Prefer HTTP / `flex-test inspect\|probe\|…` when the network is up | Invent ad-hoc `screen`/`cu`/`minicom` one-offs |
| Use `serial list` then `serial run` / `serial shell` for boot, DHCP loss, or SSH unreachable | Assume allow-remote-access **disables** CRS (it does not) |
| Use `serial allow-remote-access` only with `ALLOW_MUTATIONS` when CRS locked out SSH | Encode EXEC-2176 wipe / motion as ad-hoc serial one-liners |
| Close competing serial apps if open fails busy | Assume plain `serial shell` is gated by `ALLOW_MUTATIONS` (only mutating carveouts are) |
| Read this doc + Confluence before first cable plug | Guess header orientation |

Python API: `flex_testing_agent.serial_console`
(`resolve_serial_port`, `open_interactive_shell`, `SerialSession`, `run_command`,
`enable_remote_access`, `probe_remote_access`).

## Related

- [CRS testing](crs-testing.md) (remote-access carveout + EXEC-2176 distinction)
- [Pyro testing](pyro-testing.md) (SSH/serial when post-install `/health` is 502)
- [Safety model](safety-model.md)
- Skill: `.cursor/skills/operate-kansasflex/SKILL.md`
