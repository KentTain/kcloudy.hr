"""hr 领域事件定义"""

from dataclasses import dataclass

from framework.events.base import DomainEvent


@dataclass
class EmployeeOffboarded(DomainEvent):
    """员工离职生效事件（消费方 hr listeners：iam 停用账号 + 移出组织 + 站内信回告）"""

    tenant_id: str = ""
    employee_id: str = ""
    employee_no: str = ""
    employee_name: str = ""
    user_id: str | None = None
    org_id: str | None = None
    offboard_date: str | None = None
    operator_id: str | None = None
