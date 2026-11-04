"""移交目标校验（请假/异动/审批三单据 transfer 端点共用）

移交 = UPDATE 业务归属 owner_id（可变归属列）；目标须为当前租户在册用户，
经 iam_client 双模式校验（单体直调 / 微服务 inner）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.ctx import get_tenant_id
from framework.common.exceptions import BadRequestError


async def validate_transfer_target(session: AsyncSession, user_id: str) -> None:
    """校验移交目标为同租户在册用户（不存在/停用/跨租户均拒绝）"""
    client = get_iam_client()
    user = await client.get_user(session, user_id)
    if not user or user.status != "active":
        raise BadRequestError(f"移交目标用户不存在或未在册: {user_id}")
    tenant_id = get_tenant_id()
    tenants = await client.get_user_tenants(session, user_id)
    if not any(ut.tenant_id == tenant_id for ut in tenants):
        raise BadRequestError("移交目标用户不属于当前租户")
