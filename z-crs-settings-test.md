# CRS settings and identity coverage

This is the end-to-end test plan for the CRS settings experience. It separates:

1. **Manual App/ODD tests**, which validate what an operator can see, edit, cancel,
   confirm, and experience in the UI.
2. **Automated API tests**, which validate the underlying policy, authorization,
   persistence, and token behavior.

The two layers are intentionally complementary. A passing API test does not prove
that the App displays the value, sends the correct payload, shows the reason
prompt, or rolls back a cancelled edit. A passing manual test does not prove that
every role, endpoint, or token edge case is protected.

## Scope and test personas

Use a CRS-enabled Flex with HTTPS and these accounts:

| Persona | Purpose |
| --- | --- |
| Admin | View and change CRS settings; manage users |
| User/operator | Use the robot and attempt actions gated by admin settings |
| Auditor | Read allowed settings and audit information; attempt denied writes |
| Second session | Keep a target user logged in while Admin changes that account |

Run manual tests in both the Opentrons App/Desktop and the ODD wherever the
feature is available. Record the client, build, robot OS, browser/app version,
persona, setting baseline, and screenshots of failures.

### Preconditions

- CRS is enabled and the robot is reachable over HTTPS.
- Admin, user/operator, and auditor credentials are known.
- The deck is empty and the robot is safe for any protocol or update smoke
  action. Do not install software or play a protocol unless the test explicitly
  requires it and the operator has approved it.
- Capture the initial settings before changing anything.
- For account/session tests, use throwaway users. Never use a real operator
  account for lockout or password-reset tests.
- For audit tests, have a known valid reason and a known invalid/short reason.
- After every test, restore the baseline and verify the UI and API agree.

## Part 1: Manual App/ODD test suite

### M0. Enter CRS and reach settings

| ID | Test | Expected result |
| --- | --- | --- |
| M0.1 | Log in as Admin, open the robot card **⋮** menu → **Robot settings** → **Compliance Ready** tab | Settings page loads; all sections and controls are visible |
| M0.2 | Open settings as User/operator | User cannot edit Admin-only settings, or the settings entry is not available |
| M0.3 | Open settings as Auditor | Auditor can read only the settings permitted by product design and cannot save changes |
| M0.4 | Refresh, leave and return to the page | Values remain stable and match the saved baseline |
| M0.5 | Compare App/ODD values with the API snapshot | Every displayed value matches `GET /auth/settings` and audit settings |
| M0.6 | Attempt to open settings while unauthenticated | Login is required; no protected settings are exposed |

### M1. Login and security settings

For each editable value, test a valid change, invalid boundary values, save,
cancel, refresh, and restore. A cancelled change must not reach the robot.

| ID | Setting / path | Positive manual test | Negative / boundary test |
| --- | --- | --- | --- |
| M1.1 | Maximum login attempts | Change from baseline `Z` to valid `N`; save; reopen and confirm `N` | Set `0`, a negative number, decimal, text, blank, and an excessively large value such as `99999`; verify inline validation or documented clamping |
| M1.2 | Login-attempt enforcement | Set a low valid threshold; fail login until the threshold is reached; confirm account deactivation and Admin recovery | Verify a failure below the threshold does not deactivate the account; verify the locked user cannot log in with the correct password |
| M1.3 | Password expiration toggle | Turn on; save; reopen; verify enabled state | Cancel the change; refresh; verify it remains off. If a duration is shown, reject blank, zero, negative, and malformed values |
| M1.4 | Password expiration behavior | On a test target with a supported short period, wait or advance the test clock; log in and complete the forced-reset flow | Expired password cannot access normal robot functionality before reset; a non-expired password continues to work |
| M1.5 | Password complexity toggle | Turn on; save; create/change a password satisfying every displayed rule | Reject a password missing each individual rule, including too short and missing special character; verify the error identifies the requirement |
| M1.6 | Auto-logout duration | Set a valid short duration; save; remain idle past the duration; verify the session returns to login | Activity before expiry keeps the session alive; invalid, zero, negative, blank, decimal, and extreme values are rejected or handled as documented |
| M1.7 | Save/cancel semantics | Change multiple Login and security values, save, reopen, and confirm all values | Change a value, choose Cancel in the audit/reason dialog, and verify the UI returns to the prior value and no policy changed |
| M1.8 | Reload and reconnect | Save a valid value, close/reopen the client, and reconnect to the robot | A failed save or lost connection does not leave a false value displayed as persisted |

