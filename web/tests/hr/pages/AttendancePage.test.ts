/**
 * AttendancePage 页面测试：总览统计卡+部门统计表渲染（默认近 1 月档位）、
 * 搜索联动两区刷新（参数带筛选）、导入按钮权限显隐、重置恢复默认
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AttendancePage from "@/hr/pages/attendance/AttendancePage.vue";
import type { AttendanceRecord, AttendanceStats } from "@/hr/types/attendance";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:attendance:read", "hr:attendance:import"]),
}));

const apiMocks = vi.hoisted(() => ({
  listAttendanceRecords: vi.fn(),
  getAttendanceStats: vi.fn(),
  getOrgTree: vi.fn(),
}));

vi.mock("@/hr/api/attendance", () => ({
  listAttendanceRecords: apiMocks.listAttendanceRecords,
  getAttendanceStats: apiMocks.getAttendanceStats,
  getImportTemplate: vi.fn(),
  importAttendance: vi.fn(),
  createAiImportBatch: vi.fn(),
  getAiImportBatch: vi.fn(),
  confirmAiImportBatch: vi.fn(),
  retryAiImportBatch: vi.fn(),
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: vi.fn(),
  listEmployeeSalaryPackages: vi.fn(),
  getBandComparison: vi.fn(),
  listSalaryItemOptions: vi.fn(),
}));

vi.mock("@/framework/stores", () => ({
  useUserStore: () => ({
    hasPermission: (code: string) => permState.granted.has(code),
  }),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const RECORDS: AttendanceRecord[] = [
  {
    id: "rec-1",
    employee_id: "emp-1",
    employee_no: "EMP001",
    employee_name: "张三",
    org_id: "org-1",
    work_date: "2026-10-16",
    check_in_time: "2026-10-16T09:12:00",
    check_out_time: "2026-10-16T18:05:00",
    work_hours: 8.1,
    overtime_hours: 0,
    status: "late",
    source: "excel",
    remark: null,
  },
  {
    id: "rec-2",
    employee_id: "emp-2",
    employee_no: "EMP002",
    employee_name: "李四",
    org_id: "org-1",
    work_date: "2026-10-16",
    check_in_time: null,
    check_out_time: null,
    work_hours: null,
    overtime_hours: null,
    status: "absent",
    source: "ai",
    remark: "未打卡",
  },
];

const STATS: AttendanceStats = {
  cards: {
    total_records: 2,
    attendance_count: 1,
    late_count: 1,
    early_leave_count: 0,
    absent_count: 1,
    attendance_rate: 50.0,
  },
  org_slices: [
    {
      org_id: "org-1",
      total_records: 2,
      attendance_count: 1,
      late_count: 1,
      early_leave_count: 0,
      missing_card_count: 0,
      absent_count: 1,
      attendance_rate: 50.0,
    },
  ],
};

function mountPage(): VueWrapper {
  return mount(AttendancePage, { attachTo: document.body });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:attendance:read", "hr:attendance:import"]);
  apiMocks.listAttendanceRecords.mockResolvedValue({
    code: 200,
    data: RECORDS,
    total: 2,
    page: 1,
    page_size: 20,
  });
  apiMocks.getAttendanceStats.mockResolvedValue({ code: 200, data: STATS });
  apiMocks.getOrgTree.mockResolvedValue({
    code: 200,
    data: [{ id: "org-1", name: "研发部", children: [] }],
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("AttendancePage", () => {
  it("挂载渲染总览统计卡+部门统计表+考勤记录列表（迟到/缺勤状态标识）", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.getAttendanceStats).toHaveBeenCalledTimes(1);
    expect(apiMocks.listAttendanceRecords).toHaveBeenCalledTimes(1);
    const body = document.body.textContent ?? "";
    expect(body).toContain("出勤人次");
    expect(body).toContain("50.00%");
    expect(body).toContain("研发部");
    expect(body).toContain("张三");
    expect(body).toContain("迟到");
    expect(body).toContain("缺勤");
    expect(document.querySelector('[data-testid="stat-card-rate"]')?.textContent).toContain("50.00%");
  });

  it("搜索按钮联动总览与列表刷新（参数带部门/关键词）", async () => {
    const wrapper = mountPage();
    await flushPromises();
    expect(apiMocks.getAttendanceStats).toHaveBeenCalledTimes(1);

    // Input testid 落根 div，v-model 监听在内层原生 input 上
    const keywordHost = document.querySelector('[data-testid="attendance-keyword-input"]');
    const keywordInput = (keywordHost?.querySelector("input") ?? keywordHost) as HTMLInputElement | null;
    if (keywordInput) {
      keywordInput.value = "张三";
      keywordInput.dispatchEvent(new Event("input"));
    }
    await flushPromises();

    clickButton("attendance-search");
    await flushPromises();

    expect(apiMocks.getAttendanceStats).toHaveBeenCalledTimes(2);
    expect(apiMocks.getAttendanceStats).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: "张三" }),
    );
    expect(apiMocks.listAttendanceRecords).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: "张三", date_from: expect.any(String), date_to: expect.any(String) }),
    );
    wrapper.unmount();
  });

  it("无 hr:attendance:import 权限时导入按钮不可见", async () => {
    permState.granted = new Set(["hr:attendance:read"]);
    const wrapper = mountPage();
    await flushPromises();

    expect(document.querySelector('[data-testid="open-excel-import"]')).toBeNull();
    expect(document.querySelector('[data-testid="open-ai-import"]')).toBeNull();
    wrapper.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:attendance:read", "hr:attendance:import"]);
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-excel-import"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="open-ai-import"]')).toBeTruthy();
    withPerm.unmount();
  });

  it("重置恢复默认筛选并刷新两区", async () => {
    const wrapper = mountPage();
    await flushPromises();

    clickButton("attendance-filter-reset");
    await flushPromises();

    expect(apiMocks.getAttendanceStats).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: undefined, org_id: undefined }),
    );
    expect(apiMocks.listAttendanceRecords).toHaveBeenLastCalledWith(
      expect.objectContaining({ keyword: undefined, org_id: undefined }),
    );
    wrapper.unmount();
  });
});
