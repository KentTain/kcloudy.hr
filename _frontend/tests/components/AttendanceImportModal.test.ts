/**
 * AttendanceImportModal（Excel 导入）测试：dryRun 预检载荷与逐行结果回显、
 * 失败行时确认按钮禁用、无失败确认导入载荷与反馈计数、模板下载
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AttendanceImportModal from "@/hr/components/attendance/AttendanceImportModal.vue";
import type { AttendanceImportResult } from "@/hr/types/attendance";

const apiMocks = vi.hoisted(() => ({
  getImportTemplate: vi.fn(),
  importAttendance: vi.fn(),
}));

vi.mock("@/hr/api/attendance", () => ({
  getImportTemplate: apiMocks.getImportTemplate,
  importAttendance: apiMocks.importAttendance,
  listAttendanceRecords: vi.fn(),
  getAttendanceStats: vi.fn(),
  createAiImportBatch: vi.fn(),
  getAiImportBatch: vi.fn(),
  confirmAiImportBatch: vi.fn(),
  retryAiImportBatch: vi.fn(),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function makeResult(overrides: Partial<AttendanceImportResult> = {}): AttendanceImportResult {
  return {
    batch_id: "batch-1",
    dry_run: true,
    row_results: [
      {
        row_index: 2,
        employee_no: "EMP001",
        employee_name: "张三",
        work_date: "2026-10-16",
        parseable: true,
        error: null,
        selected: true,
        data: {},
      },
      {
        row_index: 3,
        employee_no: "BAD",
        employee_name: "未知",
        work_date: "2026-10-16",
        parseable: false,
        error: "员工不存在（工号+姓名无法匹配花名册）",
        selected: false,
        data: null,
      },
    ],
    new_count: 0,
    overwrite_count: 0,
    fail_count: 1,
    ...overrides,
  };
}

function makeFile(): File {
  return new File(["attendance"], "attendance.csv", { type: "text/csv" });
}

function mountModal(open = true): VueWrapper {
  return mount(AttendanceImportModal, {
    props: { open },
    attachTo: document.body,
  });
}

function selectFile(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[data-testid="attendance-import-file"]');
  if (!input) throw new Error("file input not found");
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.importAttendance.mockResolvedValue({ code: 200, data: makeResult() });
  apiMocks.getImportTemplate.mockResolvedValue({
    code: 200,
    data: { filename: "考勤导入模板.xlsx", content_base64: btoa("template-bytes") },
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("AttendanceImportModal", () => {
  it("选文件后预检走 dryRun=true，逐行回显可导入与失败原因，失败行时确认禁用", async () => {
    const wrapper = mountModal();
    await flushPromises();

    selectFile(makeFile());
    await flushPromises();
    clickButton("attendance-import-preview");
    await flushPromises();

    expect(apiMocks.importAttendance).toHaveBeenCalledTimes(1);
    const form = apiMocks.importAttendance.mock.calls[0][1] as boolean;
    expect(form).toBe(true);

    const table = document.querySelector('[data-testid="attendance-preview-table"]')?.textContent ?? "";
    expect(table).toContain("EMP001");
    expect(table).toContain("可导入");
    expect(table).toContain("员工不存在");

    const confirmBtn = document.querySelector<HTMLButtonElement>('[data-testid="attendance-import-confirm"]');
    expect(confirmBtn?.disabled).toBe(true);
    expect(confirmBtn?.textContent).toContain("修正后重传");
    wrapper.unmount();
  });

  it("无失败行确认导入走 dryRun=false，回显新增/覆盖计数并 emit saved", async () => {
    apiMocks.importAttendance.mockImplementation(async (_file: File, dryRun: boolean) => ({
      code: 200,
      data: makeResult({
        dry_run: dryRun,
        fail_count: 0,
        row_results: [
          {
            row_index: 2,
            employee_no: "EMP001",
            employee_name: "张三",
            work_date: "2026-10-16",
            parseable: true,
            error: null,
            selected: true,
            data: {},
          },
        ],
        new_count: dryRun ? 0 : 1,
        overwrite_count: dryRun ? 0 : 2,
      }),
    }));

    const wrapper = mountModal();
    await flushPromises();

    selectFile(makeFile());
    await flushPromises();
    clickButton("attendance-import-preview");
    await flushPromises();

    const confirmBtn = document.querySelector<HTMLButtonElement>('[data-testid="attendance-import-confirm"]');
    expect(confirmBtn?.disabled).toBe(false);
    clickButton("attendance-import-confirm");
    await flushPromises();

    expect(apiMocks.importAttendance).toHaveBeenCalledTimes(2);
    expect(apiMocks.importAttendance.mock.calls[1][1]).toBe(false);

    const result = document.querySelector('[data-testid="attendance-import-result"]')?.textContent ?? "";
    expect(result).toContain("1");
    expect(result).toContain("2");
    expect(wrapper.emitted("saved")).toHaveLength(1);
    wrapper.unmount();
  });

  it("下载模板经 base64 转 Blob 触发下载", async () => {
    const wrapper = mountModal();
    await flushPromises();

    const createObjectURL = vi.fn(() => "blob:mock-template");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, "revokeObjectURL", { value: revokeObjectURL, configurable: true });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    clickButton("attendance-template-download");
    await flushPromises();

    expect(apiMocks.getImportTemplate).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
    clickSpy.mockRestore();
    Reflect.deleteProperty(URL, "createObjectURL");
    Reflect.deleteProperty(URL, "revokeObjectURL");
    wrapper.unmount();
  });
});
