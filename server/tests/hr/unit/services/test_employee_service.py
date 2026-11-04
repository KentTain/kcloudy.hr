"""员工服务单元测试

覆盖：敏感字段掩码/初始密码强度、编辑关键字段拒绝（须走异动）、
删除保护（仅离职员可删）、岗位可选性校验、导入行预检。
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError, ConflictError, NotFoundError

from hr.models import Employee, Position
from hr.schemas.employee import EmployeeUpdate
from hr.services.employee_service import (
    EmployeeService,
    generate_initial_password,
    mask_sensitive_number,
)


class _FakeResult:
    def __init__(self, entity=None):
        self._entity = entity

    def scalar_one_or_none(self):
        return self._entity

    def scalars(self):
        entity = self._entity
        holder = self

        class _All:
            def all(self):
                return [entity] if entity is not None else []

        return _All()


def _mock_session(get_result=None, execute_result=None) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=get_result)
    session.execute = AsyncMock(return_value=execute_result or _FakeResult())
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


def _employee(**overrides) -> Employee:
    defaults = dict(
        id="e-1",
        tenant_id="t-1",
        employee_no="EMP000001",
        name="张三",
        status="regular",
        hire_date=date(2025, 1, 1),
    )
    defaults.update(overrides)
    return Employee(**defaults)


class TestMaskAndPassword:
    """掩码与初始密码"""

    def test_mask_keeps_head_tail(self):
        assert mask_sensitive_number("110101199001011234") == "110***********1234"
        assert mask_sensitive_number("6222021234567890") == "622*********7890"

    def test_mask_short_all_stars(self):
        assert mask_sensitive_number("1234567") == "*******"

    def test_mask_none(self):
        assert mask_sensitive_number(None) is None

    def test_initial_password_meets_complexity(self):
        for _ in range(20):
            password = generate_initial_password()
            assert len(password) == 12
            assert any(c.islower() for c in password)
            assert any(c.isupper() for c in password)
            assert any(c.isdigit() for c in password)
            assert any(c in "!@#$%^&*" for c in password)


class TestUpdateGuards:
    """编辑守卫"""

    @pytest.mark.asyncio
    async def test_key_field_change_rejected(self):
        service = EmployeeService()
        session = _mock_session(get_result=_employee())
        data = EmployeeUpdate(phone="13800000000", org_id="org-new")
        with pytest.raises(BadRequestError, match="异动"):
            await service.update_employee(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_status_change_rejected(self):
        service = EmployeeService()
        session = _mock_session(get_result=_employee())
        data = EmployeeUpdate(status="offboarded")
        with pytest.raises(BadRequestError):
            await service.update_employee(session, "e-1", data)

    @pytest.mark.asyncio
    async def test_plain_field_update_ok(self):
        service = EmployeeService()
        employee = _employee()
        session = _mock_session(get_result=employee)
        data = EmployeeUpdate(phone="13800000000")
        updated = await service.update_employee(session, "e-1", data)
        assert updated.phone == "13800000000"

    @pytest.mark.asyncio
    async def test_mask_submission_keeps_original(self):
        service = EmployeeService()
        employee = _employee(id_card_enc="cipher-old")
        session = _mock_session(get_result=employee)
        data = EmployeeUpdate(id_card="******")
        await service.update_employee(session, "e-1", data)
        assert employee.id_card_enc == "cipher-old"


class TestDeleteGuard:
    """删除保护"""

    @pytest.mark.asyncio
    async def test_active_employee_delete_rejected(self):
        service = EmployeeService()
        session = _mock_session(get_result=_employee(status="regular"))
        with pytest.raises(ConflictError):
            await service.delete_employee(session, "e-1")

    @pytest.mark.asyncio
    async def test_offboarded_employee_delete_ok(self):
        service = EmployeeService()
        session = _mock_session(get_result=_employee(status="offboarded"))
        await service.delete_employee(session, "e-1")
        session.delete.assert_awaited_once()


class TestPositionSelectable:
    """岗位可选性"""

    @pytest.mark.asyncio
    async def test_disabled_position_rejected(self):
        service = EmployeeService()
        session = _mock_session(
            execute_result=_FakeResult(entity=Position(id="p-1", code="DEV", name="研发", status="disabled"))
        )
        with pytest.raises(BadRequestError, match="停用"):
            await service._ensure_position_selectable(session, "p-1")

    @pytest.mark.asyncio
    async def test_missing_position_not_found(self):
        service = EmployeeService()
        session = _mock_session(execute_result=_FakeResult(entity=None))
        with pytest.raises(NotFoundError):
            await service._ensure_position_selectable(session, "p-x")


class TestImportRowValidation:
    """导入行预检"""

    @pytest.mark.asyncio
    async def test_missing_required_field(self):
        service = EmployeeService()
        session = _mock_session()
        with pytest.raises(BadRequestError, match="必填"):
            await service._validate_import_row(session, {"name": "张三"})
        with pytest.raises(BadRequestError, match="必填"):
            await service._validate_import_row(session, {"hire_date": "2026-01-01"})

    @pytest.mark.asyncio
    async def test_valid_row_passes(self):
        service = EmployeeService()
        session = _mock_session(execute_result=_FakeResult(entity=None))
        await service._validate_import_row(
            session, {"name": "张三", "hire_date": "2026-01-01"}
        )


class TestBankNameDetail:
    """开户行（代发导出用明文字段）详情回显"""

    @pytest.mark.asyncio
    async def test_detail_carries_bank_name(self):
        service = EmployeeService()
        employee = _employee(bank_name="工商银行北京分行", id_card_enc="enc", bank_card_enc="enc")
        session = _mock_session(get_result=employee)
        detail = await service.get_employee_detail(session, "e-1")
        assert detail.bank_name == "工商银行北京分行"
