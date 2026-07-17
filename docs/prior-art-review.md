# Prior-art review

## Branch / commits inspected

| Item | Value |
|------|--------|
| Clone | Local `opentrons/opentrons` via `OPENTRONS_REPO_PATH` (example `upstream/opentrons`) |
| Branch | `teach/auth-client-demo` |
| Origin tip reviewed | `9f4deffa2306577ee15261385beaa1e3d404ca97` — *Add Flex robot auth E2E tooling for demo users and HTTPS testing.* |
| Local HEAD at review time | `517b4464282935ee5cb4649c9df57feb3b0bba37` (merge of `origin/edge` into the branch; ahead of origin) |

Prior art was treated as reference material, not the final architecture. The prior-art branch was not modified.

## Files reviewed

Under `e2e-testing/`:

- `automation/clients/auth.py`
- `automation/clients/keys.py`
- `automation/clients/auth_models/*`
- `automation/robot_certs/{host,registry,paths,store}.py`
- `automation/robot_encryption.py`
- `automation/auth_helpers.py`, `auth_access.py`
- `automation/demo_users.py`, `demo_access_matrix.py`, `demo_access_runner.py`
- `automation/robot_cleanup.py`, `flex_ssh.py`
- `scripts/inspect_robot_auth.py`, `provision_demo_users.py`, `cleanup_robot_runs.py`, `reset_robot_auth_server.py`
- `Makefile`, `pyproject.toml`, `README.md`

## Existing capabilities found

- HTTPS Flex host resolution (`https://{ip}:32313`) with CA PEM registry
- `Opentrons-Version: 3` header convention
- Async `AuthClient` (ROPC token, settings, users, introspect)
- Access-control enable helper (one-way)
- Demo user provisioning and large access-matrix probes
- Run/maintenance/update cleanup helpers
- SSH-based auth-server data wipe to reset access control

No dedicated robot-server health client; robot HTTP often reused `AuthClient._client`.

## Code reused (conceptually)

- Port defaults: HTTP `31950`, HTTPS `32313`
- Always send `Opentrons-Version: 3`
- Thin async httpx client style (one method ≈ one HTTP call)
- Env-driven robot host configuration (mapped to `ROBOT_HOST`)
- Recognition that access control enablement is one-way

## Code adapted

- Host/base URL construction → `Settings.robot_base_url` + `RobotHttpSession`
- Auth settings GET envelope handling → `AuthSettingsClient.detect_access_control`
- Inspect CLI idea → `flex-test inspect` with persistence/evidence

## Code rejected

| Item | Reason |
|------|--------|
| Living inside `e2e-testing` / Playwright / PD stack | Wrong product boundary; harness must be standalone |
| Hardcoded demo passwords | Unsafe for a shared Opentrons org repo |
| Demo access-matrix HTML + concurrent scope battery | Too large; RBAC is a later milestone |
| Private `_client` reuse for robot routes | Prefer first-class robot clients |
| Local auth-server subprocess runner | Not needed for physical Kansas testing |
| Immediate HTTPS CA bootstrap requirement | Milestone 1 inspect uses HTTP by default |
| Enabling access control in helpers | Unsafe without restore; out of milestone 1 scope |

## Architectural differences

1. **Harness-first package** (`flex_testing_agent`) with capabilities, scenarios, persistence, evidence.
2. **Agent-runtime independence**: no Cursor/MCP foundation.
3. **Detect-only access control** with explicit blocked enable capability.
4. **Persistence and audit** from day one (SQLite + Alembic).
5. **Risk levels and mutation gates** before agent exposure.

## Follow-up questions

1. When AC-on testing begins, is SSH wipe an acceptable restore for Kansas lab use?
2. Should HTTPS + CA bootstrap land before or with the first authenticated scenarios?
3. Is there an upcoming reversible “lockdown” API distinct from access control?
