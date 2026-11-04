"""合同服务：新签 / 续签（旧区间闭合）/ 终止 / 编辑 / 到期扫描"""

from datetime import date, timedelta

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, EmployeeContract
from hr.schemas.contract import (
    ContractCreate,
    ContractRenew,
    ContractResponse,
    ContractUpdate,
)

_logger = logger.bind(name=__name__)


class ContractService:
    """员工合同业务"""

    async def list_contracts(
        self, session: AsyncSession, employee_id: str
    ) -> list[ContractResponse]:
        result = await session.execute(
            select(EmployeeContract)
            .where(EmployeeContract.employee_id == employee_id)
            .order_by(EmployeeContract.start_date.desc())
        )
        return [
            ContractResponse.model_validate(c) for c in result.scalars().all()
        ]

    async def create_contract(
        self, session: AsyncSession, data: ContractCreate
    ) -> ContractResponse:
        """新签合同（编号租户内唯一；起止区间校验）"""
        await self._get_employee(session, data.employee_id)
        self._validate_dates(data.start_date, data.end_date)
        await self._ensure_no_free(session, data.contract_no)

        contract = EmployeeContract(
            employee_id=data.employee_id,
            contract_no=data.contract_no,
            contract_type=data.contract_type,
            start_date=data.start_date,
            end_date=data.end_date,
            company=data.company,
            signed_date=data.signed_date,
            expiry_remind=data.expiry_remind,
            attachment=data.attachment,
            remark=data.remark,
        )
        session.add(contract)
        await session.flush()
        _logger.info(f"合同新签: {data.contract_no} employee={data.employee_id}")
        return ContractResponse.model_validate(contract)

    async def renew_contract(
        self, session: AsyncSession, contract_id: str, data: ContractRenew
    ) -> ContractResponse:
        """续签：旧合同区间闭合（end_date=新合同起始日前一天）+ 新合同卡生效"""
        old = await self._get(session, contract_id)
        if old.status != "active":
            raise ConflictError("仅生效中的合同可续签")
        self._validate_dates(data.start_date, data.end_date)
        if data.start_date <= old.start_date:
            raise BadRequestError("新合同起始日须晚于原合同起始日")
        await self._ensure_no_free(session, data.contract_no)

        new_end = data.start_date - timedelta(days=1)
        old.end_date = new_end
        if new_end < date.today():
            old.status = "expired"

        contract = EmployeeContract(
            employee_id=old.employee_id,
            contract_no=data.contract_no,
            contract_type=data.contract_type,
            start_date=data.start_date,
            end_date=data.end_date,
            company=data.company or old.company,
            signed_date=data.signed_date,
            expiry_remind=data.expiry_remind,
            attachment=data.attachment,
            remark=data.remark,
        )
        session.add(contract)
        await session.flush()
        _logger.info(f"合同续签: {old.contract_no} -> {data.contract_no}")
        return ContractResponse.model_validate(contract)

    async def terminate_contract(self, session: AsyncSession, contract_id: str) -> ContractResponse:
        contract = await self._get(session, contract_id)
        if contract.status != "active":
            raise ConflictError("仅生效中的合同可终止")
        contract.status = "terminated"
        await session.flush()
        _logger.info(f"合同终止: {contract.contract_no}")
        return ContractResponse.model_validate(contract)

    async def update_contract(
        self, session: AsyncSession, contract_id: str, data: ContractUpdate
    ) -> ContractResponse:
        contract = await self._get(session, contract_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in updates.items():
            setattr(contract, field, value)
        await session.flush()
        return ContractResponse.model_validate(contract)

    # ── 内部工具 ──

    async def _get(self, session: AsyncSession, contract_id: str) -> EmployeeContract:
        contract = await session.get(EmployeeContract, contract_id)
        if not contract:
            raise NotFoundError(f"合同 {contract_id} 不存在")
        return contract

    async def _get_employee(self, session: AsyncSession, employee_id: str) -> Employee:
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        return employee

    async def _ensure_no_free(self, session: AsyncSession, contract_no: str) -> None:
        result = await session.execute(
            select(EmployeeContract).where(EmployeeContract.contract_no == contract_no)
        )
        if result.scalar_one_or_none():
            raise ConflictError(f"合同编号 {contract_no} 已存在")

    @staticmethod
    def _validate_dates(start_date: date, end_date: date | None) -> None:
        if end_date is not None and end_date <= start_date:
            raise BadRequestError("合同截止日须晚于起始日")


contract_service = ContractService()