### M2. Actions requiring admin credentials

Run each test with the setting enabled and disabled. The disabled state means
the action is governed by the normal role permissions, not that every user can
perform it.

| ID | Setting / action | Enabled | Disabled |
| --- | --- | --- | --- |
| M2.1 | Require admin credentials to update robots | User attempts a robot software update and is prompted/denied; Admin can begin the flow | User can begin the flow if otherwise authorized; cancel before installing |
| M2.2 | Require admin credentials to send protocols to this robot | User attempts to send a valid protocol and is denied or shown the Admin credential prompt; Admin can send | User can send if otherwise authorized; use a no-motion smoke protocol |
| M2.3 | Require admin credentials for signature upon completing a protocol run | User reaches sign-off and is denied/prompted; Admin can complete sign-off | User can sign off if otherwise authorized |
| M2.4 | Combined gate behavior | Enable all three; verify the User is independently blocked at update, protocol send, and sign-off | Disable one flag at a time; only that corresponding action changes while the other two remain gated |
| M2.5 | Cancel Admin credential prompt | Start each gated action, cancel the credential prompt, and return to the prior screen | Confirm the action was not sent, uploaded, started, or signed |
| M2.6 | Wrong Admin credentials | Enter an invalid Admin password in each prompt | The action remains blocked; no partial mutation or misleading success state appears |
| M2.7 | Admin credential session behavior | Complete a prompt with valid Admin credentials | Confirm whether the prompt authorizes only the current action or the documented session duration; verify logout clears it |

### M3. Audit log requirements

| ID | Setting / action | Positive manual test | Negative / boundary test |
| --- | --- | --- | --- |
| M3.1 | Require documentation for robot actions | Enable; perform a documented robot action; verify the reason dialog appears before the action | Cancel the dialog; action does not occur and the setting/UI state is unchanged |
| M3.2 | Minimum documentation length | Set a valid minimum; enter a reason at exactly the minimum length; action proceeds | One character below minimum, blank, whitespace-only, and invalid characters are rejected |
| M3.3 | Documentation persistence | Save the minimum length, leave and reopen settings | Cancel the audit-settings confirmation; value returns to baseline |
| M3.4 | Require signature after a protocol run | Enable; complete a no-motion test run; verify sign-off is required and recorded | Cancel or submit an empty/invalid signature; run cannot be finalized |
| M3.5 | Download audit logs in App at end of run | Enable; complete a test run; verify the App prompts for download and the audit log is available locally | Decline or cancel download; verify the documented behavior and that the user is not told the file was saved when it was not |
| M3.6 | Audit setting interactions | Enable documentation, signature, and download together; complete a run and follow the full sequence | Disable one setting at a time; verify only its prompt/requirement changes |
| M3.7 | Audit reason on setting changes | Change any CRS setting and provide a valid reason | Cancel, submit too-short, or submit invalid reason; no setting change is persisted |
| M3.8 | Audit record content | After a successful change/action, view/download the audit record | Confirm actor, action, timestamp, reason, and result are present and do not contain passwords or bearer tokens |

### M4. Robot storage

| ID | Test | Positive manual test | Negative / boundary test |
| --- | --- | --- | --- |
| M4.1 | Automatic protocol-log deletion enabled | Enable; create enough disposable protocol records to reach the documented threshold of 20; verify the documented deletion behavior | Disable; verify records are retained according to the product limit |
| M4.2 | Automatic deletion disabled | Disable; create disposable records; verify records are retained according to the product limit | Re-enable; verify the setting persists after refresh |
| M4.3 | Boundary at 19, 20, and 21 records | Verify the threshold behavior exactly, including which record is deleted and whether the UI explains it | Verify no unexpected records are deleted below the threshold |
| M4.4 | Persistence and cancel | Save, reopen, and refresh; UI and robot state remain consistent | Toggle, cancel from the audit dialog, and verify the prior value remains |

