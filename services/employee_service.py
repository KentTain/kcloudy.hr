"""员工服务：花名册 / 入职建档 / 详情 / 编辑 / 统计 / 开通账号 / 批量导入"""

import secrets
import string
from datetime import date

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.clients.iam_client import get_iam_client
from framework.common.ctx import get_user_id
from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError
from framework.utils.crypto import CryptoError, decrypt, encrypt

from hr.models import (
    Employee,
    EmployeeChange,
    Position,
)
from hr.schemas.employee import (
    AccountOpenResponse,
    EmployeeCreate,
    EmployeeDetailResponse,
    EmployeeImportResponse,
    EmployeeImportRowResult,
    EmployeeStatsResponse,
    EmployeeUpdate,
)
from hr.services.change_service import change_service
from hr.services.eav_service import eav_service

_logger = logger.bind(name=__name__)

# 证件号/银行卡掩码形态：保留前 3 后 4
_MASK_KEEP_HEAD = 3
_MASK_KEEP_TAIL = 4


def mask_sensitive_number(plain: str | None) -> str | None:
    """证件号/银行卡掩码：保留前 3 后 4，中间星号。"""
    if not plain:
        return None
    if len(plain) <= _MASK_KEEP_HEAD + _MASK_KEEP_TAIL:
        return "*" * len(plain)
    return (
        plain[:_MASK_KEEP_HEAD]
        + "*" * (len(plain) - _MASK_KEEP_HEAD - _MASK_KEEP_TAIL)
        + plain[-_MASK_KEEP_TAIL:]
    )


