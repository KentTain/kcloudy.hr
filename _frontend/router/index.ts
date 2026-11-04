/**
 * hr 模块路由配置
 *
 * 叶子 path 与后端 `server/python/src/hr/module.py` 菜单树对齐（6 组 20 叶，
 * 契约测试 tests/hr/unit/module.test.ts 校验双向一致）；报表分析/员工自助/我的假期
 * 为顶级菜单（无组父级）。员工自助/我的假期/团队工作台为 console 层页面，登录即可见（无权限码），
 * 其余叶子由 meta.permissions 交全局守卫拦截（菜单可见性由后端按权限过滤下发）。
 * 页面随阶段 7 与二期分批落地。
 */

import type { RouteRecordRaw } from "vue-router";

export const hrRoutes: RouteRecordRaw[] = [
  {
    path: "hr",
    name: "HrRoot",
    component: () => import("@/hr/pages/HrModuleLayout.vue"),
    meta: { requiresAuth: true },
    children: [
      // ── 员工中心 ──
      {
        path: "employees",
        name: "HrEmployees",
        component: () => import("@/hr/pages/employees/EmployeesPage.vue"),
        meta: {
          title: "员工管理",
          icon: "contact",
          requiresAuth: true,
          permissions: ["hr:employee:read"],
        },
      },
      {
        path: "positions",
        name: "HrPositions",
        component: () => import("@/hr/pages/positions/PositionsPage.vue"),
        meta: {
          title: "岗位管理",
          icon: "briefcase",
          requiresAuth: true,
          permissions: ["hr:position:read"],
        },
      },
      {
        path: "employee-changes",
        name: "HrEmployeeChanges",
        component: () => import("@/hr/pages/employee-changes/EmployeeChangesPage.vue"),
        meta: {
          title: "异动管理",
          icon: "arrow-left-right",
          requiresAuth: true,
          permissions: ["hr:employee_change:read"],
        },
      },
      // ── 考勤假期 ──
      {
        path: "attendance",
        name: "HrAttendance",
        component: () => import("@/hr/pages/attendance/AttendancePage.vue"),
        meta: {
          title: "考勤管理",
          icon: "clock",
          requiresAuth: true,
          permissions: ["hr:attendance:read"],
        },
      },
      {
        path: "leave",
        name: "HrLeave",
        component: () => import("@/hr/pages/leave/LeavePage.vue"),
        meta: {
          title: "假勤管理",
          icon: "palmtree",
          requiresAuth: true,
          permissions: ["hr:leave:read"],
        },
      },
      // ── 招聘管理 ──
      {
        path: "requisitions",
        name: "HrRequisitions",
        component: () => import("@/hr/pages/requisitions/RequisitionsPage.vue"),
        meta: {
          title: "招聘需求",
          icon: "file-text",
          requiresAuth: true,
          permissions: ["hr:requisition:read"],
        },
      },
      {
        path: "candidates",
        name: "HrCandidates",
        component: () => import("@/hr/pages/candidates/CandidatesPage.vue"),
        meta: {
          title: "候选人",
          icon: "user-search",
          requiresAuth: true,
          permissions: ["hr:candidate:read"],
        },
      },
      {
        path: "interviews",
        name: "HrInterviews",
        component: () => import("@/hr/pages/interviews/InterviewsPage.vue"),
        meta: {
          title: "面试日程",
          icon: "calendar-clock",
          requiresAuth: true,
          permissions: ["hr:interview:read"],
        },
      },
      {
        path: "channels",
        name: "HrChannels",
        component: () => import("@/hr/pages/channels/ChannelsPage.vue"),
        meta: {
          title: "渠道管理",
          icon: "radio",
          requiresAuth: true,
          permissions: ["hr:channel:read"],
        },
      },
      // ── 薪酬管理 ──
      {
        path: "salary-items",
        name: "HrSalaryItems",
        component: () => import("@/hr/pages/salary-items/SalaryItemsPage.vue"),
        meta: {
          title: "薪酬项",
          icon: "list-ordered",
          requiresAuth: true,
          permissions: ["hr:salary_item:read"],
        },
      },
      {
        path: "salary-bands",
        name: "HrSalaryBands",
        component: () => import("@/hr/pages/salary-bands/SalaryBandsPage.vue"),
        meta: {
          title: "职级薪带",
          icon: "trending-up",
          requiresAuth: true,
          permissions: ["hr:salary_band:read"],
        },
      },
      {
        path: "salary-packages",
        name: "HrSalaryPackages",
        component: () => import("@/hr/pages/salary-packages/SalaryPackagesPage.vue"),
        meta: {
          title: "定薪调薪",
          icon: "badge-dollar-sign",
          requiresAuth: true,
          permissions: ["hr:salary_package:read"],
        },
      },
      {
        path: "payroll-runs",
        name: "HrPayrollRuns",
        component: () => import("@/hr/pages/payroll-runs/PayrollRunsPage.vue"),
        meta: {
          title: "发薪批次",
          icon: "banknote",
          requiresAuth: true,
          permissions: ["hr:payroll:read"],
        },
      },
      // ── 绩效管理（二期批 B）──
      {
        path: "perf-cycles",
        name: "HrPerfCycles",
        component: () => import("@/hr/pages/perf-cycles/PerfCyclesPage.vue"),
        meta: {
          title: "考核周期",
          icon: "calendar-range",
          requiresAuth: true,
          permissions: ["hr:perf_cycle:read"],
        },
      },
      {
        path: "perf-reviews",
        name: "HrPerfReviews",
        component: () => import("@/hr/pages/perf-reviews/PerfReviewsPage.vue"),
        meta: {
          title: "评估管理",
          icon: "clipboard-check",
          requiresAuth: true,
          permissions: ["hr:perf_review:read"],
        },
      },
      // ── 审批中心（二期批 A）──
      {
        path: "approvals",
        name: "HrApprovals",
        component: () => import("@/hr/pages/approvals/ApprovalsPage.vue"),
        meta: {
          title: "审批管理",
          icon: "stamp",
          requiresAuth: true,
          permissions: ["hr:approval:read"],
        },
      },
      // ── 报表与自助（顶级菜单，无组父级）──
      {
        path: "reports",
        name: "HrReports",
        component: () => import("@/hr/pages/analytics/AnalyticsPage.vue"),
        meta: {
          title: "报表分析",
          icon: "bar-chart-3",
          requiresAuth: true,
          permissions: ["hr:report:read"],
        },
      },
      {
        path: "self-service",
        name: "HrSelfService",
        component: () => import("@/hr/pages/self-service/SelfServicePage.vue"),
        meta: { title: "员工自助", icon: "user-round", requiresAuth: true },
      },
      {
        path: "my-leave",
        name: "HrMyLeave",
        component: () => import("@/hr/pages/my-leave/MyLeavePage.vue"),
        meta: { title: "我的假期", icon: "palmtree", requiresAuth: true },
      },
      {
        path: "team",
        name: "HrTeam",
        component: () => import("@/hr/pages/team/TeamPage.vue"),
        meta: { title: "团队工作台", icon: "users", requiresAuth: true },
      },
    ],
  },
];
