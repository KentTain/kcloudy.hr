"""绩效评估控制器（批量发起/评分/校准，校准需 hr:perf:calibrate；写操作审计留痕）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.perf import (
    PerfReviewBatchCreate,
    PerfReviewCalibrateUpdate,
    PerfReviewCreateResponse,
    PerfReviewScoreUpdate,
)
from hr.services.perf_review_service import perf_review_service

router = APIRouter()


@router.get("/perf-reviews")
async def list_perf_reviews(
    cycle_id: str | None = None,
    status: str | None = None,
    reviewer_employee_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_review:read")),
):
    result = await perf_review_service.list_reviews(
        session,
        cycle_id=cycle_id,
        status=status,
        reviewer_employee_id=reviewer_employee_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.post("/perf-reviews")
async def create_perf_reviews(
    data: PerfReviewBatchCreate,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_review:write")),
):
    """批量发起评估（scoring 态，周期 × 被评人去重）"""
    result = await perf_review_service.create_reviews(
        session,
        cycle_id=data.cycle_id,
        items=[item.model_dump() for item in data.items],
    )
    await _audit(
        session,
        action="create",
        resource_id=data.cycle_id,
        resource_name=f"批量发起评估 {result['created']} 条",
        operator_id=operator_id,
        detail={"created": result["created"], "skipped": result["skipped"]},
    )
    return ApiResponse.success(data=PerfReviewCreateResponse(**result))


@router.put("/perf-reviews/{review_id}/score")
async def score_perf_review(
    review_id: str,
    data: PerfReviewScoreUpdate,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf_review:write")),
):
    """提交评分（scoring 态；得分+初评评级）"""
    review = await perf_review_service.submit_score(
        session,
        review_id,
        score=data.score,
        rating=data.rating,
        self_score=data.self_score,
    )
    await _audit(
        session,
        action="score",
        resource_id=review_id,
        resource_name=f"评估评分 {data.rating}",
        operator_id=operator_id,
        detail={"score": str(data.score), "rating": data.rating},
    )
    return ApiResponse.success(data=perf_review_service.to_response(review))


@router.put("/perf-reviews/{review_id}/calibrate")
async def calibrate_perf_review(
    review_id: str,
    data: PerfReviewCalibrateUpdate,
    operator_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
    _: None = Depends(require_permission("hr:perf:calibrate")),
):
    """校准评级（calibrating 态，意见必填，留痕操作人/前后评级/时间）"""
    review = await perf_review_service.calibrate(
        session,
        review_id,
        rating=data.rating,
        comment=data.comment,
        operator_user_id=operator_id,
    )
    await _audit(
        session,
        action="calibrate",
        resource_id=review_id,
        resource_name=f"评级校准 {data.rating}",
        operator_id=operator_id,
        detail={"rating": data.rating, "comment": data.comment},
    )
    return ApiResponse.success(data=perf_review_service.to_response(review))


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    resource_id: str,
    resource_name: str,
    operator_id: str,
    detail: dict,
) -> None:
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type=action,
        resource_type="perf_review",
        resource_name=resource_name,
        resource_id=resource_id,
        detail={"operator_id": operator_id, **detail},
    )
