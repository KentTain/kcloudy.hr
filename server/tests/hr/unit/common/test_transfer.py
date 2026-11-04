"""移交目标校验单测（D1：同租户在册校验三分支）"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.common.ctx import Context, clear_context, set_context
from framework.common.exceptions import BadRequestError

from hr.common.transfer import validate_transfer_target

TENANT = "t1"


def _client(user: MagicMock | None, tenants: list) -> MagicMock:
    client = MagicMock()
    client.get_user = AsyncMock(return_value=user)
    client.get_user_tenants = AsyncMock(return_value=tenants)
    return client


@pytest.mark.unit
@pytest.mark.asyncio
class TestValidateTransferTarget:
    async def test_rejects_unknown_user(self):
        set_context(Context(user_id="u-op", tenant_id=TENANT))
        with patch(
            "hr.common.transfer.get_iam_client",
            return_value=_client(None, []),
        ):
            with pytest.raises(BadRequestError, match="不存在或未在册"):
                await validate_transfer_target(MagicMock(), "u-ghost")
        clear_context()

    async def test_rejects_inactive_user(self):
        set_context(Context(user_id="u-op", tenant_id=TENANT))
        disabled = MagicMock(status="disabled")
        with patch(
            "hr.common.transfer.get_iam_client",
            return_value=_client(disabled, []),
        ):
            with pytest.raises(BadRequestError, match="不存在或未在册"):
                await validate_transfer_target(MagicMock(), "u-off")
        clear_context()

    async def test_rejects_cross_tenant_user(self):
        set_context(Context(user_id="u-op", tenant_id=TENANT))
        active = MagicMock(status="active")
        other_tenant = [MagicMock(tenant_id="t-other")]
        with patch(
            "hr.common.transfer.get_iam_client",
            return_value=_client(active, other_tenant),
        ):
            with pytest.raises(BadRequestError, match="不属于当前租户"):
                await validate_transfer_target(MagicMock(), "u-alien")
        clear_context()

    async def test_passes_same_tenant_active_user(self):
        set_context(Context(user_id="u-op", tenant_id=TENANT))
        active = MagicMock(status="active")
        same_tenant = [MagicMock(tenant_id="t-other"), MagicMock(tenant_id=TENANT)]
        with patch(
            "hr.common.transfer.get_iam_client",
            return_value=_client(active, same_tenant),
        ):
            await validate_transfer_target(MagicMock(), "u-peer")
        clear_context()
