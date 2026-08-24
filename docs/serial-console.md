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
uv run flex-test serial watch --seconds 60   # capture kernel/boot console
uv run flex-test serial run "systemctl is-active opentrons-robot-server"
uv run flex-test serial run "uname -a" --include-kernel --save-log

# CRS-on QA: restore SSH/Jupyter/devtools without turning CRS off
# (docs/crs-testing.md). Close Tabby first. allow-* needs ALLOW_MUTATIONS.
uv run flex-test serial remote-access-status
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

Interactive exit: **Ctrl+]** then **q**. Menu: **Ctrl+T**.

## Session contract (assess the prompt)

The Flex serial console is also the kernel debug device. Unsolicited printk
will appear **while you are logging in** and **while commands run**. That is
not a harness bug.

On every connect, the harness:

1. Hits Enter and classifies the stream as `login` / `password` / `shell` /
   `unknown` (`probe_console_state`). Kernel lines often bury the prompt;
   it retries.
2. Auto-logs in as `root` when at `login:` (`ensure_logged_in`).
3. Runs scripted commands between echo markers. Command **output** drops
   printk lines; `kernel_lines` and the transcript keep them.

Do not treat interleaved kernel logs as a failed login. Do not invent
`screen` / `cu` / `minicom` one-offs. Prefer SSH when it is up
([interaction-layers.md](interaction-layers.md)).

## Kernel logging (expected and useful)

Per the
[Confluence FTDI guide](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex):
the serial console is also the **kernel debug device**. Unsolicited printk /
oops / boot lines mix with shell I/O (including during `vi` / `htop`). That is
not a harness bug.

| Situation | What to do |
|-----------|------------|
| Boot / power-on | `flex-test serial watch` (or `shell --no-login`) and read the scrollback |
| USB / driver events while working | Keep watching; printk will appear mid-session |
| Scripted `serial run` | Command body is printed without printk; full raw (incl. kernel) is saved |
| Keep evidence | Transcripts are **on by default** under `ARTIFACT_DIRECTORY/serial/` |

### Where logs go (default on)

Every `flex-test serial` command (except `list`) writes:

| File | Purpose |
|------|---------|
| `artifacts/serial/<UTC>-<kind>.log` | One file per operation (`run`, `shell`, `watch`, …) |
| `artifacts/serial/<YYYYMMDD>-console.log` | Append-only daily rollup for historical browsing |

Opt out with `--no-save-log`. Override the per-run path with `--log PATH`.
`artifacts/` is gitignored.

```bash
# Listen 60s (saves per-run + daily rollup)
uv run flex-test serial watch --seconds 60
uv run flex-test serial watch --kernel-only --seconds 30

# Run a command; transcript always saved (printk in file even if not printed)
uv run flex-test serial run "dmesg | tail -5"
uv run flex-test serial run "uname -a" --include-kernel

ls artifacts/serial/
```

Agents: treat kernel lines and saved transcripts as first-class evidence for boot
and hardware issues; do not strip them from saved files.

## For agents

| Do | Do not |
|----|--------|
| Prefer HTTPS/`flex-test inspect\|probe\|…` when the network is up; CRS-on API is HTTPS only | Invent ad-hoc `screen`/`cu`/`minicom` or `curl` |
| Prefer `flex-test ssh` for shell when port 22 authenticates | Open FTDI first while SSH works |
| Use `serial list` then `serial run` / `shell` / `watch` for boot, DHCP loss, first carveout, or SSH down | Discard kernel printk as “noise” when debugging boot/USB |
| Let `ensure_logged_in` classify the prompt; keep transcripts | Treat printk between `login:` and the shell as a bug |
| Use `serial allow-remote-access` only with `ALLOW_MUTATIONS` when CRS locked out SSH | Assume allow-remote-access **disables** CRS (it does not) |
| Prefer SSH `opentrons_disable_crs` (+ `{serial}-0000`) to exit CRS when SSH is up | Run `opentrons_disable_crs` from a protocol subprocess |
| Close competing serial apps if open fails busy | Encode EXEC-2176 wipe / motion as ad-hoc serial one-liners |
| Read this doc + Confluence before first cable plug | Guess header orientation |

Python API: `flex_testing_agent.serial_console`
(`resolve_serial_port`, `open_interactive_shell`, `SerialSession`, `run_command`,
`run_command_result`, `watch_console`, `partition_console_text`,
`probe_console_state`, `ensure_logged_in`,
`enable_remote_access`, `probe_remote_access`).

Lab SSH: `flex-test ssh` / `flex_testing_agent.lab_ssh`.

## Related

- [Interaction layers](interaction-layers.md)
- [Robot logs](robot-logs.md) (audit / diagnostic / protocol run; not the same as FTDI tees)
- [CRS testing](crs-testing.md) (enter/exit CRS, remote-access carveout, disable vs wipe, product model)
- [Pyro testing](pyro-testing.md) (SSH/serial when post-install `/health` is 502)
- [Safety model](safety-model.md)
- Skill: `.cursor/skills/operate-kansasflex/SKILL.md`
