"""HR 租户初始化模板（单一真相源）

默认租户 seed 与新租户初始化同走 provision_* 幂等实例化（先例
iam dict_template/code_rule_template 双通道同源）。渠道凭证与薪酬设置
配置类型随 iam provision_structure（hr 配置类型注册于 iam
system_setting_template.DEFAULT_SETTINGS），不在本模板重复。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from framework.utils.log_util import write_success
from hr.models import EmployeeFieldGroup, SalaryItem

# 预置员工属性组（basic/education/contacts/work 四域 + custom 自定义）
DEFAULT_FIELD_GROUPS: list[dict] = [
    {"code": "basic", "name": "基础信息", "sort": 10},
    {"code": "education", "name": "教育信息", "sort": 20},
    {"code": "contacts", "name": "联系方式", "sort": 30},
    {"code": "work", "name": "工作信息", "sort": 40},
    {"code": "custom", "name": "自定义", "sort": 50},
]

# 预置薪酬项 9 项（code 创建后不可修改，历史数据按 code 关联）
DEFAULT_SALARY_ITEMS: list[dict] = [
    {"code": "base_monthly", "name": "月基本工资", "category": "base", "sort": 10,
     "ext_data": {"taxable": True, "social_security_base": True, "monthly_fixed": True}},
    {"code": "performance_monthly", "name": "月绩效工资", "category": "performance", "sort": 20,
     "ext_data": {"taxable": True, "monthly_fixed": False}},
    {"code": "bonus_annual", "name": "年终奖", "category": "bonus", "sort": 30,
     "ext_data": {"taxable": True, "monthly_fixed": False, "unit": "元/年"}},
    {"code": "bonus_project", "name": "项目奖金", "category": "bonus", "sort": 40,
     "ext_data": {"taxable": True, "monthly_fixed": False}},
    {"code": "subsidy_meal", "name": "餐补", "category": "subsidy", "sort": 50,
     "ext_data": {"taxable": False, "monthly_fixed": True}},
    {"code": "subsidy_transport", "name": "交通补贴", "category": "subsidy", "sort": 60,
     "ext_data": {"taxable": False, "monthly_fixed": True}},
    {"code": "subsidy_housing", "name": "住房补贴", "category": "subsidy", "sort": 70,
     "ext_data": {"taxable": False, "monthly_fixed": True}},
    {"code": "deduction_social", "name": "社保个人部分", "category": "deduction", "sort": 80,
     "ext_data": {"taxable": False, "social_security_base": True, "monthly_fixed": False}},
    {"code": "deduction_house_fund", "name": "公积金个人部分", "category": "deduction", "sort": 90,
     "ext_data": {"taxable": False, "social_security_base": True, "monthly_fixed": False}},
]


async def provision_field_groups(session: AsyncSession, tenant_id: str) -> int:
    """按模板幂等预置员工属性组；已存在保留，缺失补建。"""
    existing = {
        code
        for code, in (
            await session.execute(
                select(EmployeeFieldGroup.code).where(EmployeeFieldGroup.tenant_id == tenant_id)
            )
        ).all()
    }
    created = 0
    for group in DEFAULT_FIELD_GROUPS:
        if group["code"] in existing:
            continue
        session.add(EmployeeFieldGroup(tenant_id=tenant_id, **group))
        created += 1
    if created:
        await session.flush()
        write_success(f"[hr] 预置员工属性组 {created} 组: tenant={tenant_id}")
    return created


async def provision_salary_items(session: AsyncSession, tenant_id: str) -> int:
    """按模板幂等预置薪酬项 9 项；已存在保留，缺失补建。"""
    existing = {
        code
        for code, in (
            await session.execute(
                select(SalaryItem.code).where(SalaryItem.tenant_id == tenant_id)
            )
        ).all()
    }
    created = 0
    for item in DEFAULT_SALARY_ITEMS:
        if item["code"] in existing:
            continue
        session.add(SalaryItem(tenant_id=tenant_id, **item))
        created += 1
    if created:
        await session.flush()
        write_success(f"[hr] 预置薪酬项 {created} 项: tenant={tenant_id}")
    return created
