"""hr 模块数据库模型"""

from framework.database import create_base_model, create_module_base

Base = create_module_base(schema="hr")
BaseModel = create_base_model(Base)

from hr.models.approval import ApprovalAction, ApprovalRequest  # noqa: E402
from hr.models.attendance import (  # noqa: E402
    AttendanceImportBatch,
    AttendanceRecord,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
)
from hr.models.employee import (  # noqa: E402
    Employee,
    EmployeeAttachment,
    EmployeeAttributeValue,
    EmployeeChange,
    EmployeeContract,
    EmployeeFieldDefinition,
    EmployeeFieldGroup,
    Position,
)
from hr.models.perf import PerfCycle, PerfGoal, PerfReview  # noqa: E402
from hr.models.recruiting import (  # noqa: E402
    Candidate,
    CandidateApplication,
    Interview,
    JobPosting,
    JobRequisition,
    Offer,
)
from hr.models.salary import (  # noqa: E402
    EmployeeSalaryPackage,
    PayrollEntry,
    PayrollRun,
    SalaryBand,
    SalaryItem,
)

__all__ = [
    "Base",
    "BaseModel",
    "ApprovalAction",
    "ApprovalRequest",
    "AttendanceImportBatch",
    "AttendanceRecord",
    "Candidate",
    "CandidateApplication",
    "Employee",
    "EmployeeAttachment",
    "EmployeeAttributeValue",
    "EmployeeChange",
    "EmployeeContract",
    "EmployeeFieldDefinition",
    "EmployeeFieldGroup",
    "Interview",
    "JobPosting",
    "JobRequisition",
    "LeaveBalance",
    "LeaveRequest",
    "LeaveType",
    "Offer",
    "PayrollEntry",
    "PayrollRun",
    "PerfCycle",
    "PerfGoal",
    "PerfReview",
    "Position",
    "SalaryBand",
    "SalaryItem",
]
