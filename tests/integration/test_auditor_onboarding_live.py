"""Live robot test: auditor temp-password onboarding and post-rotation login."""

from __future__ import annotations

import pytest

from flex_testing_agent.capabilities.user_management_suite import (
    run_auditor_onboarding_retest,
)
from flex_testing_agent.config.settings import get_settings
from flex_testing_agent.fixtures.user_management import EphemeralUserSpec


@pytest.mark.requires_robot
@pytest.mark.mutates_robot
@pytest.mark.asyncio
async def test_auditor_onboarding_temp_password_relogin() -> None:
    """Requires KansasFLEX with CRS on and ALLOW_MUTATIONS=true."""
    settings = get_settings()
    if not settings.allow_mutations:
        pytest.skip("ALLOW_MUTATIONS=false")

    result = await run_auditor_onboarding_retest(
        settings,
        spec=EphemeralUserSpec.auditor_default(),
    )
    assert result.ok, result.detail
