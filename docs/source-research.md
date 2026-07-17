# Source research

Research against the local **monorepo** clone (`opentrons/opentrons`) configured via `OPENTRONS_REPO_PATH` (example: `upstream/opentrons`). Paths below are repository-relative to that monorepo.

Do not paste large portions of Opentrons source here. This document records authoritative locations for implemented interactions.

## Python version

| Package | requires-python |
|---------|-----------------|
| robot-server | `>=3.11` |
| auth-server | `>=3.12` |
| update-server | `>=3.10` |

Harness target: **Python 3.12+**.

## GET /health

| Field | Detail |
|-------|--------|
| Purpose | Robot identity, API/OS/firmware versions, serial, disk, readiness |
| Source | `robot-server/robot_server/health/router.py` |
| Models | `robot-server/robot_server/health/models.py` (`Health`, `DiskDetails`, `HealthLinks`) |
| Route | `GET /health` |
| Auth | None for reads; may return 503 if hardware/DB not ready |
| Expected errors | 503 when not ready; connection/timeouts when robot unreachable |
| Tests | `robot-server/tests/health/test_health_router.py`; integration helpers in `robot-server/tests/integration/` |
| Uncertainty | Field availability can vary slightly by robot software version |

## GET /server/update/health

| Field | Detail |
|-------|--------|
| Purpose | Update-server / OE system versions and capabilities |
| Source | `update-server/otupdate/openembedded/__init__.py` |
| Response keys | `updateServerVersion`, `apiServerVersion`, `systemVersion`, `robotModel`, `capabilities` |
| Route | `GET /server/update/health` |
| Auth | None |
| Tests | `update-server/tests/openembedded/test_control.py` |
| Uncertainty | Capability map contents vary by build |

## GET /auth/settings/accessControlEnabled

| Field | Detail |
|-------|--------|
| Purpose | Detect whether authorization is enforced across robot HTTP APIs |
| Source | `auth-server/auth_server/settings/router.py` |
| Models | `auth-server/auth_server/settings/models.py` (`AccessControlResponseData`, `PatchAccessControlRequestData`) |
| Store | `auth-server/auth_server/settings/store.py` |
| Route | `GET /auth/settings/accessControlEnabled` |
| Auth | Read currently available when AC is off; when AC is on, protected routes need scopes |
| Expected errors | 404 if auth-server route absent on older builds; 401/403 when AC on without token |
| Tests | `auth-server/tests/integration/test_settings.tavern.yaml` and related auth integration tests |
| Critical constraint | `PATCH` accepts only `accessControlEnabled: true` (`Literal[True]`). Once set, cannot be modified via API (`AccessControlAlreadySetError` / HTTP 422). Disable requires Opentrons assistance or SSH wipe of auth-server data (prior art). |
| Harness policy | **Detect only. Never PATCH.** |

## Flex release manifests (robot-stack)

| Field | Detail |
|-------|--------|
| Purpose | Discover published Flex robot OS builds (internal/external; alpha/beta/stable) |
| Reference repo | `Opentrons/robot-stack` (local: `ROBOT_STACK_REPO_PATH`, e.g. `upstream/robot-stack`) |
| Hosts | Internal `ot3-development.builds.opentrons.com`; external `builds.opentrons.com` (`automation/flex_urls.py`) |
| Robot OS manifest | `/{ot3-oe}/releases.json` (`automation/asset_urls.py`, `automation/flex_assets.py`) |
| Parsing | Merge `production` + `productionV2` (`automation/release.py`) |
| Tag scheme | Internal `ot3@X.Y.Z[-alpha.N\|-beta.N]`; external `vX.Y.Z[-alpha.N\|-beta.N]` (`README.md`, `automation/release_tag_catalog.py`) |
| Harness surface | `flex-test releases` + `docs/robot-versions.md` |
| Uncertainty | CDN/CloudFront caching can briefly lag freshly published tags until invalidation |

## Intentionally not implemented (researched)

### PATCH access control enable

Blocked in harness. Disruptive / one-way.

### OEM / factory mode

`PUT /system/oem_mode/enable` in `system-server/system_server/system/oem_mode/`. Ignored by product decision; not part of “lockdown” for Kansas.

### Software update flow

`POST /server/update/begin|file|commit` in update-server. Deferred to later PRs.

### User management

`auth-server/auth_server/users/router.py` (`/auth/users/*`). Deferred until AC-on testing has a restore story.

### OAuth token

`POST /auth/oauth2/token` in `auth-server/auth_server/oauth2/router.py`. Needed for AC-on dual-mode; not required for inspect when AC is off.

## Client cross-check

TypeScript API client references (optional cross-check, not used as runtime dependency):

- `api-client/src/`
- Auth scopes: `server-utils/server_utils/auth/scopes.py`
