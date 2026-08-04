# Development plan

Small, reviewable pull requests. Each PR should be independently understandable.

## Suggested sequence

1. **Repository foundation and tooling**  
   `pyproject.toml`, uv, ruff, mypy, pytest, Makefile, `.env.example`, `.gitignore`.

2. **Configuration and domain models**  
   Settings, snapshot/health/access-control models, risk levels, mutation gates, robot lock.

3. **Basic robot clients**  
   `RobotHttpSession`, health, update health, auth settings GET.

4. **Inspection vertical slice**  
   `FlexRobot`, `inspect_robot`, CLI `flex-test inspect`.

5. **Persistence and evidence**  
   SQLAlchemy models, Alembic migration, evidence store, wiring into inspect.

6. **Scenario runner skeleton**  
   YAML metadata + typed inspect scenario runner.

7. **Flex release catalog (robot-stack)**  
   `flex-test releases`, internal/external latest lanes, version docs.

8. **CRS / access-control dual-mode hardening**  
   Optional token attachment, clearer CRS-on failure modes, still **no enable**.
   See [crs-testing.md](crs-testing.md).

9. **Full HTTP endpoint catalog + CRS-off Tier A**  
   Monorepo-derived `catalog/endpoints.py` (~all methods/paths); CRS-off GET probe
   driven by that catalog (`flex-test probe`).

10. **Domain clients for CRS-off Tier B/C**  
    Done: protocols, runs, data files, clientData, lights, camera, errorRecovery,
    labwareOffsets, maintenance runs; parameterized GET fixtures + `api-suite`.
    (`flex-test crs-off-b|crs-off-c|api-suite`)

10a. **Run-state preflight for suites**  
    Done: snapshot / verify / ensure `no-current` vs `current-idle` before
    Tier A/B/C (`orchestration/run_state.py`, `flex-test run-state`). Matrix in
    [crs-testing.md](crs-testing.md).

10b. **Known-state setup + latency + seed-runs**  
    Done: clear robot-server data, Kansas deck, seed inventory (incl. pause/
    failed/`group_steps` annotations, scripted LPC), install/boot timings.
    Design: [known-state-and-latency.md](known-state-and-latency.md).

11. **CRS-off mutating suite expansion**  
    Tier C sample done (`flex-test crs-off-c`, 7 reversible steps). Expand over
    remaining reversible catalog; Tier D still mostly install/explicit.

12. **User / OAuth clients (CRS-on prep)**  
    Document and implement `/auth/users`, `POST /oauth2/token`, scopes from
    `server_utils.auth.scopes`.

13. **CRS-on authorization matrix (deferred)**  
    Deterministic permission probes with CRS on, after restore path
    ([EXEC-2176](https://opentrons.atlassian.net/browse/EXEC-2176)).

14. **Build install capability**  
    Select a published robot OS build and install/verify on Kansas (uses release catalog).
    (Already largely landed via `flex-test put`.)

15. **Agent capability descriptors**  
    Expand allowlist metadata and validation.

16. **Bounded agent runtime**  
    Optional adapter; harness remains core.

17. **Local web application**  
    Display runs, snapshots, evidence, findings.

## Milestone 1 status

Items 1–7 and install/release tooling are in place. Item 9 (endpoint catalog +
CRS-off GET Tier A) is the current CRS focus. Item 8/10–13 remain; do not enable
CRS from the harness.
