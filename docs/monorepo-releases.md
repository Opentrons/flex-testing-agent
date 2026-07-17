# Monorepo release pattern (`opentrons/opentrons`)

This harness calls **[Opentrons/opentrons](https://github.com/Opentrons/opentrons)** the **monorepo** (also “app monorepo”). It holds robot-server, API/hardware control, shared-data, desktop/ODD app, and related packages.

Coordinated Flex **robot OS** builds and tags are planned in **robot-stack** (`oe-core`, `ot3-firmware`, plus the monorepo). This document describes how **point releases** are assembled on monorepo release branches, using `chore_release-9.1.2` as the concrete example.

Local clone (gitignored research tree):

```text
OPENTRONS_REPO_PATH=./upstream/opentrons   # the monorepo
ROBOT_STACK_REPO_PATH=./upstream/robot-stack
```

## Naming

| Term | Meaning |
|------|---------|
| **Monorepo** | `opentrons/opentrons` |
| **Release branch** | `chore_release-<X.Y.Z>` on the monorepo (e.g. `chore_release-9.1.2`) |
| **PD release branch** | `chore_release-pd-<X.Y.Z>` (Protocol Designer line; receives mergebacks) |
| **External stack tag** | `vX.Y.Z`, `vX.Y.Z-alpha.N`, `vX.Y.Z-beta.N` on monorepo + oe-core |
| **Internal stack tag** | `ot3@X.Y.Z…` on monorepo + oe-core (+ firmware coordination) |
| **Robot OS key** | Bare semver in `ot3-oe/releases.json` (no `v` / `ot3@` prefix) |

Flex **external** builds prefer the monorepo `chore_release-<version>` branch when it exists (robot-stack default). See [robot-versions.md](robot-versions.md) and robot-stack `README.md`.

## Point-release flow (observed on 9.1.2)

```text
edge (or prior work)
        │  select fixes
        ▼
 cherry-pick branch  ──PR──►  chore_release-9.1.2
 (e.g. cherry-pick-fixes-9.1.2)
        │
        │  additional cherry-picks / hotfixes onto release branch
        ▼
 tag lane on monorepo tip
   v9.1.2-alpha.0 → … → eventually v9.1.2
        │
        │  robot-stack coordinates oe-core / firmware + publishes
        ▼
 ot3-oe/releases.json  (robot can `flex-test put <version>`)
        │
        │  incremental mergeback (keep PD in sync)
        ▼
 chore_release-pd-9.0.0  (e.g. for PD 9.0.1)
```

### 1. Cut / maintain `chore_release-X.Y.Z`

Branch name encodes the **semver base** only (`9.1.2`), not alpha/beta. Stability lanes are tags on that branch tip over time.

### 2. Cherry-pick selected fixes into the release branch

Example: [PR #21935](https://github.com/Opentrons/opentrons/pull/21935)  
`chore(mono): Cherry-pick select commits for chore_release-9.1.2`

- Head: topic branch (`cherry-pick-fixes-9.1.2`)
- Base: `chore_release-9.1.2`
- Body lists product themes and any behavior that **differs** from an older train (here: `_dedupe_available_modules` must not clear parked modules because 9.1.x reconnect runs immediately after attach)

Further hotfixes land as separate PRs **into** `chore_release-9.1.2` (also often titled “cherry picking …”):

| PR | Theme |
|----|--------|
| #21935 | API module reconnect/retry + 96ch centering |
| #21941 | Tiprack lid compatible with 20 µL filter tiprack |
| #21949 | Flex trash deck-label rotation (components / PV) |
| #21946 | ODD Protocol Setup re-render with loops + RTP |

### 3. Tag from the release branch tip

External alpha example already on the monorepo:

| Tag | Notes |
|-----|--------|
| `v9.1.2-alpha.0` | Tagged near the module/shared-data/components fixes |
| Later `v9.1.2-alpha.N` / `v9.1.2` | Cut as more commits land and QA signs off |

robot-stack then tags matching stack repos and publishes robot OS assets. KansasFLEX install key is the bare version (`9.1.2-alpha.0`).

### 4. Mergeback into other release lines

Example: [PR #21971](https://github.com/Opentrons/opentrons/pull/21971)  
`chore(mono): Incremental mereback of chore_release-9.1.2 into chore_release-pd-9.0.0`

RS (robot software) point-release commits are folded into the PD release branch so Protocol Designer point releases stay aligned. “Mereback” in titles means **mergeback**.

## What landed in `chore_release-9.1.2` vs `v9.1.1`

Robot-relevant monorepo delta (high signal for KansasFLEX testing):

1. **96-channel centering on row-layout labware** (`#21803`)  
   Nozzle/motion/labware math + new `nest_8_reservoir_22ml` v2 definition.
2. **Module USB reconnect resilience** (`#21834`, `#21880`, temp-deck follow-up)  
   Retry/backoff on build; dedupe by serial; keep parked modules for reconnect; temp-deck re-enumeration.
3. **Tiprack lid compatibility** (`#21941`)  
   `opentrons_flex_96_filtertiprack_20ul` allowed under `opentrons_flex_tiprack_lid`.
4. **UI / visualization** (less robot-API critical)  
   ODD setup memoization with loops+RTP; Flex trash tag rotation for left slots.

## How this harness should use the pattern

When preparing KansasFLEX against a point release:

1. Identify monorepo branch `chore_release-<base>` and commits since prior tag (`v9.1.1` → tip).
2. Map each fix to a **robot-facing** test (API, module, protocol) vs **app-only** (ODD/PV).
3. Confirm published key via `flex-test releases`, then `flex-test put <version>` when installing.
4. Prefer probing APIs this harness already owns (`inspect`, `probe`, modules/instruments) before full protocol runs.

## Related docs

- [robot-versions.md](robot-versions.md) — channels, manifests, CLI
- [source-research.md](source-research.md) — monorepo paths for HTTP APIs
- robot-stack `README.md` — tagging order and `chore_release-*` as Flex external default branch
