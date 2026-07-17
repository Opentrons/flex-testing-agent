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

8. **Access-control dual-mode hardening**  
   Optional token attachment, clearer AC-on failure modes, still **no enable**.

9. **Lockdown / mode smoke (deferred)**  
   Blocked until a safe reversible mode API or restore story exists. Do not enable AC in the harness.

10. **User and role research**  
    Document `/auth/users` and scopes from Opentrons source.

11. **Authorization matrix**  
    Deterministic permission probes with AC-on, after restore path is defined.

12. **Build install capability**  
    Select a published robot OS build and install/verify on Kansas (uses release catalog).

13. **Agent capability descriptors**  
    Expand allowlist metadata and validation.

14. **Bounded agent runtime**  
    Optional adapter; harness remains core.

15. **Local web application**  
    Display runs, snapshots, evidence, findings.

## Milestone 1 status

Items 1–7 are implemented in the initial foundation (including release discovery). Next PR should focus on item 8 without enabling access control.
