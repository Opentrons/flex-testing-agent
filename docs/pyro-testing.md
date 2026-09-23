# Pyro / protocol-subprocess testing on KansasFLEX

Operator and agent guide for validating **Pyro5** inter-process communication
(IPC) on Flex builds where hardware and protocol subprocesses are enabled by
default.

Published checklist form:
[test-suggestions/10.0.0-alpha.0-pyro-subprocess.yaml](test-suggestions/10.0.0-alpha.0-pyro-subprocess.yaml)
(`make pages`). Release-delta plans:
[test-suggestions/10.0.0-alpha.1-release-delta.yaml](test-suggestions/10.0.0-alpha.1-release-delta.yaml)
(fixes on `chore_release-10.0.0` since `v10.0.0-alpha.0`),
[test-suggestions/10.0.0-alpha.4-release-delta.yaml](test-suggestions/10.0.0-alpha.4-release-delta.yaml)
(three PRs since `v10.0.0-alpha.3`, including RQA-5913 livedata). Historical checklist
from the internal line:
[test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml](test-suggestions/4.0.0-alpha.10-pyro-subprocess.yaml).
Spec background:
[Subprocess and Python-Remote Objects Specification](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5839652323/Subprocess+and+Python-Remote+Objects+Specification)
(PER).

Bug epic for `10.0.0-alpha.0`: [RQA-5831](https://opentrons.atlassian.net/browse/RQA-5831).
Bug epic for `10.0.0-alpha.1`: [RQA-5847](https://opentrons.atlassian.net/browse/RQA-5847)
(both under initiative [RQA-5484](https://opentrons.atlassian.net/browse/RQA-5484)).
Triage / priority SSOT (Pyro-centered):
[10.0.0-alpha.1 triaging/organizing tickets](https://opentrons.atlassian.net/wiki/spaces/RBARM/pages/6405062721/10.0.0-alpha.0+triaging+organizing+tickets)
(RBARM). Earlier internal-line findings: [RQA-5786](https://opentrons.atlassian.net/browse/RQA-5786).

### Filing / retest rule

Before opening a new RQA Bug under RQA-5847 (or any 10.0.0 epic): search open
tickets on the triage page and related epics (`RQA-5831`, `RQA-5786`, Runs /
Hardware / Graceful shutdown buckets). If a match exists, **comment with
evidence** on that ticket (and link related keys). File a new Bug only when
there is no existing match.

## When this applies

| Signal | Value |
|--------|--------|
| Channel | **external** (`v10.0.0-alpha.N` stack tags) |
| Example robot OS | `10.0.0-alpha.4` / `v10.0.0-alpha.4` (prior: `10.0.0-alpha.1`, `10.0.0-alpha.0`) |
| Feature flags | `enableHardwareSubprocess=true`, `enableProtocolSubprocess=true` |
| Flag file | `/data/feature_flags.json` |

### Version line rename (important)

The Pyro / protocol-subprocess Flex OS line that used to ship as **internal**
`4.0.0-alpha.N` / `ot3@4.0.0-alpha.N` is the **same product line** now published
on the **external** channel as `10.0.0-alpha.N` / `v10.0.0-alpha.N`.

| Former (internal) | Current (external) |
|-------------------|--------------------|
| `4.0.0-alpha.N` | `10.0.0-alpha.N` |
| `ot3@4.0.0-alpha.N` | `v10.0.0-alpha.N` |
| `--channel internal` | `--channel external` |

Do not assume older customer `v9.1.x` builds have Pyro subprocess mode unless
flags and systemd units prove it. See [robot-versions.md](robot-versions.md).

Install example:

```bash
# Confirm host first: DHCP can move KansasFLEX (seen 192.168.0.20 → .21)
uv run flex-test inspect
ALLOW_MUTATIONS=true uv run flex-test put 10.0.0-alpha.1 --channel external
```

After put/reboot, update-server may report the new version while `/health` is
still nginx **502** for several minutes (firmware flash + robot-server Pyro
startup). Prefer waiting for `/health` 200, or SSH/serial and check services
(below). See [RQA-5787](https://opentrons.atlassian.net/browse/RQA-5787).

## Process layout

CRS is why this split exists. The stack used to be a **single process** under
`opentrons-robot-server`. Compliance mode needs protocol execution independent
of HTTP, so the default OS line is three processes talking over **Pyro5**:

### Pre-loaded protocol workers (expected)

Robot-server keeps **at least two** `run_process_entry_point` workers warm after
boot even when **no run is current**:

| Pool role | Typical Pyro name prefix | Why |
|-----------|-------------------------|-----|
| Analysis / simulating | `ot-simulating-protocol_*` | Protocol analysis without cold-start |
| Runs | `ot-protocol_*` | `POST /runs` without 20s+ Python import stall |

This is **intentional**: separate process init is dominated by Python imports.
QA harnesses must not treat `ps=2` with `run_count=0` as a leak ([RQA-6020](https://opentrons.atlassian.net/browse/RQA-6020) closed as expected behavior).

NS registration may lag a few tens of seconds after boot; T+0 snapshots can
show ps lines before names appear in the Pyro nameserver.

**After uncurrent ([RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791) closed):**
pool size should settle back to **2** workers within ~30s. The runs-pool worker
may keep a **new** `ot-protocol_*` pyroname (not the boot-time name); that is
expected warm-pool reuse, not a leak. **Fail** only if `ps` count stays above 2.

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

| Process | Role | Runs as |
|---------|------|---------|
| `opentrons-hardware-api` | Pipettes, modules, door, motion (`OT3API` PSO) | root |
| `opentrons-robot-server` | HTTP API, run setup, general interaction | root |
| `ot-protocol` executor | Orchestrator + protocol engine for a live run | `ot-protocol` user (limited r/w) |

Each service exposes a `PyroSynchronousObject`; callers use an
`AsyncClientPyroObject` proxy. Objects that cross the process boundary must be
serializable (enums/Pydantic in a registered package; dataclasses need
`to_pyro_dict` / `from_pyro_dict`). Full product model:
[crs-testing.md](crs-testing.md#protocol-subprocess-why-pyro-exists).

Well-known nameserver entries:

| Name | Owner |
|------|--------|
| `OT3API` | `opentrons-hardware-api` (`pyro_process_entry`) |
| `robot-server-resource` | robot-server |
| `ot-protocol` / `ot-protocol_<uuid>` | current run process (when current; UUID suffix seen on `v10.0.0-alpha.0`) |
| `ot-simulating-protocol` / `ot-simulating-protocol_<uuid>` | analysis / simulating companion (when present) |

On CRS-on robots, uncurrenting a run may return **409 `RunSignoffRequired`**
until the run is signed off. That is access-control behavior, not a Pyro IPC
failure. Prefer CRS-off (or a signed-off run) when validating process teardown
([RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791)).

If the operator **explicitly** asks to play a protocol while CRS is on: App/ODD
**Pause** prompts for documentation and does not pause until the note is
submitted. That is expected. Open the door (or E-Stop in an emergency). Do not
file it as a Pyro or run-control bug. See
[crs-testing.md](crs-testing.md#documentation-required-reason-for-interaction).

Monorepo pointers (research clone `upstream/opentrons`, tag `v10.0.0-alpha.0`
or matching `ot3@` archaeology tag):

- Hardware entry: `api/src/opentrons/hardware_control/pyro_utils/pyro_process_entry.py`
- Adapters: `api/src/opentrons/util/pyro/`
- Run process: `robot-server/robot_server/runs/run_process*.py`

## SSH and on-robot checks

Prefer [interaction-layers.md](interaction-layers.md): product HTTP(S) first,
then lab SSH, then FTDI serial.

```bash
uv run flex-test ssh status
uv run flex-test ssh run "systemctl is-active opentrons-robot-server"
```

Identity defaults to `~/.ssh/robot_key` (`ROBOT_SSH_IDENTITY`). When the
network is down or you need boot/kernel output, use the FTDI serial console
instead of Tabby (close Tabby first; port is exclusive):

```bash
uv run flex-test serial list
uv run flex-test serial shell
uv run flex-test serial run "systemctl is-active opentrons-robot-server"
```

Harness + agent setup: [serial-console.md](serial-console.md).
Hardware photos / orientation:
[Confluence FTDI guide](https://opentrons.atlassian.net/wiki/spaces/RPDO/pages/5663293442/Using+an+FTDI+cable+to+access+a+Flex).

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

## Recovery: full robot reboot (preferred)

When the robot is unhealthy after an OS update, IPC glitch, or HTTP 5xx that
persists past firmware flash, **prefer a full robot reboot** (power cycle or
`reboot` from root SSH / serial). Then wait for `GET /health` → 200.

Do **not** treat ordered `systemctl restart` of
`opentrons-pyro-nameserver` / `opentrons-hardware-api` / `opentrons-robot-server`
as the default recovery path in operator notes or RQA bugs.

### Why we still prefer reboot over service restart

Partial service restarts were useful for **forcing** IPC failure modes during
early validation. [oe-core#373](https://github.com/Opentrons/oe-core/pull/373)
(`PartOf=` on the three pyro units, verified Closed on KansasFLEX
`v10.0.0-alpha.3`) now restarts nameserver, hardware-api, and robot-server as a
group, which fixed [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789)
and [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790).

Full reboot is still what operators and support should do. Do not prescribe
ordered `systemctl restart` as the recovery path in RQA bugs. Optional
regression of the grouped-restart behavior is fine; do not block
`10.0.0-alpha.*` validation on it.

### Post-install wait (before declaring broken)

If `/health` is 502/500 but update-server shows the new version:

`flex-test put` treats matching `GET /server/update/health` `systemVersion` as
OS install success (`boot.health`) even while robot-server `/health` is still
failing (common: `DatabaseFailedToInitialize` / device busy during FW flash).

1. Wait several minutes for firmware flash + robot-server attach.
2. SSH/serial: confirm nameserver + hardware-api + robot-server active; `OT3API`
   present in the nameserver.
3. If still broken after FW idle: **full robot reboot**, then wait for `/health`
   200 again.

## Filing RQA bugs (developers are the audience)

Parent new findings under [RQA-5831](https://opentrons.atlassian.net/browse/RQA-5831)
unless another epic is named.

Write bugs in **general product language**:

| Do | Do not |
|----|--------|
| HTTP paths (`GET /health`, `GET /runs/{id}/commands`) | Harness suite IDs (`A4`, `C6`, `D5b`) |
| ODD / App / robot OS symptoms operators see | `flex-test probe`, `api-suite`, CRS-off A/B/C |
| systemd unit names if SSH evidence matters | Internal harness vocab (`seed-runs`, Tier B, …) |
| Robot serial, build (`v10.0.0-alpha.0`), timestamps | Assuming readers know this repo |
| **Full robot reboot** as recovery / workaround | “Restart nameserver then hardware-api then robot-server” as the prescribed fix |

Attach focused log evidence (see operate skill / [robot-logs.md](robot-logs.md)).

## Validation map (product checks)

Run these against KansasFLEX after install. Record results in the YAML under
`docs/test-suggestions/`. Letter IDs below are **harness bookkeeping only**;
do not paste them into Jira summaries.

### Historical rollup (KansasFLEX, 2026-07-31 → 2026-08-03, internal `ot3@4.0.0-alpha.10`)

Kept for archaeology. Re-run on `v10.0.0-alpha.0` and update the new YAML.

| ID | Result | Notes |
|----|--------|-------|
| A1 | **PASS** | nameserver, hardware-api, robot-server active+enabled |
| A2 | **PASS** | `OT3API` in NS ~0.05s; `get_fw_version` → `72` |
| A3 | **PASS** | `/health` 200; instruments/subsystems via HW proxy |
| A4 | **FAIL** (later Closed) | [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789) NS restart, no re-register |
| A5 | **FAIL** (later Closed) | [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790) HW restart, stale RS proxy |
| B1 | **PASS** | `/instruments` + `/subsystems/status` healthy |
| B2 | **SKIP** | no modules attached |
| B3 | **PASS** | two door open/close cycles on `/robot/door/status` |
| C1 | **PASS** | create run → `ot-protocol` in NS + `run_process_entry_point` |
| C2 | **PASS** | upload + analysis `completed` / `result=ok` |
| C3a | **PASS** | idle pause → 409; idle stop → 201/`stopped` |
| C3b | **PASS** | live tip smoke play succeeded |
| C6 | **PASS** (alpha.5 retest) | Uncurrent settles to 2 pre-loaded workers; runs pool may keep new `ot-protocol_*` name ([RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791) closed) |
| D1–D4, D5a, D6–D8 | **PASS** / expected negative | see historical YAML |
| D4b | **FAIL** | [RQA-5797](https://opentrons.atlassian.net/browse/RQA-5797) |
| D5b | **FAIL** (Closed) | [RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796) |

### A. Process / service health

| ID | Intent | Notes for 10.0.0-alpha.* |
|----|--------|---------------------------|
| A1 | Three systemd units active | Required each build |
| A2 | `OT3API` in nameserver quickly | Required |
| A3 | `/health` OK with HW proxy usable | Required |
| A4 | Restart **nameserver** | Optional regression: grouped `PartOf=` restart (RQA-5789 Closed) |
| A5 | Restart **hardware-api** | Optional regression: grouped `PartOf=` restart (RQA-5790 Closed) |

### B. Hardware IPC (lower line)

| ID | Intent |
|----|--------|
| B1 | Instruments + subsystems via HTTP |
| B2 | Modules / nested proxies (skip if no modules) |
| B3 | Door open/close via `/robot/door/status` |

### C. Protocol subprocess (upper line)

| ID | Intent |
|----|--------|
| C1 | Create current run → `ot-protocol` in NS + process |
| C2 | Upload + analyze Python protocol |
| C3a | Idle run actions (pause/stop contract) |
| C3b | Live tip smoke play (only with explicit operator request) |
| C6 | Uncurrent tears down process ([RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791)) |

Sample protocols: [protocols/](test-suggestions/protocols/).

### D. Serialization

Prefer robot-server HTTP (or on-robot Proxy after `register_hardware_types()`).
Raw Proxy without registry is a negative control only.

On-robot registry tip: use writable `HOME=/tmp/ot-home`. `/root/.opentrons` is
often read-only over SSH. Helper: `scripts/run_pyro_d_suite.sh`.

## Live tip smoke (physical motion)

Requires **explicit operator request** and clear deck setup. Play homes the robot.

Typical KansasFLEX setup:

- Right: `p50_single_flex`
- Deck: `opentrons_flex_96_filtertiprack_50ul` in **A1**, rest clear
- Door closed, estop disengaged
- Protocol: [protocols/pyro_live_p50_tip_smoke.py](test-suggestions/protocols/pyro_live_p50_tip_smoke.py)

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

Pitfall: store **bare UUIDs** only in id files. Prefer `return_tip` when no trash
bin is loaded.

## Bugs from the internal alpha.10 line (under RQA-5786)

Many are assigned; several Closed. Keep linking when regressing on `10.0.0-alpha.*`.

| Key | Summary | Notes |
|-----|---------|-------|
| [RQA-5787](https://opentrons.atlassian.net/browse/RQA-5787) | robot-server startup / nginx 502 after update during HW firmware flash | Highest; Casey |
| [RQA-5808](https://opentrons.atlassian.net/browse/RQA-5808) | `/health` 500 `DatabaseFailedToInitialize` (EBUSY) | Tamar |
| [RQA-5788](https://opentrons.atlassian.net/browse/RQA-5788) | `unhashable type: 'dict'` on subsystem updates | Closed |
| [RQA-5789](https://opentrons.atlassian.net/browse/RQA-5789) | After nameserver restart, app names never re-register | Closed on `v10.0.0-alpha.3` (oe-core#373 `PartOf=`) |
| [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790) | robot-server does not reattach after hardware-api restart | Closed on `v10.0.0-alpha.3` (oe-core#373 `PartOf=`) |
| [RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791) | Uncurrent + warm pool reuse (closed; not a leak) | Closed |
| [RQA-5796](https://opentrons.atlassian.net/browse/RQA-5796) | Succeeded runs return empty `/runs/{id}/commands` | Closed |
| [RQA-5797](https://opentrons.atlassian.net/browse/RQA-5797) | Legacy StateSummary missing camera field | Josh |

Related prior: [RQA-5582](https://opentrons.atlassian.net/browse/RQA-5582), [EXEC-2187](https://opentrons.atlassian.net/browse/EXEC-2187).

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
- CRS product model (why subprocess exists): [crs-testing.md](crs-testing.md)
- Operate skill: `.cursor/skills/operate-kansasflex/SKILL.md`
