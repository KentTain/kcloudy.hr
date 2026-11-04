"""hr 模块声明"""

from collections.abc import Callable

from framework.module.definition import MenuDef, ModuleDefinition, PermissionDef, RoleDef

from hr.models import Base

# 权限资源清单（对齐 docs/features/hr/README admin controllers 列表）
_RESOURCE_LABELS: list[tuple[str, str]] = [
    ("employee", "员工"),
    ("position", "岗位"),
    ("employee_change", "异动"),
    ("contract", "合同"),
    ("attachment", "材料附件"),
    ("field_definition", "属性定义"),
    ("requisition", "招聘需求"),
    ("candidate", "候选人"),
    ("interview", "面试"),
    ("offer", "Offer"),
    ("salary_item", "薪酬项"),
    ("salary_band", "职级薪带"),
    ("salary_package", "定薪"),
    ("payroll", "发薪"),
    ("channel", "招聘渠道"),
    ("attendance", "考勤"),
    ("leave", "假勤"),
    ("report", "报表"),
    ("perf_cycle", "考核周期"),
    ("perf_goal", "绩效目标"),
    ("perf_review", "绩效评估"),
]

_ACTION_LABELS = {"read": "查看", "write": "编辑", "delete": "删除"}

# 一期专属动作点（00.通用设计 RBAC 权限编码规范）
_SPECIAL_PERMISSIONS = [
    PermissionDef(code="hr:employee:sensitive", name="查看员工敏感字段", resource="employee", action="sensitive"),
    PermissionDef(code="hr:employee:import", name="员工批量导入", resource="employee", action="import"),
    PermissionDef(code="hr:candidate:merge", name="候选人合并", resource="candidate", action="merge"),
    PermissionDef(code="hr:payroll:confirm", name="发薪批次确认", resource="payroll", action="confirm"),
    PermissionDef(code="hr:payroll:export", name="标准代发文件导出", resource="payroll", action="export"),
    PermissionDef(code="hr:channel:sync", name="渠道归集同步", resource="channel", action="sync"),
    PermissionDef(code="hr:attendance:import", name="考勤导入", resource="attendance", action="import"),
    PermissionDef(code="hr:leave:approve", name="请假审批", resource="leave", action="approve"),
    PermissionDef(code="hr:approval:read", name="查看审批请求", resource="approval", action="read"),
    PermissionDef(code="hr:approval:approve", name="审批请求处理", resource="approval", action="approve"),
    PermissionDef(code="hr:perf:calibrate", name="绩效评级校准", resource="perf", action="calibrate"),
    PermissionDef(code="hr:report:export", name="报表导出", resource="report", action="export"),
    PermissionDef(code="hr:leave:transfer", name="移交请假单", resource="leave", action="transfer"),
    PermissionDef(code="hr:employee_change:transfer", name="移交异动记录", resource="employee_change", action="transfer"),
    PermissionDef(code="hr:approval:transfer", name="移交审批请求", resource="approval", action="transfer"),
]


