"""合同管理控制器 - 管理端

新签 / 续签（旧区间闭合）/ 终止 / 编辑（备注/提醒开关/附件）。
权限码 hr:contract:read/write/delete。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.response import ApiResponse
from framework.database.dependencies import get_db_session
from iam.dependencies import get_current_user_id, require_permission

from hr.schemas.contract import (
    ContractCreate,
    ContractRenew,
    ContractResponse,
    ContractUpdate,
)
from hr.services.contract_service import contract_service

router = APIRouter()


@router.get("/employees/{employee_id}/contracts")
async def list_contracts(
    employee_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:read")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """员工合同记录卡列表（按起始日倒序）"""
    contracts = await contract_service.list_contracts(session, employee_id)
    return ApiResponse.success(data=contracts)


@router.post("/contracts")
async def create_contract(
    data: ContractCreate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """新签合同（编号租户内唯一）"""
    contract = await contract_service.create_contract(session, data)
    return ApiResponse.success(data=contract)


@router.post("/contracts/{contract_id}/renew")
async def renew_contract(
    contract_id: str,
    data: ContractRenew,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """续签（旧合同区间闭合 + 新合同卡生效）"""
    contract = await contract_service.renew_contract(session, contract_id, data)
    return ApiResponse.success(data=contract)


@router.post("/contracts/{contract_id}/terminate")
async def terminate_contract(
    contract_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """终止合同"""
    contract = await contract_service.terminate_contract(session, contract_id)
    return ApiResponse.success(data=contract)


@router.put("/contracts/{contract_id}")
async def update_contract(
    contract_id: str,
    data: ContractUpdate,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:write")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """合同编辑（备注/到期提醒开关/附件）"""
    contract = await contract_service.update_contract(session, contract_id, data)
    return ApiResponse.success(data=contract)


@router.delete("/contracts/{contract_id}")
async def delete_contract(
    contract_id: str,
    user_id: str = Depends(get_current_user_id),
    _perm: None = Depends(require_permission("hr:contract:delete")),
    session: AsyncSession = Depends(get_db_session),
) -> ApiResponse:
    """删除合同记录"""
    from hr.models import EmployeeContract

    from framework.common.exceptions import ConflictError, NotFoundError

    contract = await session.get(EmployeeContract, contract_id)
    if not contract:
        raise NotFoundError(f"合同 {contract_id} 不存在")
    if contract.status == "active":
        raise ConflictError("生效中的合同不可删除，请先终止")
    await session.delete(contract)
    await session.flush()
    return ApiResponse.success(data={"deleted": contract_id})
