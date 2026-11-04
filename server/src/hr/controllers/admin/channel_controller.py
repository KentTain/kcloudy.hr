"""招聘渠道控制器 - 管理端

渠道状态总览 / 手动同步任务化 / 渠道已发布职位。
权限码 hr:channel:read / hr:channel:sync（手动同步）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.ctx import get_tenant_id
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.services.channel_service import channel_service

router = APIRouter()


@router.get("/channels")
async def list_channels(
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:channel:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """渠道清单与状态（凭证状态/同步开关/累计归集数/最近同步）"""
    channels = await channel_service.list_channels(session, get_tenant_id())
    return ApiResponse.success(data=channels)


@router.post("/channels/{channel}/sync")
async def trigger_sync(
    channel: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:channel:sync")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """手动触发候选人拉取（任务化异步执行，返回任务 ID）"""
    task_id = await channel_service.trigger_sync(session, get_tenant_id(), channel)
    return ApiResponse.success(data={"task_id": task_id, "channel": channel})


@router.post("/channels/{channel}/test-connection")
async def test_connection(
    channel: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:channel:sync")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """连通测试：向渠道换取 token 验证凭证（配置缺失/换取失败返回 ok=False）"""
    result = await channel_service.test_connection(session, get_tenant_id(), channel)
    return ApiResponse.success(data=result)


@router.get("/channels/{channel}/postings")
async def list_channel_postings(
    channel: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:channel:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """渠道已发布职位与同步状态"""
    postings = await channel_service.get_channel_postings(
        session, get_tenant_id(), channel
    )
    return ApiResponse.success(
        data=[
            {
                "id": str(p.id),
                "requisition_id": str(p.requisition_id),
                "channel": p.channel,
                "status": p.status,
                "external_post_id": p.external_post_id,
                "published_at": p.published_at,
            }
            for p in postings
        ]
    )
