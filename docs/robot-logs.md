# Robot logs (Flex)

**SSOT for humans and agents.** Three product log families live on the robot.
They answer different questions. Do not conflate them with harness-local
transcripts under `artifacts/serial/` ([serial-console.md](serial-console.md)).

Source notes: internal engineering summary (Slack / Authorship + EXEC). Deeper
audit design: [Audit Logging (PER)](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5433294945/Audit+Logging).
CRS context: [crs-testing.md](crs-testing.md).

## Quick chooser

| You need… | Use |
|-----------|-----|
| “Who changed what / who ran this protocol and why?” (CRS on) | **Audit logs** |
| “Send us the logs” for a bug, HTTP trace, CAN, ODD, deep errors | **Diagnostic logs** |
| Command-by-command protocol timeline for app / ODD run UI | **Protocol run logs** |
| Bootloader / kernel / root shell while network is down | **FTDI serial** ([serial-console.md](serial-console.md)) |
| What *this harness* captured over the FTDI cable today | `artifacts/serial/` |

```text
                    ┌─────────────────────┐
                    │   Operator / agent  │
                    └──────────┬──────────┘
           ┌───────────────────┼───────────────────┐
           ▼                   ▼                   ▼
    Audit logs            Diagnostic          Protocol run
    (CRS only,            logs                logs
     signed periods)      (“usual” support)   (run UI / commands)
           │                   │                   │
           └───────────────────┴───────────────────┘
                               │
                    Robot HTTP / UI export
                               │
              FTDI serial (kernel + shell) ──► artifacts/serial/
```

## 1. Audit logs (CRS)

**What:** Composite, **cryptographically signed** packages produced only when
**CRS is active** (`accessControlEnabled`). Built for non-repudiation / compliance
style questions (“who did this?”), not day-to-day debug.

**Composite contents:**

| Piece | Role |
|-------|------|
| User action log | Every person-driven action that caused a change |
| Protocol run log(s) | Runlog of any protocol that ran in the period |
| Robot identity file | Identifies the robot for the package |
| Signing public key | Verifies the robot’s signature on the package |

**Periods:**

- Logs are grouped into **periods**.
- A period **ends** when (1) the robot **boots**, or (2) a **protocol ends**.
- A new period **starts** as soon as one ends.
- There is **always** an active period.
- Packages can be **downloaded at any time**.

**When they exist:** Only with CRS on. CRS-off lab robots will not have this
stream.

**Example questions:** Who ran this protocol and why? What user actions happened
before a failure in a CRS-on lab?

**Harness notes:** Typed client `clients/audit.py`; CLI:

```bash
uv run flex-test audit list
uv run flex-test audit download <period-id>
```

Downloads land under `ARTIFACT_DIRECTORY/audit/`. Catalog lists audit-server
routes in [`catalog/endpoints.py`](../src/flex_testing_agent/catalog/endpoints.py).
Hash-chain verification in the white-label Log File Viewer is product, not this
harness. Plan: [crs-audit-logs.yaml](test-suggestions/crs-audit-logs.yaml).
Never invent ad-hoc URLs.

## 2. Diagnostic logs

**What:** The logs people usually mean when they say “pull / send robot logs.”
Operational and developer breadcrumbs across subsystems.

**Typical contents:**

- Automated access-style logging (for example every HTTP request)
- Error reports (user-visible and invisible / no UI outcome)
- Deeper error detail than the UI shows
- Ad-hoc developer logging
- Multiple **specific** log streams by endpoint / subsystem (examples called out
  in product discussion: robot-server, CAN bus, ODD, and similar)

**Example questions:** Why did this API call 500? What did robot-server log
around the fault? Any CAN / ODD noise correlating with a hang?

**Harness notes:** Health payloads historically advertise paths like
`/logs/api.log`, `/logs/serial.log`, `/logs/server.log`; catalog has
`GET /logs/{log_identifier}`. Download via:

```bash
uv run flex-test logs list
uv run flex-test logs archive
```

Archives land under `ARTIFACT_DIRECTORY/logs/<UTC-stamp>-<host>/` with
`manifest.json`. Soft-skips missing identifiers (404). Typed client:
`clients/logs.py`; capability: `capabilities/archive_logs.py`.

## 3. Protocol run logs

**What:** The document of **every command** in a protocol run. Feeds the
ongoing-run UI in the app and on the ODD.

**May also include:** Protocol source and RTP (runtime parameter) files.

**Example questions:** Which command was current when the run paused? What was
the command sequence for this `runId`?

**Harness notes:** Overlaps HTTP run/command surfaces already used by CRS-off
suites (`/runs/...`, commands, annotations). This is **not** the CRS audit
package, even though audit periods embed a runlog when a protocol ran.

## Related but different

| Surface | Not a product “log package” | Doc |
|---------|----------------------------|-----|
| FTDI serial console | Live kernel printk + root shell; always available from boot | [serial-console.md](serial-console.md) |
| Harness serial transcripts | Local copies under `ARTIFACT_DIRECTORY/serial/` (per-run + daily) | same |
| Robot `serial.log` via `/logs/...` | On-robot serial/diagnostic file name; do not confuse with FTDI harness tees | Diagnostic logs above |

## For agents

| Do | Do not |
|----|--------|
| Pick the log family from the chooser table before fetching anything | Call every `/logs/*` and `/audit/*` path “the logs” interchangeably |
| Assume audit packages exist only when CRS is on | Expect signed audit periods on CRS-off KansasFLEX by default |
| Use diagnostic logs for support-style debugging | Treat protocol run command lists as a substitute for diagnostic dumps |
| After live `seed-runs` / `api-suite` / install verification, run `flex-test logs archive` and review | Skip log archive after a verification pass that should feed an RQA epic |
| Attach focused log evidence to every bug filed from the review | File log-review bugs with summary only and no excerpts on the ticket |
| Save FTDI sessions to `artifacts/serial/` for boot / no-network cases | Invent parallel log download stacks outside clients → capabilities → CLI |
| Cite this doc + PER Audit Logging when extending harness coverage | Enable CRS from the harness to “get audit logs” |

### Post-suite archive and review (required)

After `seed-runs`, `api-suite`, or install verification on KansasFLEX:

1. `uv run flex-test logs archive`
2. Note related FTDI paths under `artifacts/serial/` in the review (do not confuse with robot `serial.log`)
3. Scan archived text for: `ERROR`, `CRITICAL`, `Traceback`, `Exception`, `Application startup failed`, `CommunicationError`, unexpected Pyro/hardware-api activity when subprocess flags are off, clustered 5xx after `/health` recovered
4. Write `review.md` beside the archive (clean vs suspects, paths, timestamps)
5. If clear product defects and the user named a parent epic: create RQA **Bugs** with that parent; otherwise summarize in chat / epic comment
6. **Always attach evidence to each filed bug**: focused `evidence-<KEY>/` (+ zip) with excerpts, `review.md`, and `manifest.json`. Prefer Jira file attachments; if binary upload is unavailable, paste the focused excerpts into an issue comment and cite the local pack path. Do not leave log-review bugs without log text on the ticket.

Full agent checklist: `.cursor/skills/operate-kansasflex/SKILL.md`.

## Related

- [crs-testing.md](crs-testing.md) (CRS on/off, remote-access carveout)
- [serial-console.md](serial-console.md) (FTDI + harness transcripts)
- [safety-model.md](safety-model.md)
- [Audit Logging (PER)](https://opentrons.atlassian.net/wiki/spaces/PER/pages/5433294945/Audit+Logging)
- Skill: `.cursor/skills/operate-kansasflex/SKILL.md`
