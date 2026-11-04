"""发薪批次控制器 - 管理端

批次创建（异步试算）/ 明细矩阵 / 人工修正（draft）/ 确认（hr:payroll:confirm
锁死）/ 发放 / 取消 / 导出（写审计）。
"""

import base64

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.salary import PayrollEntryUpdate, PayrollRunCreate
from hr.services.payroll_service import payroll_service

router = APIRouter()


@router.get("/payroll-runs")
async def list_payroll_runs(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """发薪批次列表（期间倒序；hrViewer 仅见总额与人数聚合口径）"""
    result = await payroll_service.list_runs(
        session, status=status, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.post("/payroll-runs")
async def create_payroll_run(
    data: PayrollRunCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """创建批次（期间租户唯一）并异步试算（返回 task_id）"""
    result = await payroll_service.create_run(session, data.period)
    return ApiResponse.success(
        data={
            "run": payroll_service.to_run_response(result["run"]).model_dump(),
            "task_id": result["task_id"],
        }
    )


@router.get("/payroll-runs/{run_id}")
async def get_payroll_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """批次详情"""
    run = await payroll_service.get_run(session, run_id)
    return ApiResponse.success(data=payroll_service.to_run_response(run).model_dump())


@router.get("/payroll-runs/{run_id}/entries")
async def list_payroll_entries(
    run_id: str,
    page: int = 1,
    page_size: int = 50,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """批次明细分页（员工 × 薪酬项行；矩阵列由薪酬项字典动态生成）"""
    result = await payroll_service.list_entries(
        session, run_id, page=page, page_size=page_size
    )
    return ApiResponse.paginated(
        data=result["items"],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.put("/payroll-runs/{run_id}/entries/{entry_id}")
async def update_payroll_entry(
    run_id: str,
    entry_id: str,
    data: PayrollEntryUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """明细人工修正（仅 draft 态；金额修改须填备注留痕）"""
    entry = await payroll_service.update_entry(
        session,
        run_id,
        entry_id,
        amount=data.amount,
        note=data.note,
    )
    return ApiResponse.success(data=payroll_service.to_entry_response(entry).model_dump())


@router.post("/payroll-runs/{run_id}/confirm")
async def confirm_payroll_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:confirm")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """确认批次（明细锁死；写审计）"""
    run = await payroll_service.confirm_run(session, run_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="confirm",
        resource_type="payroll_run",
        resource_name=f"发薪批次 {run.period}",
        resource_id=run_id,
        detail={"operator_id": user_id, "period": run.period},
    )
    return ApiResponse.success(data=payroll_service.to_run_response(run).model_dump())


@router.post("/payroll-runs/{run_id}/pay")
async def pay_payroll_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """标记发放（生成个人薪酬单，员工自助可查；写审计）"""
    run = await payroll_service.pay_run(session, run_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="pay",
        resource_type="payroll_run",
        resource_name=f"发薪批次 {run.period}",
        resource_id=run_id,
        detail={
            "operator_id": user_id,
            "period": run.period,
            "total_amount": float(run.total_amount) if run.total_amount else None,
            "employee_count": run.employee_count,
        },
    )
    return ApiResponse.success(data=payroll_service.to_run_response(run).model_dump())


@router.post("/payroll-runs/{run_id}/cancel")
async def cancel_payroll_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """取消批次（已发放不可取消；写审计）"""
    run = await payroll_service.cancel_run(session, run_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="cancel",
        resource_type="payroll_run",
        resource_name=f"发薪批次 {run.period}",
        resource_id=run_id,
        detail={"operator_id": user_id, "period": run.period},
    )
    return ApiResponse.success(data=payroll_service.to_run_response(run).model_dump())


@router.get("/payroll-runs/{run_id}/export")
async def export_payroll_run(
    run_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:payroll:export")),
    session: AsyncSession = Depends(get_db_session),
):
    """标准代发文件导出（工号/姓名/证件号/开户行/银行卡号/应发/实发/期间，xlsx 单 sheet）。

    仅 confirmed/paid 态可导；证件号/银行卡解密明文（敏感导出），必写审计。
    """
    filename, content = await payroll_service.export_run(session, run_id)
    run = await payroll_service.get_run(session, run_id)
    await get_iam_client().create_audit_log(
        session,
        business_domain="hr",
        operation_type="export",
        resource_type="payroll_run",
        resource_name=f"发薪批次 {run.period} 标准代发导出",
        resource_id=run_id,
        detail={
            "operator_id": user_id,
            "period": run.period,
            "sensitive_export": True,
            "filename": filename,
        },
    )
    return ApiResponse.success(
        data={"filename": filename, "content_base64": base64.b64encode(content).decode()}
    )
