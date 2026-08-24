# Robot state model

## Snapshot

`RobotSnapshot` is the inspect aggregate for **KansasFLEX** (not "Kansas"):

| Field | Meaning |
|-------|---------|
| `configured_name` | From `ROBOT_NAME` (default KansasFLEX) |
| `host` / `base_url` | Connection target (HTTPS `:32313` when CRS is on) |
| `connectivity` | True if at least one of health / update-health succeeded |
| `health` | Normalized `GET /health` or null |
| `update_health` | Normalized `GET /server/update/health` or null |
| `access_control` | Detected access-control status |
| `plaintext_http_reachable` | CRS on: whether HTTP `:31950` still served `/health` (leak; [RQA-5981](https://opentrons.atlassian.net/browse/RQA-5981)). Null when CRS is off |
| `ssh_tcp_reachable` / `ssh_authenticated` | Lab SSH probe (`flex-test ssh status`) |
| `recommended_shell` | `ssh` if BatchMode auth worked, else `serial` |
| `transport_notes` | Operator hints (HTTPS-only CRS API, carveout, printk) |
| `errors` | Soft failures for partial inspect |

Derived helpers:

- `installed_software_version`
- `api_version`
- `robot_display_name` (prefers live health name)

How to choose HTTPS vs SSH vs serial: [interaction-layers.md](interaction-layers.md).

Published Flex builds (not part of the live snapshot object, but used for comparison) come from the release catalog. See [robot-versions.md](robot-versions.md) and `flex-test releases`.

## Access control state

`AccessControlState`:

| Value | Meaning |
|-------|---------|
| `disabled` | API reported `accessControlEnabled: false` |
| `enabled` | API reported `true` |
| `unknown` | Request failed or response malformed |
| `unsupported` | Endpoint missing (404) |

OEM / factory mode is **not** part of this model.

## Future extensions

Later snapshots may include:

- Authenticated principal / scopes
- Installed build identity
- Run / maintenance activity
- Baseline markers for restore

Keep the base `RobotUnderTest` protocol small; add optional capability protocols rather than forcing every feature into one interface.
