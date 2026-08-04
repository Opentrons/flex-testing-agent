# Pyro / protocol-subprocess testing on KansasFLEX

Operator and agent guide for validating **Pyro5** inter-process communication
(IPC) on Flex internal builds where hardware and protocol subprocesses are
enabled by default.

Published checklist form: [test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml](test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml)
(`make pages`). Spec background:
[Subprocess and Python-Remote Objects Specification](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5839652323/Subprocess+and+Python-Remote+Objects+Specification)
(PER). Epic for alpha.10 findings: [RQA-5786](https://opentrons.atlassian.net/browse/RQA-5786).

## When this applies

| Signal | Value |
|--------|--------|
| Channel | **internal** (`ot3@…` stack tags) |
| Example robot OS | `4.0.0-alpha.10` / `ot3@4.0.0-alpha.10` |
| Feature flags | `enableHardwareSubprocess=true`, `enableProtocolSubprocess=true` (default on since ~`ot3@4.0.0-alpha.7`) |
| Flag file | `/data/feature_flags.json` |

External customer builds (for example `v9.1.x`) are a different stack. Do not
assume Pyro subprocess mode there unless flags and systemd units prove it.

Install example:

```bash
# Confirm host first: DHCP can move KansasFLEX (seen 192.168.0.20 → .21)
uv run flex-test inspect
ALLOW_MUTATIONS=true uv run flex-test put 4.0.0-alpha.10 --channel internal
```

After put/reboot, update-server may report the new version while `/health` is
still nginx **502** for several minutes (firmware flash + robot-server Pyro
startup). Prefer waiting for `/health` 200, or SSH and check services (below).
See [RQA-5787](https://opentrons.atlassian.net/browse/RQA-5787).

## Process layout

```text
opentrons-pyro-nameserver     (Pyro5 NS, localhost:9090)
        ↑ register / resolve
   ┌────┴─────────┬──────────────────────┐
   │              │                      │
opentrons-    opentrons-           ot-protocol /
hardware-api  robot-server         ot-simulating-protocol
(OT3API PSO)  (HTTP +              (run / analysis
               robot-server-        DirectedRunProcess)
               resource)
```

Well-known nameserver entries:

| Name | Owner |
|------|--------|
| `OT3API` | `opentrons-hardware-api` (`pyro_process_entry`) |
| `robot-server-resource` | robot-server |
| `ot-protocol` | current run process (when current) |
| `ot-simulating-protocol` | analysis / simulating companion (when present) |

Monorepo pointers (research clone `upstream/opentrons`, tag `ot3@4.0.0-alpha.10`):

- Hardware entry: `api/src/opentrons/hardware_control/pyro_utils/pyro_process_entry.py`
- Adapters: `api/src/opentrons/util/pyro/`
- Run process: `robot-server/robot_server/runs/run_process*.py`

## SSH and on-robot checks

KansasFLEX SSH (lab key, not committed):

```bash
ssh -i ~/.ssh/robot_key -o IdentitiesOnly=yes root@$ROBOT_HOST
```

Useful commands:

```bash
systemctl is-active opentrons-pyro-nameserver opentrons-hardware-api opentrons-robot-server
systemctl status opentrons-hardware-api opentrons-robot-server --no-pager -l | head -80
cat /data/feature_flags.json | python3 -m json.tool | head -40

python3 - <<'PY'
import Pyro5.api as pyro
with pyro.locate_ns() as ns:
    for name, uri in sorted(ns.list().items()):
        print(name, uri)
PY

# Cheap OT3API call (no Serpent specialty types)
python3 - <<'PY'
import Pyro5.api as pyro
p = pyro.Proxy(pyro.resolve("PYRONAME:OT3API"))
print(p.get_fw_version())
PY

ps -ef | grep run_process_entry_point | grep -v grep
journalctl -u opentrons-robot-server -n 80 --no-pager
journalctl -u opentrons-hardware-api -n 40 --no-pager
```

Notes:

- Prefer `PYTHONPATH=/opt/opentrons-robot-server` if importing `opentrons.*` on-robot.
- Ad-hoc `Proxy(OT3API)` **without** the Opentrons Serpent type registry often fails on
  specialty types (`NonBuiltinKeyDictWrapper`, `DoorState`, `StateSummary`). That is
  expected for raw clients. Product paths go through robot-server HTTP (registry applied).
- Writing under `/root/.opentrons` may hit read-only FS when registering types from SSH.

## Suite map (A–D)

Run in this order. Record results in the YAML under `docs/test-suggestions/`.

### Results rollup (KansasFLEX, 2026-07-31 → 2026-08-03, `ot3@4.0.0-alpha.10`)

| ID | Result | Notes |
|----|--------|-------|
| A1 | **PASS** | nameserver, hardware-api, robot-server active+enabled |
| A2 | **PASS** | `OT3API` in NS ~0.05s; `get_fw_version` → `72` |
| A3 | **PASS** | `/health` 200; instruments/subsystems via HW proxy |
| A4 | **FAIL** | [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789) NS restart, no re-register |
| A5 | **FAIL** | [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790) HW restart, stale RS proxy |
| B1 | **PASS** | `/instruments` + `/subsystems/status` healthy |
| B2 | **SKIP** | no modules attached |
| B3 | **PASS** | two door open/close cycles on `/robot/door/status`; HW logs matched |
| C1 | **PASS** | create run → `ot-protocol` in NS + `run_process_entry_point` |
| C2 | **PASS** | upload + analysis `completed` / `result=ok` |
| C3a | **PASS** | idle pause → 409 (expected); idle stop → 201/`stopped`; `cancel` not a valid `actionType` |
| C3b | **PASS** | live tip smoke play succeeded (home, loadLabware, loadPipette, pickUpTip, dropTip) |
| C6 | **FAIL** | [RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791) uncurrent clears NS name, processes remain |
| D1 | **PASS** | door HTTP `closed` |
| D2 | **PASS** | `DoorState.CLOSED` via Proxy after `register_hardware_types()` (`HOME=/tmp/…`) |
| D3 | **PASS** | `attached_instruments` → `Mount` keys + pipette dicts with registry |
| D4 | **PASS** | `/runs/{id}/currentState` keys (`tipStates`, `estopEngaged`, …) |
| D4b | **FAIL** | [RQA-5797](https://opentrons.atlassian.net/browse/RQA-5797) legacy StateSummary load |
| D5a | **PASS** | idle run commands list OK (empty); analysis command slices OK |
| D5b | **FAIL** | [RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796) succeeded tip smoke `/commands` empty |
| D6 | **PASS** | invalid mount → HTTP `InvalidRequest` / `4000` |
| D7 | **PASS** | `/subsystems/status` 6 subsystems `ok=true` (RQA-5788 not reproducing now) |
| D8 | **PASS** | raw Proxy: `SerializeError` on `DoorState` / `NonBuiltinKeyDictWrapper` (expected) |

Passing (A–D): **A1–A3, B1, B3, C1–C3b, D1–D4, D5a, D6–D8** (18). Skipped: B2. Failed: A4, A5, C6, D4b, D5b.

### A. Process / service health

| ID | Intent | Validated 2026-07-31 |
|----|--------|----------------------|
| A1 | Three systemd units active | **PASS** |
| A2 | `OT3API` in nameserver quickly | **PASS** |
| A3 | `/health` OK with HW proxy usable | **PASS** |
| A4 | Restart **nameserver alone** → re-register or fail clearly | **FAIL** [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789) |
| A5 | Restart **hardware-api** → robot-server reattaches | **FAIL** [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790) |

A4 observation: NS comes back empty of app names; services stay active; `/health`
can stay 200 on stale sockets. Recovery: restart hardware-api then robot-server
(or full ordered restart: nameserver → hardware-api → robot-server).

A5 observation: new `OT3API` URI registers; robot-server keeps old proxy → HTTP 500
`CommunicationError` until robot-server restart.

### B. Hardware IPC (lower line)

| ID | Intent | Validated 2026-07-31 |
|----|--------|----------------------|
| B1 | Instruments + subsystems via HTTP | **PASS** |
| B2 | Modules / nested proxies | **SKIP** (no modules attached) |
| B3 | Door open/close via `/robot/door/status` | **PASS** (two cycles; HW `DoorSwitchStateInfo` matched) |

Door lives on `/robot/door/status`, not `/runs/{id}/currentState`.

### C. Protocol subprocess (upper line)

| ID | Intent | Validated 2026-07-31 |
|----|--------|----------------------|
| C1 | Create current run → `ot-protocol` in NS + process | **PASS** |
| C2 | Upload + analyze Python protocol | **PASS** |
| C3a | Idle run actions (pause/stop/cancel contract) | **PASS** (pause 409; stop 201; cancel invalid) |
| C3b | Live tip smoke play across process boundary | **PASS** (run succeeded; tiprack A1, right P50) |
| C6 | Uncurrent tears down process | **FAIL** [RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791): NS name cleared, `run_process_entry_point` processes remain |

Sample no-motion protocol (analysis only) and live tip smoke protocol:
[protocols/](test-suggestions/protocols/).

### D. Serialization (high bug density)

Concrete cases (product path = robot-server HTTP or on-robot Proxy **after**
`register_hardware_types()` / robot-server registry). Raw Proxy without registry
is a negative control only.

| ID | Intent | Validated 2026-07-31 |
|----|--------|----------------------|
| D1 | Door enum via HTTP `/robot/door/status` | **PASS** (`closed`) |
| D2 | DoorState via on-robot OT3API Proxy **with** hardware type registry | **PASS** (`DoorState.CLOSED`) |
| D3 | `attached_instruments` / NonBuiltinKeyDictWrapper with registry | **PASS** (LEFT/RIGHT Mount → pipette dicts) |
| D4 | Run `currentState` / StateSummary-shaped payload via HTTP | **PASS** |
| D4b | Legacy persisted StateSummary still loads | **FAIL** [RQA-5797](https://opentrons.atlassian.net/browse/RQA-5797) |
| D5a | Analysis / idle-run command slices via HTTP | **PASS** (analysis has `home`/`comment`) |
| D5b | Succeeded tip-smoke run command history via HTTP | **FAIL** [RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796) `totalLength=0` |
| D6 | Invalid request / error surface via HTTP | **PASS** (`InvalidRequest` on bad mount) |
| D7 | `/subsystems/status` healthy now (RQA-5788 regression check) | **PASS** (6 subsystems ok) |
| D8 | Negative: raw Proxy without registry fails specialty types | **PASS** (expected SerializeError) |

On-robot registry tip: `import opentrons…` as root needs a writable home
(`HOME=/tmp/ot-home` or similar). `/root/.opentrons` is often read-only over SSH.

Also watch journals for `unhashable type: 'dict'` / `numpy.float64`
([RQA-5788](https://opentrons.atlassian.net/browse/RQA-5788),
[RQA-5582](https://opentrons.atlassian.net/browse/RQA-5582)). Full pipette FW
reflash for the numpy path is optional / destructive; skip unless operator
requests. Helper script: `scripts/run_pyro_d_suite.sh`.

## Live tip smoke (physical motion)

Requires **explicit operator request** and clear deck setup. Play homes the robot.

Validated setup on KansasFLEX (2026-07-31):

- Right: `p50_single_flex`
- Left: `p50_multi_flex` (unused)
- Deck: `opentrons_flex_96_filtertiprack_50ul` in **A1**, rest clear
- Door closed, estop disengaged
- Protocol: [protocols/pyro_live_p50_tip_smoke.py](test-suggestions/protocols/pyro_live_p50_tip_smoke.py)
- Result: run `1c4e5cce-…` `succeeded` (summary shows pipette + tiprack A1). Note:
  `GET /runs/{id}/commands` later returned empty ([RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796));
  treat live observation during play as the C3b pass evidence, not post-hoc command listing.

HTTP sketch:

```bash
# After upload+analysis completed:
RUN_ID=…   # bare UUID only
curl -sS -H 'Opentrons-Version: *' -H 'Content-Type: application/json' \
  -d "{\"data\":{\"protocolId\":\"$PROTO_ID\"}}" \
  http://$ROBOT_HOST:31950/runs
curl -sS -H 'Opentrons-Version: *' -H 'Content-Type: application/json' \
  -d '{"data":{"actionType":"play"}}' \
  http://$ROBOT_HOST:31950/runs/$RUN_ID/actions
```

Pitfall: never write id files as `PROTO_ID=<uuid>` then `cat` them back into JSON.
Store **bare UUIDs** only (`printf '%s' "$PROTO_ID" > file`). A `PROTO_ID=` prefix
caused create-run `ProtocolNotFound` and play `404` (false “did not play”).

Prefer `return_tip` / tiprack return when no trash bin is loaded.

## Post-install recovery cheat sheet

If `/health` is 502 but update-server shows the new version:

1. SSH: confirm nameserver + hardware-api + robot-server active.
2. Confirm `OT3API` in NS; watch hardware-api for firmware `Update: … %`.
3. After FW idle: `systemctl restart opentrons-robot-server`.
4. If still broken: restart in order  
   `opentrons-pyro-nameserver` → `opentrons-hardware-api` → wait for `OT3API` →  
   `opentrons-robot-server`.

## Bugs filed from KansasFLEX alpha.10 (under RQA-5786)

| Key | Summary |
|-----|---------|
| [RQA-5787](https://opentrons.atlassian.net/browse/RQA-5787) | robot-server startup / nginx 502 after update during HW firmware flash |
| [RQA-5788](https://opentrons.atlassian.net/browse/RQA-5788) | `unhashable type: 'dict'` on subsystem updates via OT3API proxy |
| [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789) | After nameserver restart, app names never re-register |
| [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790) | robot-server does not reattach after hardware-api restart |
| [RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791) | Uncurrent clears NS `ot-protocol` but leaves processes running |
| [RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796) | Succeeded runs return empty `/runs/{id}/commands` (`totalLength=0`) |
| [RQA-5797](https://opentrons.atlassian.net/browse/RQA-5797) | Legacy StateSummary missing `cameraSettings.errorRecoveryCameraEnabled` |

Related prior: [RQA-5582](https://opentrons.atlassian.net/browse/RQA-5582) (numpy float64 pyro), [EXEC-2187](https://opentrons.atlassian.net/browse/EXEC-2187).

## Harness gaps (future work)

The harness does not yet expose first-class Pyro capabilities (NS list, service
status, run upload/play). Operators currently combine `flex-test` inspect/probe/put
with SSH and HTTP. Natural extensions (follow `clients/ → capabilities/ → CLI`):

- Read-only “pyro status” capability (SSH optional or HTTP-only health correlation)
- Protocol upload / analysis / run / play gated capabilities for operator smoke
- Post-install waiter that treats long 502 + FW flash as expected, not only success/fail

## References

- Spec: Confluence PER Pyro / subprocess pages (link above)
- Versions: [robot-versions.md](robot-versions.md)
- Safety: [safety-model.md](safety-model.md)
- Operate skill: `.cursor/skills/operate-kansasflex/SKILL.md`
