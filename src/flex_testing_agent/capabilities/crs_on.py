"""CRS-on bootstrap capabilities (HTTPS trust, user provisioning)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from flex_testing_agent.capabilities.descriptor import CapabilityDescriptor
from flex_testing_agent.clients.errors import RobotApiError
from flex_testing_agent.clients.oauth import OAuthClient
from flex_testing_agent.clients.users import UsersClient
from flex_testing_agent.config.settings import Settings
from flex_testing_agent.fixtures.crs_users import (
    CrsUserFixture,
    CrsUserFixtureFile,
    load_crs_user_fixtures,
    resolve_bootstrap_admin_credentials,
    resolve_fixture_password,
)
from flex_testing_agent.models.access_control import AccessControlState
from flex_testing_agent.models.risk import RiskLevel
from flex_testing_agent.orchestration.gates import ensure_mutation_allowed
from flex_testing_agent.robot_certs.bootstrap import TrustCaResult, trust_robot_ca
from flex_testing_agent.robots.flex import FlexRobot, _effective_user_notes

TRUST_CA = CapabilityDescriptor(
    name="crs_trust_ca",
    description=(
        "Fetch robot encrypted CA over HTTP, decrypt with CRS service password, "
        "save PEM + registry for HTTPS (:32313)."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    evidence_produced=["crs_trust_ca.json"],
)

PROVISION_USERS = CapabilityDescriptor(
    name="crs_provision_users",
    description=(
        "Create CRS test users from fixtures/crs_users.yaml "
        "(admin/user/auditor/service)."
    ),
    risk_level=RiskLevel.REVERSIBLE_MUTATION,
    evidence_produced=["crs_provision_users.json"],
)

ENABLE_CRS = CapabilityDescriptor(
    name="crs_enable",
    description=(
        "Create bootstrap admin, PATCH accessControlEnabled=true (one-way), "
        "and provision enabled fixture users."
    ),
    risk_level=RiskLevel.DISRUPTIVE,
    evidence_produced=["crs_enable.json"],
)


@dataclass(frozen=True, slots=True)
class ProvisionUserOutcome:
    username: str
    account_type: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class ProvisionUsersResult:
    outcomes: list[ProvisionUserOutcome]

    @property
    def ok_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.ok)

    @property
    def fail_count(self) -> int:
        return sum(1 for outcome in self.outcomes if not outcome.ok)


async def run_trust_ca(
    robot: FlexRobot,
    *,
    password: str | None = None,
) -> TrustCaResult:
    """Install robot CA trust for HTTPS (see docs/crs-on-setup.md)."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=TRUST_CA.risk_level,
        capability_name=TRUST_CA.name,
    )
    host = robot.settings.require_robot_host()
    result = await trust_robot_ca(robot.settings, host=host, password=password)
    robot.raw_evidence["crs_trust_ca"] = {
        "robot_host": result.robot_host,
        "robot_serial": result.robot_serial,
        "robot_name": result.robot_name,
        "pem_path": result.pem_path,
        "registry_path": result.registry_path,
        "https_ok": result.https_ok,
    }
    return result


@dataclass(frozen=True, slots=True)
class EnableCrsResult:
    access_control_state: AccessControlState
    bootstrap_username: str
    bootstrap_created: bool
    crs_enabled: bool
    provision: ProvisionUsersResult


async def run_enable_crs(
    robot: FlexRobot,
    *,
    confirm_one_way: bool,
    skip_provision: bool = False,
    fixture_path: str | None = None,
) -> EnableCrsResult:
    """Enable CRS on the robot with the harness bootstrap admin."""
    if not confirm_one_way:
        raise ValueError(
            "CRS enable is one-way. Pass confirm_one_way=True (CLI: --confirm-one-way)."
        )
    ensure_mutation_allowed(
        robot.settings,
        risk_level=ENABLE_CRS.risk_level,
        capability_name=ENABLE_CRS.name,
    )

    fixture_file = (
        load_crs_user_fixtures()
        if fixture_path is None
        else load_crs_user_fixtures(Path(fixture_path))
    )
    bootstrap_username, bootstrap_password = resolve_bootstrap_admin_credentials(
        fixture_file,
        robot.settings,
    )
    bootstrap = fixture_file.require_bootstrap_admin()

    status = await robot.auth_settings.detect_access_control()
    already_enabled = status.state == AccessControlState.ENABLED
    bootstrap_created = False
    crs_enabled = already_enabled

    users = UsersClient(robot.session)
    provision_result = ProvisionUsersResult(outcomes=[])

    if not already_enabled:
        try:
            await users.create_user(
                username=bootstrap_username,
                password=bootstrap_password,
                full_name=bootstrap.full_name,
                account_type="admin",
            )
            bootstrap_created = True
        except RobotApiError as exc:
            if exc.status_code not in (400, 409):
                raise

        if not skip_provision:
            provision_result = await run_provision_users(
                robot,
                fixture_path=fixture_path,
                replace=False,
                access_token=None,
                fixture_file=fixture_file,
            )

        await robot.auth_settings.enable_access_control()
        crs_enabled = True
    elif not skip_provision:
        oauth = OAuthClient(robot.session)
        token = await oauth.get_token(bootstrap_username, bootstrap_password)
        provision_result = await run_provision_users(
            robot,
            fixture_path=fixture_path,
            replace=False,
            access_token=token.access_token,
            fixture_file=fixture_file,
        )

    result = EnableCrsResult(
        access_control_state=AccessControlState.ENABLED,
        bootstrap_username=bootstrap_username,
        bootstrap_created=bootstrap_created,
        crs_enabled=crs_enabled,
        provision=provision_result,
    )
    robot.raw_evidence["crs_enable"] = {
        "bootstrap_username": bootstrap_username,
        "bootstrap_created": bootstrap_created,
        "crs_enabled": crs_enabled,
        "already_enabled": already_enabled,
        "provision_ok": provision_result.ok_count,
        "provision_failed": provision_result.fail_count,
    }
    return result


