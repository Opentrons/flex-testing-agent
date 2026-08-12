# CRS-on setup (access control enabled)

Design for turning KansasFLEX (or a dedicated CRS lab robot) into a **CRS-on**
test target with **HTTPS**, provisioned **role fixtures**, and a path to Tier
CRS-on authorization matrix testing.

Local SSOT for CRS-off remains [crs-testing.md](crs-testing.md). This doc covers
the **CRS-on bootstrap** only.

## Prior art

Adapted conceptually from monorepo branch `teach/auth-client-demo`
(`e2e-testing/automation/*`). See [prior-art-review.md](prior-art-review.md) for
what was reused vs rejected.

| Monorepo concept | Harness location |
|------------------|------------------|
| `robot-certs/registry.yaml` + PEM store | `artifacts/robot-certs/` (gitignored) |
| HTTPS `:32313` + CA verify | `ROBOT_USE_HTTPS`, `RobotHttpSession(verify=…)` |
| ROPC `POST /auth/oauth2/token` | `clients/oauth.py` |
| User CRUD `POST /auth/users` | `clients/users.py` |
| Demo account types + scopes | `fixtures/crs_users.yaml` + `flex-test crs provision-users` |
| Encrypt-key / CA bootstrap | `flex-test crs trust-ca` |

## Prerequisites (operator)

