"""渠道 webhook 接收 - inner 面（无认证，HMAC 签名校验兜安全）

渠道服务商投递事件回调入口：验签失败 401 / 渠道停用 403 / 未匹配职位 404。
归集复用 candidate_service.collect_application（幂等）。
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, NotFoundError
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from framework.tenant.context import TenantContext

from hr.integration.errors import (
    IntegrationAuthError,
    IntegrationDisabledError,
)
from hr.services.channel_service import (
    WEBHOOK_SIGNATURE_HEADER,
    channel_service,
)

router = APIRouter(prefix="/inner/v1")


@router.post("/webhooks/{channel}")
async def receive_webhook(
    channel: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    """渠道投递事件接收（签名校验，供渠道回调）"""
    raw_body = await request.body()
    signature = request.headers.get(WEBHOOK_SIGNATURE_HEADER)
    try:
        result = await channel_service.handle_webhook(
            session, channel, raw_body=raw_body, signature=signature
        )
    except IntegrationAuthError:
        return ApiResponse.fail(401, "webhook 签名校验失败")
    except IntegrationDisabledError:
        return ApiResponse.fail(403, "渠道未启用")
    except NotFoundError as exc:
        return ApiResponse.fail(404, str(exc))
    except BadRequestError as exc:
        return ApiResponse.fail(400, str(exc))
    await session.commit()
    TenantContext.clear()
    return ApiResponse.success(data=result)