def _resolve_admin_credentials(settings: Settings) -> tuple[str | None, str | None]:
    fixture_file = load_crs_user_fixtures()
    username, password = resolve_bootstrap_admin_credentials(fixture_file, settings)
    return username, password


async def _admin_access_token(robot: FlexRobot) -> str | None:
    username, password = _resolve_admin_credentials(robot.settings)
    if not username or not password:
        return None
    oauth = OAuthClient(robot.session)
    token = await oauth.get_token(username, password)
    return token.access_token


async def _provision_one(
    robot: FlexRobot,
    users: UsersClient,
    fixture: CrsUserFixture,
    *,
    access_token: str | None,
    password: str,
    replace: bool,
) -> ProvisionUserOutcome:
    if replace and access_token is not None:
        await users.delete_user_if_exists(
            fixture.username,
            access_token=access_token,
        )
    if not replace:
        try:
            if access_token:
                await users.get_user_by_username(
                    fixture.username,
                    access_token=access_token,
                )
                return ProvisionUserOutcome(
                    username=fixture.username,
                    account_type=fixture.account_type,
                    ok=True,
                    detail="already exists",
                )
        except RobotApiError as exc:
            if exc.status_code not in (404, 401, 403):
                return ProvisionUserOutcome(
                    username=fixture.username,
                    account_type=fixture.account_type,
                    ok=False,
                    detail=str(exc),
                )
    try:
        profile = await users.create_user(
            username=fixture.username,
            password=password,
            full_name=fixture.full_name,
            account_type=fixture.account_type,
            access_token=access_token,
        )
        return ProvisionUserOutcome(
            username=profile.user_name,
            account_type=profile.account_type,
            ok=True,
            detail="created",
        )
    except RobotApiError as exc:
        if exc.status_code == 409:
            return ProvisionUserOutcome(
                username=fixture.username,
                account_type=fixture.account_type,
                ok=True,
                detail="already exists (409)",
            )
        return ProvisionUserOutcome(
            username=fixture.username,
            account_type=fixture.account_type,
            ok=False,
            detail=str(exc),
        )


async def run_provision_users(
    robot: FlexRobot,
    *,
    fixture_path: str | None = None,
    replace: bool = False,
    access_token: str | None = None,
    fixture_file: CrsUserFixtureFile | None = None,
) -> ProvisionUsersResult:
    """Create enabled CRS fixture users on the robot."""
    ensure_mutation_allowed(
        robot.settings,
        risk_level=PROVISION_USERS.risk_level,
        capability_name=PROVISION_USERS.name,
    )
    loaded = fixture_file or (
        load_crs_user_fixtures()
        if fixture_path is None
        else load_crs_user_fixtures(Path(fixture_path))
    )
    if access_token is not None:
        token: str | None = access_token
    else:
        status = await robot.auth_settings.detect_access_control()
        token = (
            await _admin_access_token(robot)
            if status.state == AccessControlState.ENABLED
            else None
        )
    # provision-users often starts with an unauthenticated FlexRobot, then mints
    # a bearer for create_user. Session notes are only wired when the session is
    # built with a token; without them, CRS returns HTTP 451 on POST /auth/users.
    if token:
        robot.session.set_access_token(token)
        robot.session.set_user_notes(
            _effective_user_notes(robot.settings, access_token=token)
        )
    users = UsersClient(robot.session)
    outcomes: list[ProvisionUserOutcome] = []

    for fixture in loaded.enabled_users():
        password = resolve_fixture_password(fixture, defaults=loaded.defaults)
        if not password:
            outcomes.append(
                ProvisionUserOutcome(
                    username=fixture.username,
                    account_type=fixture.account_type,
                    ok=False,
                    detail=(
                        "missing password: set CRS_FIXTURE_PASSWORD or "
                        f"CRS_PASSWORD_{fixture.env_suffix.upper()}"
                    ),
                )
            )
            continue
        outcomes.append(
            await _provision_one(
                robot,
                users,
                fixture,
                access_token=token,
                password=password,
                replace=replace,
            )
        )

    result = ProvisionUsersResult(outcomes=outcomes)
    robot.raw_evidence["crs_provision_users"] = {
        "ok": result.ok_count,
        "failed": result.fail_count,
        "outcomes": [asdict(outcome) for outcome in outcomes],
    }
    return result