class HrModule:
    """hr 模块描述符"""

    @property
    def name(self) -> str:
        return "hr"

    @property
    def schema(self) -> str:
        return "hr"

    @property
    def dependencies(self) -> list[str]:
        # 依赖 tenant/iam：菜单与权限码经 iam 体系下发，租户上下文来自 tenant 体系
        return ["tenant", "iam"]

    def get_base(self) -> type:
        return Base

    def get_routers(self) -> list[tuple]:
        """
        返回路由注册列表

        格式: [(router, prefix, tags), ...]
        """
        from hr.controllers.admin.approval_request_controller import (
            router as admin_approval_router,
        )
        from hr.controllers.admin.attachment_controller import (
            router as admin_attachment_router,
        )
        from hr.controllers.admin.candidate_controller import (
            router as admin_candidate_router,
        )
        from hr.controllers.admin.channel_controller import (
            router as admin_channel_router,
        )
        from hr.controllers.admin.change_controller import (
            router as admin_change_router,
        )
        from hr.controllers.admin.contract_controller import (
            router as admin_contract_router,
        )
        from hr.controllers.admin.employee_controller import (
            router as admin_employee_router,
        )
        from hr.controllers.admin.field_controller import (
            router as admin_field_router,
        )
        from hr.controllers.admin.interview_controller import (
            router as admin_interview_router,
        )
        from hr.controllers.admin.leave_controller import (
            router as admin_leave_router,
        )
        from hr.controllers.admin.offer_controller import (
            router as admin_offer_router,
        )
        from hr.controllers.admin.position_controller import (
            router as admin_position_router,
        )
        from hr.controllers.admin.report_controller import (
            router as admin_report_router,
        )
        from hr.controllers.admin.attendance_controller import (
            router as admin_attendance_router,
        )
        from hr.controllers.admin.payroll_controller import (
            router as admin_payroll_router,
        )
        from hr.controllers.admin.perf_cycle_controller import (
            router as admin_perf_cycle_router,
        )
        from hr.controllers.admin.perf_review_controller import (
            router as admin_perf_review_router,
        )
        from hr.controllers.admin.requisition_controller import (
            router as admin_requisition_router,
        )
        from hr.controllers.admin.salary_band_controller import (
            router as admin_salary_band_router,
        )
        from hr.controllers.admin.salary_item_controller import (
            router as admin_salary_item_router,
        )
        from hr.controllers.console.my_leave_controller import (
            router as console_my_leave_router,
        )
        from hr.controllers.console.self_service_controller import (
            router as console_self_service_router,
        )
        from hr.controllers.console.team_controller import (
            router as console_team_router,
        )
        from hr.controllers.admin.salary_package_controller import (
            router as admin_salary_package_router,
        )
        from hr.controllers.inner.agent_tools_controller import (
            router as inner_agent_tools_router,
        )
        from hr.controllers.inner.employee_controller import (
            router as inner_employee_router,
        )
        from hr.controllers.inner.webhook_controller import (
            router as inner_webhook_router,
        )

        return [
            # Admin 层路由
            (admin_employee_router, "/hr/admin/v1", ["Admin - Employee"]),
            (admin_position_router, "/hr/admin/v1", ["Admin - Position"]),
            (admin_change_router, "/hr/admin/v1", ["Admin - EmployeeChange"]),
            (admin_field_router, "/hr/admin/v1", ["Admin - FieldDefinition"]),
            (admin_contract_router, "/hr/admin/v1", ["Admin - Contract"]),
            (admin_attachment_router, "/hr/admin/v1", ["Admin - Attachment"]),
            (admin_candidate_router, "/hr/admin/v1", ["Admin - Candidate"]),
            (admin_channel_router, "/hr/admin/v1", ["Admin - Channel"]),
            (admin_interview_router, "/hr/admin/v1", ["Admin - Interview"]),
            (admin_offer_router, "/hr/admin/v1", ["Admin - Offer"]),
            (admin_requisition_router, "/hr/admin/v1", ["Admin - Requisition"]),
            (admin_salary_item_router, "/hr/admin/v1", ["Admin - SalaryItem"]),
            (admin_salary_band_router, "/hr/admin/v1", ["Admin - SalaryBand"]),
            (admin_salary_package_router, "/hr/admin/v1", ["Admin - SalaryPackage"]),
            (admin_payroll_router, "/hr/admin/v1", ["Admin - Payroll"]),
            (admin_attendance_router, "/hr/admin/v1", ["Admin - Attendance"]),
            (admin_leave_router, "/hr/admin/v1", ["Admin - Leave"]),
            (admin_approval_router, "/hr/admin/v1", ["Admin - ApprovalRequest"]),
            (admin_perf_cycle_router, "/hr/admin/v1", ["Admin - PerfCycle"]),
            (admin_perf_review_router, "/hr/admin/v1", ["Admin - PerfReview"]),
            (admin_report_router, "/hr/admin/v1", ["Admin - Report"]),
            # Console 层路由
            (console_self_service_router, "/hr/console/v1", ["Console - SelfService"]),
            (console_team_router, "/hr/console/v1", ["Console - Team"]),
            (console_my_leave_router, "/hr/console/v1", ["Console - MyLeave"]),
            # Inner 层路由
            (inner_employee_router, "/hr", ["Inner - Employee"]),
            (inner_agent_tools_router, "/hr", ["Inner - AgentTools"]),
            (inner_webhook_router, "/hr", ["Inner - ChannelWebhook"]),
        ]

    def get_middlewares(self) -> list[type]:
        return []

    def get_lifespan_hooks(self) -> list[Callable]:
        return []

    def get_seeds(self) -> dict[str, Callable]:
        from hr.migrations.seeds.hr_seed import run as hr_seed_run

        return {"hr": hr_seed_run}

    def get_task_setup(self) -> tuple | None:
        """合同到期扫描任务（到期自动置 expired + 30 天窗口站内信提醒）"""
        from hr.tasks.setup import cleanup_tasks, setup_tasks

        return (setup_tasks, cleanup_tasks)

    def get_listener_setup(self) -> tuple | None:
        """离职生效事件监听（iam 停用账号/移出组织/站内信回告）"""
        from hr.listeners.setup import cleanup_listeners, setup_listeners

        return (setup_listeners, cleanup_listeners)

    def get_module_definition(self) -> ModuleDefinition:
        # 菜单树对齐 docs/features/hr/README：6 组 + 20 叶（二期批 B 增绩效组·考核周期/批 C 增评估管理）；
        # 员工自助/我的假期为 console 层，登录即可见（无权限码）。
        permissions = [
            PermissionDef(
                code=f"hr:{resource}:{action}",
                name=f"{label}·{_ACTION_LABELS[action]}",
                resource=resource,
                action=action,
            )
            for resource, label in _RESOURCE_LABELS
            for action in ("read", "write", "delete")
        ] + _SPECIAL_PERMISSIONS

        return ModuleDefinition(
            code="hr",
            name="人力资源",
            description="员工主档与异动、招聘漏斗、薪酬定薪发薪、考勤假期与报表自助",
            icon="Users",
            version="0.1.0",
            menus=[
                # ── 员工中心 ──
                MenuDef(
                    clients="vue",
                    code="hr.employee-center",
                    name="员工中心",
                    path="",
                    icon="Building2",
                    sort_order=1,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.employees",
                    name="员工管理",
                    path="/hr/employees",
                    icon="Contact",
                    parent_code="hr.employee-center",
                    sort_order=1,
                    permission_codes=["hr:employee:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.positions",
                    name="岗位管理",
                    path="/hr/positions",
                    icon="Briefcase",
                    parent_code="hr.employee-center",
                    sort_order=2,
                    permission_codes=["hr:position:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.employee-changes",
                    name="异动管理",
                    path="/hr/employee-changes",
                    icon="ArrowLeftRight",
                    parent_code="hr.employee-center",
                    sort_order=3,
                    permission_codes=["hr:employee_change:read"],
                ),
                # ── 考勤假期 ──
                MenuDef(
                    clients="vue",
                    code="hr.attendance-leave",
                    name="考勤假期",
                    path="",
                    icon="CalendarCheck",
                    sort_order=2,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.attendance",
                    name="考勤管理",
                    path="/hr/attendance",
                    icon="Clock",
                    parent_code="hr.attendance-leave",
                    sort_order=1,
                    permission_codes=["hr:attendance:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.leave",
                    name="假勤管理",
                    path="/hr/leave",
                    icon="Palmtree",
                    parent_code="hr.attendance-leave",
                    sort_order=2,
                    permission_codes=["hr:leave:read"],
                ),
                # ── 招聘管理 ──
                MenuDef(
                    clients="vue",
                    code="hr.recruiting",
                    name="招聘管理",
                    path="",
                    icon="UserPlus",
                    sort_order=3,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.requisitions",
                    name="招聘需求",
                    path="/hr/requisitions",
                    icon="FileText",
                    parent_code="hr.recruiting",
                    sort_order=1,
                    permission_codes=["hr:requisition:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.candidates",
                    name="候选人",
                    path="/hr/candidates",
                    icon="UserSearch",
                    parent_code="hr.recruiting",
                    sort_order=2,
                    permission_codes=["hr:candidate:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.interviews",
                    name="面试日程",
                    path="/hr/interviews",
                    icon="CalendarClock",
                    parent_code="hr.recruiting",
                    sort_order=3,
                    permission_codes=["hr:interview:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.channels",
                    name="渠道管理",
                    path="/hr/channels",
                    icon="Radio",
                    parent_code="hr.recruiting",
                    sort_order=4,
                    permission_codes=["hr:channel:read"],
                ),
                # ── 薪酬管理 ──
                MenuDef(
                    clients="vue",
                    code="hr.salary",
                    name="薪酬管理",
                    path="",
                    icon="Wallet",
                    sort_order=4,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.salary-items",
                    name="薪酬项",
                    path="/hr/salary-items",
                    icon="ListOrdered",
                    parent_code="hr.salary",
                    sort_order=1,
                    permission_codes=["hr:salary_item:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.salary-bands",
                    name="职级薪带",
                    path="/hr/salary-bands",
                    icon="TrendingUp",
                    parent_code="hr.salary",
                    sort_order=2,
                    permission_codes=["hr:salary_band:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.salary-packages",
                    name="定薪调薪",
                    path="/hr/salary-packages",
                    icon="BadgeDollarSign",
                    parent_code="hr.salary",
                    sort_order=3,
                    permission_codes=["hr:salary_package:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.payroll-runs",
                    name="发薪批次",
                    path="/hr/payroll-runs",
                    icon="Banknote",
                    parent_code="hr.salary",
                    sort_order=4,
                    permission_codes=["hr:payroll:read"],
                ),
                # ── 绩效管理（二期批 B）──
                MenuDef(
                    clients="vue",
                    code="hr.perf",
                    name="绩效管理",
                    path="",
                    icon="Target",
                    sort_order=5,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.perf-cycles",
                    name="考核周期",
                    path="/hr/perf-cycles",
                    icon="CalendarRange",
                    parent_code="hr.perf",
                    sort_order=1,
                    permission_codes=["hr:perf_cycle:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.perf-reviews",
                    name="评估管理",
                    path="/hr/perf-reviews",
                    icon="ClipboardCheck",
                    parent_code="hr.perf",
                    sort_order=2,
                    permission_codes=["hr:perf_review:read"],
                ),
                # ── 审批中心 ──
                MenuDef(
                    clients="vue",
                    code="hr.approval-center",
                    name="审批中心",
                    path="",
                    icon="ClipboardCheck",
                    sort_order=6,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.approvals",
                    name="审批管理",
                    path="/hr/approvals",
                    icon="Stamp",
                    parent_code="hr.approval-center",
                    sort_order=1,
                    permission_codes=["hr:approval:read"],
                ),
                # ── 报表与自助 ──
                MenuDef(
                    clients="vue",
                    code="hr.reports",
                    name="报表分析",
                    path="/hr/reports",
                    icon="BarChart3",
                    sort_order=7,
                    permission_codes=["hr:report:read"],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.self-service",
                    name="员工自助",
                    path="/hr/self-service",
                    icon="UserRound",
                    sort_order=8,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.my-leave",
                    name="我的假期",
                    path="/hr/my-leave",
                    icon="Palmtree",
                    sort_order=9,
                    permission_codes=[],
                ),
                MenuDef(
                    clients="vue",
                    code="hr.team",
                    name="团队工作台",
                    path="/hr/team",
                    icon="Users",
                    sort_order=10,
                    permission_codes=[],
                ),
            ],
            permissions=permissions,
            default_roles=[
                RoleDef(
                    code="hrAdmin",
                    name="人力资源管理员",
                    description="HR 模块全部权限（含薪酬项定义、批次确认、渠道凭证配置）",
                    permission_codes=["hr:*:*"],
                    is_system=True,
                ),
                RoleDef(
                    code="hrSpecialist",
                    name="人资专员",
                    description=(
                        "员工/岗位/异动/合同/附件/属性全操作，招聘漏斗全操作，考勤假期全操作，"
                        "请假审批兜底，审批中心处理，绩效全流程操作（评级校准除外）；"
                        "薪酬只读+定薪执行+发薪试算与明细修正；"
                        "含报表导出与标准代发文件导出；"
                        "不含批次确认（hr:payroll:confirm）与渠道凭证同步（hr:channel:sync）"
                    ),
                    permission_codes=[
                        "hr:*:read",
                        "hr:employee:*",
                        "hr:employee:import",
                        "hr:position:*",
                        "hr:employee_change:*",
                        "hr:contract:*",
                        "hr:attachment:*",
                        "hr:field_definition:*",
                        "hr:requisition:*",
                        "hr:candidate:*",
                        "hr:candidate:merge",
                        "hr:interview:*",
                        "hr:offer:*",
                        "hr:salary_package:*",
                        "hr:payroll:write",
                        "hr:payroll:export",
                        "hr:report:export",
                        "hr:attendance:*",
                        "hr:attendance:import",
                        "hr:leave:*",
                        "hr:leave:approve",
                        "hr:approval:approve",
                        "hr:perf_cycle:write",
                        "hr:perf_goal:write",
                        "hr:perf_review:write",
                    ],
                    is_system=True,
                ),
                RoleDef(
                    code="hrViewer",
                    name="查阅者",
                    description=(
                        "HR 模块只读：员工/岗位/异动/合同/招聘/考勤/假勤/审批/绩效/报表可查；"
                        "不含敏感字段明文、薪酬明细（定薪与发薪）——薪酬仅见聚合统计"
                    ),
                    permission_codes=[
                        "hr:employee:read",
                        "hr:position:read",
                        "hr:employee_change:read",
                        "hr:contract:read",
                        "hr:field_definition:read",
                        "hr:requisition:read",
                        "hr:candidate:read",
                        "hr:interview:read",
                        "hr:offer:read",
                        "hr:channel:read",
                        "hr:salary_item:read",
                        "hr:salary_band:read",
                        "hr:attendance:read",
                        "hr:leave:read",
                        "hr:approval:read",
                        "hr:perf_cycle:read",
                        "hr:perf_goal:read",
                        "hr:perf_review:read",
                        "hr:report:read",
                    ],
                    is_system=True,
                ),
                RoleDef(
                    code="lineManager",
                    name="用人经理",
                    description="本部门员工只读、招聘需求与面试日程读写、候选人只读、所辖组织请假审批、团队绩效只读（评分经 console 团队工作台）",
                    permission_codes=[
                        "hr:employee:read",
                        "hr:requisition:read",
                        "hr:requisition:write",
                        "hr:candidate:read",
                        "hr:interview:read",
                        "hr:interview:write",
                        "hr:leave:approve",
                        "hr:perf_cycle:read",
                        "hr:perf_goal:read",
                        "hr:perf_review:read",
                    ],
                    is_system=True,
                ),
            ],
        )