1. **Dedicated robot or accepted lockout risk** (CRS enable is one-way via API).
2. **Restore rehearsed**: `opentrons_disable_crs` from root SSH/serial
   (`{robot_serial}-0000`), plus serial remote-access carveout while CRS stays on.
   See [crs-testing.md](crs-testing.md#enter--exit-crs-operator-notes).
3. **Enter CRS manually** (ODD / product flow) **or** harness:
   `ALLOW_MUTATIONS=true uv run flex-test crs enable --confirm-one-way`
   (one-way; creates bootstrap admin `flex_harness_admin` from fixtures).
4. Bootstrap admin credentials live in `fixtures/crs_users.yaml`
   (`flex_harness_admin` / lab default password). Override via
   `CRS_ADMIN_USERNAME` / `CRS_ADMIN_PASSWORD` when needed.

## Workstreams

```text
1. HTTPS trust     flex-test crs trust-ca
2. User fixtures   fixtures/crs_users.yaml + flex-test crs provision-users
3. Auth clients    oauth + users clients, session bearer token
4. CRS-on matrix   deferred: authorization probes per catalog + scopes
```

### 1. HTTPS trust

Two different secrets (do not conflate):

| Secret | Used for | On alpha.12 (KansasFLEX) |
|--------|----------|---------------------------|
| **Robot Encryption Key** | Decrypt `encryptedCerts` → HTTPS CA PEM | ODD rotating key (~30s periods; QA checklist ~2 min UX). **Required** for `trust-ca`. |
| **CRS service PIN** `{serial}-0000` | Enter CRS, `opentrons_disable_crs` | Newer product behavior; **does not** decrypt HTTPS certs on alpha.12 (verified). |

While CRS is **off**, fetch encrypted CA material over HTTP and decrypt with the
**ODD Robot Encryption Key** (same flow as Opentrons App “Verify robot encryption
key” and monorepo `verify_robot_encryption.py`). Save PEM +
`registry.yaml` under `artifacts/robot-certs/`.

```bash
# Open Robot encryption key on ODD, copy the key, then immediately:
ALLOW_MUTATIONS=true uv run flex-test crs trust-ca --password 'word-word-word'

# Or import PEM from Opentrons App cert dir (macOS):
# ~/Library/Application Support/Opentrons/certificates/

# Then enable HTTPS for all harness calls
ROBOT_USE_HTTPS=true
```

Optional: import PEMs from Opentrons App cert dir (`~/Library/Application Support/Opentrons/certificates/` on macOS) if already trusted in the app.

Settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ROBOT_USE_HTTPS` | `false` | Use `https://host:32313` |
| `ROBOT_HTTPS_PORT` | `32313` | HTTPS port |
| `ROBOT_CERTS_DIR` | `./artifacts/robot-certs` | PEM + registry store |
| `ROBOT_CA_PEM` | (empty) | Override: explicit PEM path |
| `CRS_SERVICE_PASSWORD` | (empty) | Robot Encryption Key for `trust-ca` (not `{serial}-0000`) |

Discovery (`GET /health`) uses the same CA verify when `ROBOT_USE_HTTPS=true`.

### 2. User fixtures

`src/flex_testing_agent/fixtures/crs_users.yaml` defines accounts by **account
type** (`admin`, `user`, `auditor`, `service`). Passwords are **not** in git:
set `CRS_FIXTURE_PASSWORD` in `.env` (shared lab password) or per-user overrides
(`CRS_PASSWORD_FLEX_TEST_ADMIN`, etc.).

Legacy Postman names (`testadmin`, `testuser`) remain in the fixture file as
**optional** entries (disabled by default) for backward compatibility.

Provision after CRS on (bootstrap admin exists):

```bash
# One-shot: enable CRS + bootstrap admin + fixture users
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs enable --confirm-one-way

# Or provision only (CRS already on):
export CRS_ADMIN_USERNAME='flex_harness_admin'   # optional; yaml default
export CRS_ADMIN_PASSWORD='FlexHarnessAdmin1!'   # optional; yaml default
ALLOW_MUTATIONS=true uv run flex-test crs provision-users
```

When CRS is still off, provisioning works without admin credentials (unauthenticated user create).

### 3. Auth session

With CRS on, obtain a token via ROPC and attach `Authorization: Bearer …` on
`RobotHttpSession`. Future CLI flags: `--as-user flex_test_operator`.

### 4. CRS-on authorization matrix

```bash
ROBOT_USE_HTTPS=true uv run flex-test crs auth-matrix
```

Exercises catalogued scoped GET endpoints with no token and each fixture role
(`flex_test_operator`, `flex_test_auditor`, `flex_test_service`,
`flex_harness_admin`). **auth-server** routes are asserted strictly (401/403 vs
200/404). **robot-server** scoped GETs are report-only on alpha builds until
enforcement is complete.

### 4b. CRS-on lockdown negative auth

Complements **auth-matrix** (valid tokens, scoped GET allow/deny) with
**negative** probes across methods and bad credentials:

| Actor | What it tests |
|-------|----------------|
| `none` | No `Authorization` header |
| `bad_bearer` | Invalid bearer string |
| `malformed_bearer` | Non-JWT bearer |
| `bad_oauth` | Wrong ROPC password on `POST /auth/oauth2/token` |
| `auditor` | Read-only role must not mutate or read write-scoped data |
| `operator` | User role must not hit admin-only scopes |

```bash
# Parameter-free catalog (all HTTP methods); summary output
ROBOT_USE_HTTPS=true uv run flex-test crs lockdown

# Include `{runId}` / `{protocolId}` paths with placeholder UUIDs
ROBOT_USE_HTTPS=true uv run flex-test crs lockdown --include-parameterized

# Hard-fail only auth-server + audit-server
ROBOT_USE_HTTPS=true uv run flex-test crs lockdown --strict-only --show-failures

# Pick actors
ROBOT_USE_HTTPS=true uv run flex-test crs lockdown --actors none,bad_bearer,auditor
```

**Strict services:** auth-server and audit-server mutations must return 401/403
without valid credentials. **Report-only:** robot-server mutation gaps
(non-401/403) are counted OK but printed in `--show-failures` for triage.
**Mutation bypass:** POST/PATCH/PUT/DELETE returning 200/201/204 without valid
credentials is always a failure. GET routes are reachable without credentials by
design.

Published checklist: `docs/test-suggestions/crs-on-lockdown-negative-auth.yaml`.

### 5. CRS-on Tier A (GET probe + user-management API)

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe --as-user flex_test_operator
# GET probe only (skip user CRUD):
ROBOT_USE_HTTPS=true uv run flex-test crs probe --skip-users-api
```

Tier A combines the catalogued parameter-free **GET probe** (OAuth as
`--as-user`, default `flex_test_operator`) with the full **auth-server
user-management REST verb suite** (idempotent CRUD on throwaway
`flex_harness_um_crud`, admin OAuth as `flex_harness_admin`). Includes
`POST/GET/PATCH/DELETE /auth/users*`, `resetPassword`, self routes, and OAuth
introspect.

Shortcut for user CRUD only: `flex-test crs users-api`.

### 6. CRS-on Tier B (parameterized GETs)

```bash
ROBOT_USE_HTTPS=true uv run flex-test crs probe-b --as-user flex_test_operator
# Optional fixture seeding (mutations while CRS on):
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe-b --create-fixtures
```

Same parameterized GET catalog as CRS-off Tier B (`flex-test crs-off-b`), but
requests carry an OAuth bearer token. Default run presence: `current-idle`.
Auth path params use `--as-user` for `/auth/users/byUsername/{username}`.

### 7. CRS-on Tier C (reversible mutations)

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe-c
# Default --as-user flex_test_service (run create needs run_data.write)
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe-c --as-user flex_test_operator
```

Same reversible mutation steps as CRS-off Tier C (`flex-test crs-off-c`), with OAuth.
Default run presence: `no-current`. Mutating requests automatically include the
`Opentrons-User-Notes` header (CRS audit trail); override with `ROBOT_USER_NOTES`
in `.env` or set empty to disable. Run delete / uncurrent steps sign off via
`PATCH /runs/{id}` with `signedBy` when CRS requires protocol-log signoff.

### 8. CRS-on full suite (matrix + A + B + C)

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs suite
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs suite --skip-auth-matrix
```

Writes `artifacts/crs_on_suite.json` and a timing report under `artifacts/timing/`.
Default OAuth user: `flex_test_service` (broad scopes for B fixture create and C).
Tier A includes user-management API coverage automatically.

## Safety

- Harness **never** PATCH-enables CRS.
- `trust-ca` and `provision-users` are `REVERSIBLE_MUTATION` / `DISRUPTIVE` as
  appropriate; require `ALLOW_MUTATIONS=true` when mutating robot auth state.
- Redact tokens and passwords in evidence (`evidence/redaction.py`).
- Re-check `ROBOT_HOST` after DHCP moves (HTTP probe still works pre-trust).

## Related

- [crs-testing.md](crs-testing.md)
- [safety-model.md](safety-model.md)
- [prior-art-review.md](prior-art-review.md)
- Confluence: [Flex testing harness CRS matrix (RBARM)](https://opentrons.atlassian.net/wiki/spaces/RBARM/pages/6382649592)
