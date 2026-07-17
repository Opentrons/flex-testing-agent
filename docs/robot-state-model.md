# Robot state model

## Snapshot

`RobotSnapshot` is the milestone 1 aggregate:

| Field | Meaning |
|-------|---------|
| `configured_name` | From `ROBOT_NAME` (Kansas) |
| `host` / `base_url` | Connection target |
| `connectivity` | True if at least one of health / update-health succeeded |
| `health` | Normalized `GET /health` or null |
| `update_health` | Normalized `GET /server/update/health` or null |
| `access_control` | Detected access-control status |
| `errors` | Soft failures for partial inspect |

Derived helpers:

- `installed_software_version`
- `api_version`
- `robot_display_name` (prefers live health name)

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