def generate_initial_password(length: int = 12) -> str:
    """生成初始密码（大小写 + 数字 + 符号，满足平台密码强度校验）。"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)
        ):
            return password


class EmployeeService:
    """员工主档业务"""

    # ── 花名册 ──

    async def list_employees(
        self,
        session: AsyncSession,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        org_id: str | None = None,
        status: str | None = None,
        position_id: str | None = None,
        job_level: str | None = None,
    ) -> tuple[list[Employee], int]:
        """员工分页筛选；已离职默认不展示（需显式选择状态筛选查看）。"""
        conditions = []
        if org_id:
            org_ids = await self.expand_org_ids(session, org_id)
            conditions.append(Employee.org_id.in_(org_ids))
        if status:
            conditions.append(Employee.status == status)
        else:
            conditions.append(Employee.status != "offboarded")
        if position_id:
            conditions.append(Employee.position_id == position_id)
        if job_level:
            conditions.append(Employee.job_level == job_level)
        if keyword:
            like = f"%{keyword}%"
            conditions.append(
                or_(
                    Employee.employee_no.ilike(like),
                    Employee.name.ilike(like),
                    Employee.phone.ilike(like),
                )
            )

        base = select(Employee).where(*conditions)
        total = (
            await session.execute(select(func.count(Employee.id)).where(*conditions))
        ).scalar_one()

        result = await session.execute(
            base.order_by(Employee.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def expand_org_ids(self, session: AsyncSession, org_id: str) -> list[str]:
        """org_id 含子组织语义：经 iam 组织树拍平展开。"""
        tenant_id = get_tenant_id_safe()
        tree = await get_iam_client().get_organization_tree(session, tenant_id)
        flat: dict[str, list[str]] = {}

        def walk(nodes: list[dict]) -> None:
            for node in nodes:
                flat.setdefault(node["parent_id"], []).append(node["id"])
                walk(node.get("children") or [])

        walk(tree)
        # 按树收集 org_id 及全部后代
        collected: set[str] = set()
        stack = [org_id]
        while stack:
            current = stack.pop()
            if current in collected:
                continue
            collected.add(current)
            stack.extend(flat.get(current, []))
        return list(collected)

    async def get_stats(
        self, session: AsyncSession, org_id: str | None = None
    ) -> EmployeeStatsResponse:
        """统计卡口径：在编=probation+regular；试用=probation；本月新入职=当月 hire_date；
        离职率=近 12 个月离职人数/平均在编人数。"""
        today = date.today()
        month_start = today.replace(day=1)
        year_ago = today.replace(year=today.year - 1)

        async def scoped_count(stmt):
            result = await session.execute(stmt)
            return result.scalar_one()

        active_conds = [Employee.status.in_(["probation", "regular"])]
        org_filter = None
        if org_id:
            org_ids = await self.expand_org_ids(session, org_id)
            org_filter = Employee.org_id.in_(org_ids)
            active_conds.append(org_filter)

        active_count = await scoped_count(
            select(func.count(Employee.id)).where(*active_conds)
        )
        probation_count = await scoped_count(
            select(func.count(Employee.id)).where(
                *active_conds, Employee.status == "probation"
            )
        )
        month_hired_count = await scoped_count(
            select(func.count(Employee.id)).where(
                *active_conds,
                Employee.hire_date >= month_start,
            )
        )
        offboarded_conds = [Employee.status == "offboarded", Employee.offboard_date >= year_ago]
        if org_filter is not None:
            offboarded_conds.append(org_filter)
        offboarded_12m = await scoped_count(
            select(func.count(Employee.id)).where(*offboarded_conds)
        )

        turnover_rate = round(offboarded_12m / active_count, 4) if active_count else 0.0
        return EmployeeStatsResponse(
            active_count=active_count,
            probation_count=probation_count,
            month_hired_count=month_hired_count,
            turnover_rate=turnover_rate,
        )

    # ── 建档 / 详情 / 编辑 / 删除 ──

    async def create_employee(
        self, session: AsyncSession, data: EmployeeCreate
    ) -> Employee:
        """入职建档：自动取号、加密敏感字段、写 hire 异动流水、保存扩展属性。"""
        if data.position_id:
            await self._ensure_position_selectable(session, data.position_id)

        employee_no = await self._generate_employee_no(session)
        employee = Employee(
            employee_no=employee_no,
            name=data.name,
            gender=data.gender,
            birth_date=data.birth_date,
            id_card_enc=self._encrypt_sensitive(data.id_card, "证件号"),
            bank_card_enc=self._encrypt_sensitive(data.bank_card, "银行卡号"),
            bank_name=data.bank_name,
            phone=data.phone,
            work_email=data.work_email,
            org_id=data.org_id,
            position_id=data.position_id,
            job_level=data.job_level,
            status=data.status,
            hire_date=data.hire_date,
        )
        session.add(employee)
        await session.flush()

        if data.attribute_values:
            await eav_service.save_employee_attributes(
                session, employee.id, data.attribute_values
            )

        await change_service.record_change(
            session,
            employee=employee,
            change_type="hire",
            before_data=None,
            after_data=self._snapshot(employee),
            effective_date=data.hire_date,
        )
        _logger.info(f"员工建档完成: {employee.employee_no} {employee.name}")
        return employee

    async def get_employee(self, session: AsyncSession, employee_id: str) -> Employee:
        employee = await session.get(Employee, employee_id)
        if not employee:
            raise NotFoundError(f"员工 {employee_id} 不存在")
        return employee

    async def get_employee_by_user_id(
        self, session: AsyncSession, user_id: str
    ) -> Employee:
        result = await session.execute(
            select(Employee).where(Employee.user_id == user_id)
        )
        employee = result.scalar_one_or_none()
        if not employee:
            raise NotFoundError(f"用户 {user_id} 无关联员工档案")
        return employee

    async def get_employees_by_ids(
        self, session: AsyncSession, employee_ids: list[str]
    ) -> list[Employee]:
        if not employee_ids:
            return []
        result = await session.execute(
            select(Employee).where(Employee.id.in_(employee_ids))
        )
        return list(result.scalars().all())

    async def get_employee_detail(
        self,
        session: AsyncSession,
        employee_id: str,
        *,
        can_sensitive: bool = False,
    ) -> EmployeeDetailResponse:
        """员工详情（敏感字段掩码；明文查看走 sensitive 视图并写审计）。"""
        employee = await self.get_employee(session, employee_id)
        response = EmployeeDetailResponse(
            id=employee.id,
            employee_no=employee.employee_no,
            name=employee.name,
            gender=employee.gender,
            phone=employee.phone,
            work_email=employee.work_email,
            org_id=employee.org_id,
            position_id=employee.position_id,
            job_level=employee.job_level,
            status=employee.status,
            hire_date=employee.hire_date,
            regular_date=employee.regular_date,
            offboard_date=employee.offboard_date,
            user_id=employee.user_id,
            has_account=bool(employee.user_id),
            birth_date=employee.birth_date,
            id_card_masked=self._masked_or_none(employee.id_card_enc),
            bank_card_masked=self._masked_or_none(employee.bank_card_enc),
            bank_name=employee.bank_name,
        )
        if can_sensitive:
            # 有敏感权限时掩码字段置 None 由前端经 sensitive 视图接口取明文（避免详情接口写审计）
            response.id_card_masked = None
            response.bank_card_masked = None
        return response

    async def get_sensitive_view(
        self, session: AsyncSession, employee_id: str
    ) -> dict:
        """敏感字段明文视图（调用方须已校验 hr:employee:sensitive 并负责写审计）。"""
        employee = await self.get_employee(session, employee_id)
        return {
            "employee_id": employee.id,
            "employee_no": employee.employee_no,
            "name": employee.name,
            "id_card": self._decrypt_sensitive(employee.id_card_enc, "证件号"),
            "bank_card": self._decrypt_sensitive(employee.bank_card_enc, "银行卡号"),
        }

    async def update_employee(
        self, session: AsyncSession, employee_id: str, data: EmployeeUpdate
    ) -> Employee:
        """员工编辑（敏感字段提交掩码/空串表示保留原值）。

        组织/岗位/职级/状态属关键字段，须走异动流水（change_service.submit_change），
        直接编辑一律拒绝——保证「不直接改主档不留痕」。
        """
        employee = await self.get_employee(session, employee_id)
        updates = data.model_dump(exclude_unset=True, exclude_none=True)
        for field in ("org_id", "position_id", "job_level", "status"):
            if field in updates and updates[field] != getattr(employee, field):
                raise BadRequestError(f"{field} 变更须通过异动办理")

        for field in ("id_card", "bank_card"):
            if field in updates:
                raw = updates.pop(field)
                if raw and raw != "******":
                    column = "id_card_enc" if field == "id_card" else "bank_card_enc"
                    setattr(
                        employee,
                        column,
                        self._encrypt_sensitive(
                            raw, "证件号" if field == "id_card" else "银行卡号"
                        ),
                    )

        for field, value in updates.items():
            setattr(employee, field, value)
        await session.flush()
        return employee

    async def delete_employee(self, session: AsyncSession, employee_id: str) -> None:
        """删除员工（仅离职员可删，二次确认由前端承担）。"""
        employee = await self.get_employee(session, employee_id)
        if employee.status != "offboarded":
            raise ConflictError("仅已离职员工可删除")
        await session.delete(employee)
        await session.flush()

    # ── 开通系统账号 ──

    async def open_account(
        self, session: AsyncSession, employee_id: str
    ) -> AccountOpenResponse:
        """开通系统账号：inner 调 iam 建号回填 user_id，初始密码一次性回显。"""
        employee = await self.get_employee(session, employee_id)
        if employee.user_id:
            raise ConflictError("该员工已开通系统账号")
        if employee.status == "offboarded":
            raise ConflictError("已离职员工不可开通账号")

        tenant_id = get_tenant_id_safe()
        initial_password = generate_initial_password()
        try:
            result = await get_iam_client().create_user(
                session,
                tenant_id=tenant_id,
                username=employee.employee_no,
                password=initial_password,
                email=employee.work_email,
                phone=employee.phone,
                nickname=employee.name,
            )
        except ValueError as error:
            raise ConflictError(f"开通系统账号失败: {error}") from error

        employee.user_id = result["user_id"]
        await session.flush()
        _logger.info(f"员工开通系统账号: {employee.employee_no} -> user_id={employee.user_id}")
        return AccountOpenResponse(
            employee_id=employee.id,
            user_id=employee.user_id,
            username=employee.employee_no,
            initial_password=initial_password,
        )

    # ── 批量导入 ──

    async def import_employees(
        self, session: AsyncSession, *, dry_run: bool, rows: list[dict]
    ) -> EmployeeImportResponse:
        """员工批量导入：dryRun 逐行预检不落库；正式导入逐员工写 hire 流水。"""
        results: list[EmployeeImportRowResult] = []
        success_count = 0

        for index, row in enumerate(rows):
            try:
                if dry_run:
                    await self._validate_import_row(session, row)
                    results.append(EmployeeImportRowResult(row_index=index, success=True))
                else:
                    data = EmployeeCreate(**row)
                    employee = await self.create_employee(session, data)
                    success_count += 1
                    results.append(
                        EmployeeImportRowResult(
                            row_index=index, success=True, employee_no=employee.employee_no
                        )
                    )
            except Exception as error:  # noqa: BLE001 逐行容错收集
                results.append(
                    EmployeeImportRowResult(row_index=index, success=False, error=str(error))
                )

        failure_count = sum(1 for r in results if not r.success)
        return EmployeeImportResponse(
            dry_run=dry_run,
            total=len(rows),
            success_count=success_count if not dry_run else len(results) - failure_count,
            failure_count=failure_count,
            rows=results,
        )

    async def _validate_import_row(self, session: AsyncSession, row: dict) -> None:
        """预检：必填/岗位可选性/证件号可解析（不落库）。"""
        for required in ("name", "hire_date"):
            if not row.get(required):
                raise BadRequestError(f"必填字段缺失: {required}")
        if row.get("position_id"):
            await self._ensure_position_selectable(session, row["position_id"])
        EmployeeCreate(**row)

    # ── 内部工具 ──

    async def _generate_employee_no(self, session: AsyncSession) -> str:
        """工号经 iam 编码规则取号（employee_no：EMP+6 位流水）。"""
        tenant_id = get_tenant_id_safe()
        try:
            return await get_iam_client().generate_code(session, tenant_id, "employee_no")
        except ValueError as error:
            raise BadRequestError(f"工号生成失败: {error}") from error

    @staticmethod
    def _encrypt_sensitive(plain: str | None, label: str) -> str | None:
        if not plain:
            return None
        try:
            return encrypt(plain)
        except CryptoError as error:
            raise BadRequestError(f"{label}加密失败") from error

    @staticmethod
    def _decrypt_sensitive(cipher: str | None, label: str) -> str | None:
        if not cipher:
            return None
        try:
            return decrypt(cipher)
        except CryptoError as error:
            raise BadRequestError(f"{label}解密失败") from error

    @staticmethod
    def _masked_or_none(cipher: str | None) -> str | None:
        if not cipher:
            return None
        try:
            return mask_sensitive_number(decrypt(cipher))
        except CryptoError:
            return "******"

    async def _ensure_position_selectable(
        self, session: AsyncSession, position_id: str
    ) -> None:
        result = await session.execute(
            select(Position).where(Position.id == position_id)
        )
        position = result.scalar_one_or_none()
        if not position:
            raise NotFoundError(f"岗位 {position_id} 不存在")
        if position.status != "active":
            raise BadRequestError("停用岗位不可被员工建档选中")

    @staticmethod
    def _snapshot(employee: Employee) -> dict:
        return {
            "name": employee.name,
            "gender": employee.gender,
            "org_id": employee.org_id,
            "position_id": employee.position_id,
            "job_level": employee.job_level,
            "status": employee.status,
            "hire_date": str(employee.hire_date) if employee.hire_date else None,
            "regular_date": str(employee.regular_date) if employee.regular_date else None,
            "offboard_date": str(employee.offboard_date) if employee.offboard_date else None,
            "phone": employee.phone,
            "work_email": employee.work_email,
        }


def get_tenant_id_safe() -> str:
    from framework.common.ctx import get_tenant_id

    tenant_id = get_tenant_id()
    if not tenant_id:
        raise BadRequestError("缺少租户上下文")
    return tenant_id


employee_service = EmployeeService()
