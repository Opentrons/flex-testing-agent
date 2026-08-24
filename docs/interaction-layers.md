# Interaction layers (KansasFLEX)

**SSOT for how this harness talks to the robot.** Product CRS details stay in
[crs-testing.md](crs-testing.md). Serial hardware and printk stay in
[serial-console.md](serial-console.md). CRS-on bootstrap stays in
[crs-on-setup.md](crs-on-setup.md).

Agents: follow this ladder. Do not `curl` the robot. Do not open FTDI first
when HTTPS or SSH already works.

## Ladder

```text
1. Product HTTP(S)     flex-test inspect / probe / suites / put
2. Lab SSH (root)      flex-test ssh status|run   (shell only, not the API)
3. FTDI serial         flex-test serial …         (last resort)
```

| Need | Use | Do not |
|------|-----|--------|
| Health, CRS detect, versions, catalog, suites | `flex-test` HTTP(S) | Raw `curl` / ad-hoc URLs |
| CRS-on API (any verb, including GET) | **HTTPS** `:32313` after `crs trust-ca` | Plaintext `:31950` even if it still answers |
| Journal, systemd, Pyro on-robot, `opentrons_disable_crs` | **SSH** when port 22 + lab key work | Serial while SSH is up |
| First-time QA carveout (CRS on, SSH locked) | `flex-test serial allow-remote-access` | Assume carveout disables CRS |
| Boot, DHCP loss, kernel printk, no SSH | `flex-test serial` | Treat printk as a login failure |

`flex-test inspect` records API scheme, whether plaintext HTTP still answers
while CRS is on, and whether SSH is reachable. Start there.

## 1. Product HTTP(S)

CRS **off**: unauthenticated HTTP `:31950` is the lab default.

CRS **on**: discovery forces HTTPS `:32313`. The harness will not send
credentials or CRS-on API calls over HTTP. `flex-test crs lockdown` fails
`plaintext_http_*` if `:31950` still returns HTTP statuses.

KansasFLEX on `v10.0.0-alpha.4` still served the full API (including password
grant) on `:31950`. That is a **product leak**, not a harness transport.
Ticket: [RQA-5981](https://opentrons.atlassian.net/browse/RQA-5981) (Closed,
Won't Do: client-side HTTPS is considered enough). This harness still refuses
that path when CRS is on. Do not "helpfully" use HTTP because it works.

Discovery may **probe** HTTP `/health` only to find the host and learn CRS is
on, then upgrade. After that, all API work is HTTPS.

HTTPS CA: [crs-on-setup.md](crs-on-setup.md) (`flex-test crs trust-ca`).

## 2. Lab SSH (QA remote-access)

SSH/Jupyter/devtools are **unimpeded when CRS is off**. When CRS is on they
are **off** unless the allow sentinel exists:

- File: `/etc/opentrons-allow-remote-access`
- Unit: `opentrons-remote-access-allowed`

That carveout does **not** turn CRS off. It is cleared on the next OS `put`.
Policy: [crs-testing.md](crs-testing.md#crs-on-remote-access-carveout-qa).

```bash
uv run flex-test ssh status
uv run flex-test ssh run "systemctl is-active opentrons-robot-server"
uv run flex-test serial remote-access-status   # SSH first, serial if SSH fails
```

Identity defaults to `~/.ssh/robot_key` (`ROBOT_SSH_IDENTITY`). Not committed.

When CRS is on, **try SSH before serial**. If SSH works, use it for shell
work (including `opentrons_disable_crs`). First enable of the carveout still
needs serial because SSH is already locked out:

```bash
ALLOW_MUTATIONS=true uv run flex-test serial allow-remote-access
```

Redo after every robot OS update.

## 3. FTDI serial (last resort)

Use serial when SSH is down, the network is down, you need boot/kernel
output, or you must turn on the carveout for the first time.

On connect, the harness **assesses the prompt** (`login` / `password` /
`shell` / `unknown`) and auto-logs in as `root`. Kernel printk **will**
interleave with the shell. That is expected. Details:
[serial-console.md](serial-console.md).

Close Tabby first (exclusive port).

## Enter / exit CRS (shell)

| Goal | Path |
|------|------|
| Keep CRS on, restore SSH | Serial `allow-remote-access` once; then SSH |
| Turn CRS off | Root SSH (preferred) or serial: `opentrons_disable_crs` + `{serial}-0000` |
| Turn CRS off if disable binary fails | EXEC-2176 wipe (not this harness) |

Enable CRS only via `flex-test crs enable --confirm-one-way`.
