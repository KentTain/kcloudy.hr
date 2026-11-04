"""团队工作台控制器（console：团队招聘/我的面试/待我评分，数据按归属自动裁剪）"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from hr.schemas.perf import PerfReviewScoreUpdate
from iam.dependencies import get_current_user_id

from hr.services.self_service_service import self_service_service

router = APIRouter()


@router.get("/team/requisitions")
async def list_team_requisitions(
    page: int = 1,
    page_size: int = 20,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.list_team_requisitions(
        session, user_id, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"], total=result["total"], page=page, page_size=page_size
    )


@router.get("/team/interviews")
async def list_team_interviews(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    items = await self_service_service.list_team_interviews(session, user_id)
    return ApiResponse.success(data=items)


@router.get("/team/reviews")
async def list_team_reviews(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    items = await self_service_service.list_team_reviews(session, user_id)
    return ApiResponse.success(data=items)


@router.put("/team/reviews/{review_id}/score")
async def score_team_review(
    review_id: str,
    data: PerfReviewScoreUpdate,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_db_session),
):
    result = await self_service_service.submit_team_review_score(
        session,
        user_id,
        review_id,
        score=data.score,
        rating=data.rating,
        self_score=data.self_score,
    )
    return ApiResponse.success(data=result)