### M5. Personal account settings

Run once as Admin and once as a normal User. Use a throwaway account for the
negative cases.

| ID | Test | Expected result |
| --- | --- | --- |
| M5.1 | Change username only | New username is shown; logout and login with the new username works; old username does not |
| M5.2 | Change password only | New password works after logout; old password does not |
| M5.3 | Change legal name only | New legal name is shown after save, refresh, logout, and login; existing session remains usable |
| M5.4 | Change username, password, and legal name together | All three changes persist; new credentials log in and the legal name is correct |
| M5.5 | Sequential username then legal name | Save username, then save legal name; verify the second save succeeds and the existing session remains valid. Track RQA-5950 if it fails |
| M5.6 | Sequential username then password | Save username, then save password; verify the second save succeeds and the existing session remains valid. Track RQA-5950 if it fails |
| M5.7 | Invalid profile inputs | Duplicate username, blank username, weak password, mismatched confirmation, and blank legal name are rejected with usable validation |
| M5.8 | Cancel profile edits | Make each edit, cancel, refresh, and log out/in; no cancelled value is persisted |

### M6. User management

Use two machines or two independent sessions: Admin and target User.

| ID | Test | Expected result |
| --- | --- | --- |
| M6.1 | Create user | Admin creates User, Auditor, and (if exposed) Service accounts; each can log in with the assigned role |
| M6.2 | Edit legal name | Admin changes only legal name; target session remains valid and sees the new name |
| M6.3 | Edit username | Admin changes username; target's old session is invalidated; new username can log in |
| M6.4 | Edit role | Admin changes role; target's old session is invalidated; new session has the new permissions |
| M6.5 | Lock account | Admin locks target; Admin UI shows locked; target is immediately locked out, including an active session |
| M6.6 | Unlock account | Admin unlocks target; target can log in again with the current password |
| M6.7 | Reset password | Admin initiates reset; UI shows reset/temporary-password state; original password fails and the temporary password works once |
| M6.8 | Temporary-password rotation | Target changes the temporary password; temporary password stops working and the new password works |
| M6.9 | Delete user | Admin deletes target; target session is invalidated and login fails; deleted user is absent from the list |
| M6.10 | Duplicate and forbidden operations | Duplicate username is rejected; User cannot edit, lock, reset, or delete another user |
| M6.11 | Empty/invalid user form | Required fields, username format, password rules, role, and confirmation errors are shown without creating a partial account |
| M6.12 | List/search/refresh | User list shows correct role, lock, reset, and name state after each change; refresh does not resurrect stale data |

## Part 2: Automated API coverage already in this repository

These commands use typed clients and capabilities. Do not replace them with
`curl` or one-off HTTP calls.

### A0. Baseline and authorization

```bash
ROBOT_USE_HTTPS=true uv run flex-test inspect
ROBOT_USE_HTTPS=true uv run flex-test crs lockdown --show-failures
ROBOT_USE_HTTPS=true uv run flex-test crs auth-matrix
```

Covers CRS state, HTTPS, public versus protected routes, missing/bad/malformed
bearers, OAuth bad credentials, and under-scoped Auditor/User attempts. Mutation
routes must return 401/403 without valid credentials. GET behavior is checked
according to the CRS contract and current product exceptions.

### A1. Settings API and policy enforcement

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true \
  uv run flex-test crs settings-suite --include-slow
```

The suite covers:

- `GET`, partial `PATCH`, `DELETE`, persistence, baseline restore, and settings
  route authorization for `/auth/settings`.
- `maxNumberOfLoginAttempts`, including lockout and Admin reactivation.
- Minimum password length, special-character enforcement, and their combination.
- `passwordResetTime` when clock control or a safe short expiry is available.
- `idleLogout` inactivity expiry (S6). Standalone probe with no API traffic:

```bash
ROBOT_USE_HTTPS=true uv run flex-test crs idle-logout-inactivity --wait-seconds 65
```

Authenticated API calls do **not** refresh access tokens; the App uses refresh-token
grants for that. The harness uses ROPC only.

- Admin credential gates for update begin, protocol upload, and protocol sign-off.
- The all-three gate combination and one-flag-at-a-time behavior.

Case mapping: `S0` baseline, `S1` login attempts, `S2` length, `S3` special
characters, `S4` combination, `S5` password expiry, `S6` idle logout, `S7`
software update, `S8` protocol upload, `S9` sign-off, `S10` gate matrix, `S11`
persistence/restore, and `S12` route authorization.

### A2. User-management API

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true \
  uv run flex-test crs users-api
```

