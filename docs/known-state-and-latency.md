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
| **0. Build** | `flex-test put <ver>` | INSTALLATION | Baseline first: latest external `9.1.2-alpha.*` (no Pyro). Later re-run on internal `4.0.0-alpha.*` for comparison. |
| **1. Clear robot-server data** | `flex-test reset-data` | DISRUPTIVE | `POST /settings/reset` with `runsHistory` (protocols, runs, offsets, …). Do **not** clear `authorizedKeys` by default. |
| **2. Deck config** | part of known-state setup | REVERSIBLE | PUT known cutouts (HS on D1, trash A3, slots). |
| **3. LPC / offsets** | part of known-state setup | REVERSIBLE + motion if probe | Prefer applying known offsets via HTTP when full probe LPC is blocked; live LPC only with explicit motion gate. |
| **4. Seed run history** | `flex-test seed-runs` (planned) | PHYSICAL_MOTION | Dry deck, tip detection / sensing off, real motion; see inventory below. |
| **5. Suite probes** | `probe` / `crs-off-*` / latency | varies | Always run-state preflight (`docs/crs-testing.md`). |

Phase 0 → 1 → 2 are safe to automate without tip pickup. Phase 3–4 need an
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
| `simple_home_move` | succeeded | home + simple moves (right P50) | Simple commands only |
| `complex_transfer_dry` | succeeded | pick/place style dry moves, both pipettes if safe | Complex PE commands; tip detection off |
| `heater_shaker_brief` | succeeded | HS target **37 °C** (API min; ambient not allowed), shake **&lt; 5 s**, then deactivate | Labware on HS adapter optional; no long heat soak |
| `cancel_mid_run` | stopped | start play, cancel after first motion / N commands | Mid-run cancel path |
| `camera_and_comments` | succeeded | short motion + `POST /camera/picture` or run preview + run comments | Pictures + comments during run |
| `idle_current` | idle / uncurrent | create current run, never play | For `current-idle` suite preflight |

Add more states only when product APIs expose them cleanly (paused, errored
recovery). Prefer explicit seeds over hoping leftover UI state survives.

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

## Safety

- Mutations gated (`ALLOW_MUTATIONS`)
- Never enable CRS
- Never reset `authorizedKeys` unless explicitly requested
- Physical motion / play only when the operator asks for seed-runs / known-state
  motion phases; deck must be clear; HS at API min 37 °C then deactivate; shake &lt; 5 s
- Re-discover `ROBOT_HOST` after reboot (DHCP)

## Related

- [crs-testing.md](crs-testing.md) — run presence `no-current` / `current-idle`
- [pyro-testing.md](pyro-testing.md) — internal subprocess stack
- [safety-model.md](safety-model.md)
- [robot-versions.md](robot-versions.md)
