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
    Protocols, runs, data files, clientData, lights; parameterized GET fixtures.
    (`flex-test crs-off-b`)

10a. **Run-state preflight for suites**  
    Snapshot / verify / ensure `no-current` vs `current-idle` before Tier A/B/C
    (`orchestration/run_state.py`, `flex-test run-state`). Matrix in
    [crs-testing.md](crs-testing.md).

10b. **Known-state setup + latency**  
    Clear robot-server data, apply Kansas deck, record install/boot/play timings
    for Pyro vs non-Pyro compare. Design: [known-state-and-latency.md](known-state-and-latency.md).
    CLI: `reset-data`, `known-state`, `timing`. Seed-run motion history next.

11. **CRS-off mutating suite**  
    Gated Tier C (`flex-test crs-off-c`); Tier D still mostly install/explicit.

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
