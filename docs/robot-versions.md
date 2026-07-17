# Flex robot software versions

This harness needs a precise answer to: **what software is KansasFLEX running, and how does that compare to available Flex builds?**

Application and robot-server code live in the **monorepo** (`opentrons/opentrons`). Point-release branch/cherry-pick/mergeback patterns are documented in [monorepo-releases.md](monorepo-releases.md).

Authoritative release tagging, channel hosts, and `releases.json` locations are documented in **Opentrons/robot-stack**. Keep a local clone for reference:

```text
ROBOT_STACK_REPO_PATH=./upstream/robot-stack
```

Do not modify that clone from this harness. Live inventories and guides are also published at [opentrons.github.io/robot-stack](https://opentrons.github.io/robot-stack/).

## What “version” means on a Flex

Several related identifiers appear in the wild:

| Signal | Where you see it | Meaning |
|--------|------------------|---------|
| Robot OS / system version | `GET /health` → `system_version`, `GET /server/update/health` → `systemVersion` | On-robot OE / system build identity |
| API version | `GET /health` → `api_version` | robot-server software version |
| Update-server version | `GET /server/update/health` → `updateServerVersion` | update-server package version |
| Stack / app tag | git tags in the monorepo (`opentrons/opentrons`), `oe-core`, `ot3-firmware` | Coordinated release marker from robot-stack |
| Robot manifest key | `ot3-oe/releases.json` | Bare semver used for on-robot updates |

For Kansas install/regression work, the **robot OS manifest key** (and its matching stack tag) is the primary “which build is this?” answer. `flex-test inspect` reports the live robot fields; `flex-test releases` reports what is published.

## Internal vs external

Flex has two independent release pipelines (hosts from robot-stack `automation/flex_urls.py`):

| Channel | Host | Robot OS manifest |
|---------|------|-------------------|
| **Internal** | `ot3-development.builds.opentrons.com` | `https://ot3-development.builds.opentrons.com/ot3-oe/releases.json` |
| **External** | `builds.opentrons.com` | `https://builds.opentrons.com/ot3-oe/releases.json` |

App manifests (desktop updater) live under `/app/releases.json` on the same hosts. Flex robots read **`ot3-oe/releases.json`** for on-robot updates; that is the source of truth this harness uses for “latest robot OS releases.”

Manifests merge `production` and `productionV2` (V2 wins on duplicate keys). Newer Flex builds publish under `productionV2` so older robots keep reading legacy `production` (robot-stack `automation/release.py`).

## Stability lanes

Within each channel, versions are classified as:

- **stable** — `X.Y.Z`
- **alpha** — `X.Y.Z-alpha.N`
- **beta** — `X.Y.Z-beta.N`

Alpha and beta are **independent lanes** with separate counters on the same `X.Y.Z` base (not a promote-alpha-to-beta ladder). See robot-stack README “Flex semver (coordinated tags).”

Typical Kansas concern:

- **Internal** alphas and betas (lab / CRS / VM channels)
- **External** alphas, betas, and stables (customer-facing)

## Stack tags vs manifest keys

| Channel | Stack / app tag | Robot `releases.json` key |
|---------|-----------------|---------------------------|
| Internal | `ot3@4.0.0-alpha.5` | `4.0.0-alpha.5` |
| Internal | `ot3@4.0.0-beta.0` | `4.0.0-beta.0` |
| External | `v9.1.0-alpha.7` | `9.1.0-alpha.7` |
| External | `v9.1.0` | `9.1.0` |

Coordinated Flex tags also land on `oe-core` and (with firmware mapping rules) `ot3-firmware`. Details: robot-stack README and `automation/release_tag_catalog.py`.

## CLI

List latest published robot OS builds per channel and lane:

```bash
uv run flex-test releases
uv run flex-test releases --channel internal
uv run flex-test releases --channel external
```

Classify a version string from inspect/health:

```bash
uv run flex-test releases --installed 4.0.0-alpha.5
uv run flex-test releases --installed ot3@4.0.0-beta.0
```

Inspect the live robot (KansasFLEX):

```bash
uv run flex-test inspect
```

Put KansasFLEX on a published version (mutates robot; requires `ALLOW_MUTATIONS=true`):

```bash
uv run flex-test put 9.1.2-alpha.0
```

Compare the inspect `Installed software version` to `flex-test releases` output to see whether KansasFLEX is current for a given lane.

## robot-stack files to read first

| Path under `robot-stack` | Why |
|--------------------------|-----|
| `README.md` | Flex vs OT-2 paths, tag schemes, `chore_release-*` default for Flex external |
| (monorepo) see [monorepo-releases.md](monorepo-releases.md) | How `chore_release-X.Y.Z` cherry-picks and mergebacks work |
| `automation/flex_urls.py` | Internal/external hosts |
| `automation/asset_urls.py` | `releases.json` URL builders |
| `automation/flex_assets.py` | App + robot OS S3 prefixes and manifests |
| `automation/release.py` | `production` / `productionV2` merge, alpha/beta/stable split |
| `automation/release_tag_catalog.py` | Tag stability classification and “latest in lane” |
| `automation/flex_release_version.py` | Flex version planning helpers |

## Out of scope (for now)

- Pushing tags or invalidating CloudFront (use robot-stack `just` recipes)
- OT-2 calendar semver (`internal@YY.M…`) — Flex-only for this agent
