# Known-state setup and latency benchmarks

Goal: put KansasFLEX into **repeatable known states** (software build, cleared
robot-server data, deck config, LPC/offsets, diverse run history) while
**timing** critical paths so we can compare builds with and without Pyro /
protocol-subprocess.

Agent and operators use the same CLI / capabilities one-off or inside suites.

## Why

Leftover runs, offsets, and deck config confound CRS probes, camera behavior
([RQA-5807](https://opentrons.atlassian.net/browse/RQA-5807)), and Pyro latency
work. We need:

1. A clean baseline on a chosen OS build
2. A seeded history that exercises real motion and attached hardware
3. Structured timings (JSON) comparable across builds

## Phases (ordered)

| Phase | Command / capability | Mutates | Notes |
|-------|----------------------|---------|-------|
| **0. Build** | `flex-test put <ver>` | INSTALLATION | Baseline: external `10.0.0-alpha.*` (Pyro line; formerly internal `4.0.0-alpha.*`). Older customer `9.1.2-alpha.*` still useful for non-Pyro compare. |
| **1. Clear robot-server data** | `flex-test reset-data` | DISRUPTIVE | `POST /settings/reset` with `runsHistory` (protocols, runs, offsets, …). Do **not** clear `authorizedKeys` by default. |
| **2. Deck config** | part of known-state setup | REVERSIBLE | PUT known cutouts (HS on D1, trash A3, slots). |
| **3. LPC / offsets** | part of known-state setup | REVERSIBLE + motion if probe | Prefer applying known offsets via HTTP when full probe LPC is blocked; live LPC only with explicit motion gate. |
| **4. Seed run history** | `flex-test seed-runs` | PHYSICAL_MOTION | Dry deck, tip detection / sensing off, real motion; see inventory below. |
| **4b. LPC jog timing** | `flex-test lpc-jog-timing` | PHYSICAL_MOTION | Many random `moveRelative` jogs in a high-Z safe box on C2; latency only (no offset persist). |
| **5. Suite probes** | `probe` / `crs-off-*` / `api-suite` / latency | varies | Always run-state preflight (`docs/crs-testing.md`). |

Phase 0 → 1 → 2 are safe to automate without tip pickup. Phase 3–4 / 4b need an
operator-confirmed clear deck and attached instruments/modules.

## KansasFLEX hardware assumptions

Observed / target lab config:

| Item | Value |
|------|--------|
| Instruments | left `p50_multi_flex`, right `p50_single_flex` |
| Module | Heater-Shaker `heaterShakerModuleV1` serial `HSDVT22041138` on **D1** |
| Trash | `trashBinAdapter` on **A3** |
| Deck | otherwise empty; dry run (no liquids) |

Protocols must match this deck. Tip detection and other sensing disabled in
protocol / robot settings so dry motion does not hard-fail on missing tips or
liquid sense.

## Seed run inventory (phase 4)

Each seed is a named scenario producing persisted run data (commands, camera,
comments where supported). Failures are recorded; do not abort the whole seed
unless `--strict`.

| Seed id | Outcome | Motions / modules | Notes |
|---------|---------|-------------------|-------|
| `simple_home_move` | succeeded | home + grouped move to trash (right P50, apiLevel 2.29 `group_steps`) | Short motion + real `commandAnnotations` for Tier B |
| `complex_transfer_dry` | succeeded | pick/place style dry moves, both pipettes if safe | Complex PE commands; tip detection off |
| `heater_shaker_brief` | succeeded | HS target **37 °C** (API min; ambient not allowed), shake **&lt; 5 s**, then deactivate | Labware on HS adapter optional; no long heat soak |
| `cancel_mid_run` | stopped | start play, cancel after first motion / N commands | Mid-run cancel path |
| `camera_and_comments` | succeeded | short motion + `POST /camera/picture` or run preview + run comments | Pictures + comments during run |
| `failed_intentional` | failed | play short protocol that raises `RuntimeError` | Failed terminal history |
| `pause_mid_run` | paused → stopped | play, pause (verify), then stop to free current (uncurrent while paused is 409) | Mid-run pause path; stopped afterward so later seeds can run |
| `idle_current` | idle (current) | create current run, never play | For `current-idle` suite preflight |
| `lpc_scripted` | offset stored | maintenance-run load + high-Z approach + small jogs + `POST /labwareOffsets` | Not a `.py` protocol; virtual tiprack on **C2** |

Prefer these explicit seeds over hoping leftover UI state survives. Full
`seed-runs` uncurrents the paused run so `idle_current` can remain the current
fixture for Tier B.

## Scripted LPC HTTP map (`lpc_scripted`)

Flex LPC is not exposed as a single “run LPC” endpoint. The app drives a
**maintenance run** (commands execute when enqueued) and then persists offsets
via **`/labwareOffsets`**.

| Step | Method / path | Purpose |
|------|---------------|---------|
| Create session | `POST /maintenance_runs` | Current maintenance run |
| Drive LPC-like motion | `POST /maintenance_runs/{id}/commands?waitUntilComplete=true&timeout=…` | `loadPipette`, `loadLabware`, `home`, `moveToWell`, `moveRelative`, `savePosition` |
| Persist offset | `POST /labwareOffsets` | `StoredLabwareOffsetCreate`: `definitionUri`, `locationSequence` (`onAddressableArea`), `vector` |
| Read / clear | `GET` / `DELETE /labwareOffsets`, `POST /labwareOffsets/searches` | Inventory / reset |
| Cleanup | `DELETE /maintenance_runs/{id}` | Drop maintenance run after seed |

Optional related routes: `POST …/labware_offsets`, `POST …/labware_definitions`
on the maintenance run (run-scoped offsets / defs). Harness clients:
`clients/maintenance_runs.py`, `clients/labware_offsets.py`. Capability:
`capabilities/seed_lpc.py`.

Deck: keep trash **A3** and HS **D1**; seed uses free slot **C2** with a
definition-only tiprack load and high Z (`+40 mm` above well top) so dry deck
without a physical tiprack is safer. Door must be closed (`requiresClosedDoor`).

## LPC jog timing (`flex-test lpc-jog-timing`)

Same HTTP map as `lpc_scripted` (maintenance run, virtual tiprack on **C2**,
approach at A1 top + 40 mm) but walks many random `moveRelative` jogs for
latency instead of persisting an offset. Planner: `fixtures/lpc_jog_space.py`.

Coordinates are millimetres **relative to the approach pose**. Origin is that
pose. +Z is away from the deck. The box never allows negative Z, so the pipette
never moves closer to the deck than the 40 mm approach.

| Axis | Min (mm) | Max (mm) | Why |
|------|----------|----------|-----|
| X | -2 | +12 | A1 is back-left of a 96 rack; +X into the grid toward H |
| Y | -12 | +2 | -Y into the grid toward A12 |
| Z | 0 | +20 | Never toward the deck; extra height only |

Step sizes: 0.1 / 0.5 / 1.0 / 2.0 mm (LPC UI 10 mm is skipped; the box is
smaller). Default 80 jogs (max 400), RNG seed 42, `savePosition` every 10 jogs,
then return-to-approach and home. KansasFLEX default pipette: right
`p50_single_flex`.

Gates: `ALLOW_MUTATIONS=true`, required `--confirm-clear-deck`, door closed,
estop clear, pipette on mount. Leftover maintenance run is deleted first.

```bash
ALLOW_MUTATIONS=true uv run flex-test lpc-jog-timing --confirm-clear-deck
ALLOW_MUTATIONS=true uv run flex-test lpc-jog-timing --confirm-clear-deck --jogs 200 --rng-seed 42
```

JSON under `ARTIFACT_DIRECTORY/timing/lpc-jog-timing-*.json`. Plan:
[lpc-jog-timing.yaml](test-suggestions/lpc-jog-timing.yaml).

## Latency metrics (every phase records spans)

Timing module: `orchestration/timing.py` → JSON under
`ARTIFACT_DIRECTORY/timing/<run_id>.json`.

| Metric id | Start | End | Compare across |
|-----------|-------|-----|----------------|
| `install.download` | download start | zip on disk | network |
| `install.upload_and_flash` | update begin | ready-for-restart / reboot | update-server |
| `boot.health` | reboot trigger / first offline | first `GET /health` 200 | Pyro vs non-Pyro boot |
| `boot.instruments` | first health 200 | `GET /instruments` ok with expected mounts | HW subprocess attach |
| `boot.modules` | first health 200 | heater-shaker visible | module enum |
| `protocol.upload` | POST protocols | 201 | |
| `protocol.analyze` | analysis request | analysis completed | |
| `run.create` | POST runs | 201 current idle | |
| `run.play_to_running` | POST play | status `running` | **play → robot action** |
| `run.play_to_first_command` | POST play | first command `succeeded`/`running` | PE / Pyro path |
| `run.cancel_latency` | POST stop | status `stopped` | |
| `camera.picture` | POST picture | 200 JPEG | current-run interactions |
| `lpc.create_maintenance_run` | POST maintenance_runs | 201 | LPC seed / jog timing |
| `lpc.setup_approach` | loadPipette through moveToWell | succeeded | LPC jog timing |
| `lpc.jog.NNN.{axis}` | one moveRelative | succeeded | LPC jog timing (per jog) |
| `lpc.savePosition.NNN` | savePosition after a jog | succeeded | LPC-like confirm |
| `lpc.return_to_approach` | undo XY/Z to origin | succeeded | LPC jog timing |
| `lpc.home` | home after jogs | succeeded | LPC jog timing |
| `lpc.store_offset` | POST labwareOffsets | 201 | LPC seed persist |

Always stamp: robot `system_version`, `api_version`, host, channel, whether
feature flags look like protocol/hardware subprocess (when readable).

## CLI surface (agent-runnable)

```bash
# Phase 0 — baseline non-Pyro build (external latest 9.1.2 alpha as of writing)
ALLOW_MUTATIONS=true uv run flex-test put 9.1.2-alpha.5 --channel external

# Phase 1 — clear robot-server DB (runs/protocols/offsets); keeps SSH keys
ALLOW_MUTATIONS=true uv run flex-test reset-data

# Inspect timings from last install / boot wait
uv run flex-test timing show

# Later: deck + seed (motion; explicit)
ALLOW_MUTATIONS=true uv run flex-test known-state
ALLOW_MUTATIONS=true uv run flex-test seed-runs
ALLOW_MUTATIONS=true uv run flex-test seed-runs --seed simple_home_move
ALLOW_MUTATIONS=true uv run flex-test seed-runs --seed lpc_scripted
ALLOW_MUTATIONS=true uv run flex-test lpc-jog-timing --confirm-clear-deck
```

Python: import capabilities (`reset_robot_data`, `install_build`, timing
helpers) from suite code the same way CLI does. Prefer capabilities over curl.

## Comparison workflow (Pyro impact)

1. On **external 9.1.2-alpha.N**: phases 0–2 (and 3–4 when ready); archive
   `artifacts/timing/*.json` as `baseline-9.1.2-alpha.N`.
2. `put` internal Pyro build (e.g. `4.0.0-alpha.10`); repeat same seeds/metrics.
3. Diff metric ids in a small table (boot.health, play_to_first_command, …).

Existing Pyro bugs may break seeds on internal builds; still record timings and
failures (do not hide product defects).

## Aggregation caveats (KansasFLEX 2026-08-04)

Local archives (gitignored):

| Archive | Path |
|---------|------|
| Non-Pyro baseline (prior) | `artifacts/timing/baseline-9.1.2-alpha.5/` |
| Non-Pyro baseline (current) | `artifacts/timing/baseline-9.1.2-alpha.6/` |
| Pyro compare (partial) | `artifacts/timing/pyro-4.0.0-alpha.10/` |
| Extra Pyro retry | `artifacts/timing/seed-runs-ea0a7a48-*.json` (not copied into archive yet) |

**alpha.6 notes (2026-08-04):** install from `ot3@4.0.0-alpha.10` succeeded.
First full `seed-runs` was 6/7: `camera_and_comments` failed with
`CameraDisabledError` after `reset-data` (camera off). Enabled via
`POST /camera`, then camera seed retry succeeded
(`seed-runs-3be0bdd4-…`). Seed preflight now enables the camera so this does
not repeat. Use `0d060ba8` for non-camera/LPC spans; `3be0bdd4` for camera.

**Do not share raw numbers without these caveats.**

### Missing / incomplete Pyro install timings

- `flex-test put 4.0.0-alpha.10 --channel internal` flashed successfully (update-server
  showed `ot3@4.0.0-alpha.10`), but the harness hung waiting on robot-server
  `/health` 500 (`DatabaseFailedToInitialize` / EBUSY; [RQA-5808](https://opentrons.atlassian.net/browse/RQA-5808)).
- The hung `put` was killed after SSH recovery, so **no**
  `install-4.0.0-alpha.10-*.json` was written.
- Therefore there is **no comparable** Pyro `install.download`,
  `install.upload_and_flash`, or `boot.health` span for this session.
- Baseline install on `v9.1.2-alpha.5` *was* recorded (~13s download, ~391s
  upload/flash, ~125s `boot.health`).

### Seed-run reliability vs latency

- First Pyro `seed-runs` pass: only `simple_home_move` succeeded; the next five
  seeds failed with HTTP 500 on `POST /protocols` after uncurrent.
- Journal showed stale Pyro `CommunicationError` / connection reset to a dead
  `ot-protocol` port. Treat as impact of [RQA-5791](https://opentrons.atlassian.net/browse/RQA-5791)
  (related: [RQA-5790](https://opentrons.atlassian.net/browse/RQA-5790)), not as
  “slow upload.”
- Spans left open at failure (often ~30–180s on `*.upload` / `*.create`) are
  **timeout / error dwell**, not successful operation latency. Exclude them from
  aggregates, or report them separately as failure durations.
- Retry pass recovered some seeds (`complex`, `cancel`, `idle`);
  `heater_shaker_brief` and `camera_and_comments` still failed on `POST /runs` 500.
  Prefer retry spans that `status=ok` / completed when comparing to baseline.

### Fair compare guidance

When aggregating later:

1. Compare only **completed** spans with matching metric ids and seed ids.
2. Call out that Pyro play metrics may include post-uncurrent recovery noise;
   prefer the first successful seed after a clean robot-server / protocol-process
   state when possible.
3. Do not invent Pyro `boot.health` from wall-clock memory; re-run `put` after
   the install wait fix lands if a publishable boot compare is needed.
4. Note HS protocol target is API min **37 °C** (not ambient); first baseline HS
   attempt at 23 °C failed validation and was re-run.
5. Camera seed uses in-protocol `capture_image` (apiLevel 2.27+); harness HTTP
   `/camera/picture` mid-run still hits [RQA-5807](https://opentrons.atlassian.net/browse/RQA-5807)
   and must not be treated as a camera-latency success.

## Safety

- Mutations gated (`ALLOW_MUTATIONS`)
- Enable CRS only via `flex-test crs enable --confirm-one-way` (one-way API)
- Never reset `authorizedKeys` unless explicitly requested
- Physical motion / play only when the operator asks for `seed-runs`,
  `lpc-jog-timing --confirm-clear-deck`, or known-state motion phases; deck must
  be clear; HS at API min 37 °C then deactivate; shake &lt; 5 s
- Re-discover `ROBOT_HOST` after reboot (DHCP)

## Related

- [crs-testing.md](crs-testing.md) — run presence `no-current` / `current-idle`
- [pyro-testing.md](pyro-testing.md) — internal subprocess stack
- [safety-model.md](safety-model.md)
- [robot-versions.md](robot-versions.md)