Covers typed REST calls for create, get-by-username, get-self, profile update,
username rename, role changes, lock, reset flag, password reset, delete,
duplicate username rejection, non-admin write denial, temporary-password
one-use behavior, OAuth token introspection, and cleanup.

It also covers the token matrix required by the manual two-session tests:

| Admin action on target | Existing target token |
| --- | --- |
| Username change | Must be invalidated |
| Role change | Must be invalidated |
| Legal-name-only change | Must remain valid |
| Delete | Must be invalidated |
| Lock | Must be invalidated |
| Password reset | Must be invalidated |

Known product defects currently encoded by the suite: RQA-5950 (self token
after username change) and RQA-5952 (lock does not revoke an existing token).

### A3. Full CRS-on API suite

```bash
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true \
  uv run flex-test crs suite --include-lockdown
```

This combines negative authorization, scoped GET authorization, parameter-free
GET coverage, user-management API coverage, parameterized GET coverage, and
reversible OAuth mutations. It writes `artifacts/crs_on_suite.json`.

For focused coverage:

```bash
ROBOT_USE_HTTPS=true uv run flex-test crs probe-b --as-user flex_test_operator
ALLOW_MUTATIONS=true ROBOT_USE_HTTPS=true uv run flex-test crs probe-c
```

### A4. Audit and log API coverage

```bash
uv run flex-test audit list
uv run flex-test audit download <period-id>
uv run flex-test logs archive
```

This checks audit-period listing and download after audited mutations, archive
availability, and the separation between audit, diagnostic, and protocol-run
records. It does not replace the App/ODD checks for prompts, local download UX,
or hash-chain viewer behavior.

## Coverage closure matrix

| Product experience | Manual | Automated API | Primary source |
| --- | ---: | ---: | --- |
| Settings display, controls, validation, cancel, refresh | Yes | Partial | M0-M4, S0/S11 |
| Login attempts and account lockout | Yes | Yes | M1, S1 |
| Password expiration and complexity | Yes | Yes, expiry may be blocked | M1, S2-S5 |
| Idle logout (inactivity; App refresh out of scope) | Yes | Yes | M1, S6, inactivity CLI |
| Admin credential prompts and gates | Yes | Yes | M2, S7-S10 |
| Documentation and signature prompts | Yes | Partial | M3, Tier C, audit plan |
| Audit download and record content | Yes | Yes for HTTP list/download | M3, A4 |
| Robot storage cleanup | Yes | Not currently covered by CRS suite | M4 |
| Personal account profile | Yes | Yes | M5, users-api |
| User CRUD and roles | Yes | Yes | M6, users-api |
| Cross-session/token invalidation | Yes | Yes | M6, users-api |
| Full CRS authorization surface | Spot-check | Yes | A0, A3 |

The remaining API gap is product-specific storage-threshold behavior and the
full audit-server `requireReasonForInteraction` policy. The latter is tracked
as RQA-5841 because a direct API mutation may bypass the App/ODD reason prompt.
The UI prompt still requires manual validation.

## Recommended execution order

1. M0 baseline and screenshots.
2. A0 lockdown and authorization baseline.
3. M1-M4 settings UI, restoring the baseline after each section.
4. A1 settings suite, including slow cases when the lab permits.
5. M5-M6 account and user-management UI with two sessions.
6. A2 users API and compare every token result with the manual result.
7. M3 audit download checks, then A4.
8. A3 full suite and final baseline verification.

For every failure capture: test ID, client/persona, setting before and after,
UI screenshot, request path/method if known, HTTP status/body from harness
evidence, audit reason, and the relevant Jira issue. Never include passwords,
temporary passwords, access tokens, or private keys in evidence.
