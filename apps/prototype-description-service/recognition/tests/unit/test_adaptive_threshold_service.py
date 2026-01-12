from unittest.mock import Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from recognition.application.settings.adaptive import AdaptiveThresholdService


@pytest.mark.asyncio
async def test_get_threshold_uses_experiment_variant() -> None:
    session = Mock(spec=AsyncSession)
    service = AdaptiveThresholdService(session)

    result = await service.get_threshold("tenant-alpha", experiment_id="threshold_v2_jan2026")

    assert result.source.startswith("experiment:threshold_v2_jan2026:")
    assert result.threshold in {0.72, 0.68, 0.78}
    assert result.confidence == 1.0


@pytest.mark.asyncio
async def test_get_threshold_falls_back_to_default_on_invalid_tenant() -> None:
    session = Mock(spec=AsyncSession)
    service = AdaptiveThresholdService(session, default_threshold=0.74)

    result = await service.get_threshold("not-a-uuid")

    assert result.threshold == 0.74
    assert result.source == "default"
