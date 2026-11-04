/**
 * AttendanceAiImportModal（AI 导入）测试：上传创建批次进入轮询、解析完成
 * 进入预览且默认勾选可解析行、取消勾选后确认载荷只含勾选行、解析失败重试
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AttendanceAiImportModal from "@/hr/components/attendance/AttendanceAiImportModal.vue";
import type { AttendanceBatch } from "@/hr/types/attendance";

const apiMocks = vi.hoisted(() => ({
  createAiImportBatch: vi.fn(),
  getAiImportBatch: vi.fn(),
  confirmAiImportBatch: vi.fn(),
  retryAiImportBatch: vi.fn(),
  listAiImportBatches: vi.fn(),
  exportAiBatchFailures: vi.fn(),
}));

vi.mock("@/hr/api/attendance", () => ({
  createAiImportBatch: apiMocks.createAiImportBatch,
  getAiImportBatch: apiMocks.getAiImportBatch,
  confirmAiImportBatch: apiMocks.confirmAiImportBatch,
  retryAiImportBatch: apiMocks.retryAiImportBatch,
  listAiImportBatches: apiMocks.listAiImportBatches,
  exportAiBatchFailures: apiMocks.exportAiBatchFailures,
  getImportTemplate: vi.fn(),
  importAttendance: vi.fn(),
  listAttendanceRecords: vi.fn(),
  getAttendanceStats: vi.fn(),
}));

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

function makeBatch(overrides: Partial<AttendanceBatch> = {}): AttendanceBatch {
  return {
    id: "batch-ai-1",
    channel: "ai",
    status: "parsing",
    file_id: "file-1",
    filename: "attendance.png",
    field_mapping: null,
    row_results: null,
    new_count: 0,
    overwrite_count: 0,
    discard_count: 0,
    fail_count: 0,
    created_at: null,
    ...overrides,
  };
}

const PARSED_ROWS = [
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
    employee_no: "EMP002",
    employee_name: "李四",
    work_date: "2026-10-16",
    parseable: true,
    error: null,
    selected: true,
    data: {},
  },
  {
    row_index: 4,
    employee_no: null,
    employee_name: "路人",
    work_date: "2026-10-16",
    parseable: false,
    error: "未匹配员工",
    selected: false,
    data: null,
  },
];

function makeFile(): File {
  return new File(["img"], "attendance.png", { type: "image/png" });
}

function mountModal(open = true): VueWrapper {
  return mount(AttendanceAiImportModal, {
    props: { open },
    attachTo: document.body,
  });
}

function selectFile(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[data-testid="attendance-ai-file"]');
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
  apiMocks.createAiImportBatch.mockResolvedValue({ code: 200, data: makeBatch() });
  apiMocks.getAiImportBatch.mockResolvedValue({
    code: 200,
    data: makeBatch({ status: "parsed", row_results: PARSED_ROWS }),
  });
  apiMocks.confirmAiImportBatch.mockResolvedValue({
    code: 200,
    data: makeBatch({ status: "completed", new_count: 1, overwrite_count: 1, row_results: PARSED_ROWS }),
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("AttendanceAiImportModal", () => {
  it("上传创建批次后轮询到解析完成，进入预览且默认勾选可解析行", async () => {
    const wrapper = mountModal();
    await flushPromises();

    selectFile(makeFile());
    await flushPromises();
    clickButton("attendance-ai-upload");
    await flushPromises();

    expect(apiMocks.createAiImportBatch).toHaveBeenCalledTimes(1);
    expect(apiMocks.getAiImportBatch).toHaveBeenCalledWith("batch-ai-1");
    // 轮询首轮即返回 parsed，直接进入预览
    expect(document.querySelector('[data-testid="attendance-ai-preview-table"]')).toBeTruthy();

    const table = document.querySelector('[data-testid="attendance-ai-preview-table"]')?.textContent ?? "";
    expect(table).toContain("EMP001");
    expect(table).toContain("未匹配员工");

    const check2 = document.querySelector<HTMLInputElement>('[data-testid="attendance-ai-row-check-2"]');
    const check4 = document.querySelector<HTMLInputElement>('[data-testid="attendance-ai-row-check-4"]');
    expect(check2?.checked).toBe(true);
    expect(check4?.checked).toBe(false);
    expect(check4?.disabled).toBe(true);
    wrapper.unmount();
  });

  it("取消一行勾选后确认载荷只含勾选行，回显计数并 emit saved", async () => {
    const wrapper = mountModal();
    await flushPromises();

    selectFile(makeFile());
    await flushPromises();
    clickButton("attendance-ai-upload");
    await flushPromises();

    const check3 = document.querySelector<HTMLInputElement>('[data-testid="attendance-ai-row-check-3"]');
    check3?.click();
    await flushPromises();

    clickButton("attendance-ai-confirm");
    await flushPromises();

    expect(apiMocks.confirmAiImportBatch).toHaveBeenCalledTimes(1);
    expect(apiMocks.confirmAiImportBatch).toHaveBeenCalledWith("batch-ai-1", [2]);

    const result = document.querySelector('[data-testid="attendance-ai-result"]')?.textContent ?? "";
    expect(result).toContain("导入完成");
    expect(wrapper.emitted("saved")).toHaveLength(1);
    wrapper.unmount();
  });

  it("解析失败展示重试入口并调用重新解析", async () => {
    apiMocks.getAiImportBatch.mockResolvedValue({
      code: 200,
      data: makeBatch({ status: "failed" }),
    });
    apiMocks.retryAiImportBatch.mockResolvedValue({ code: 200, data: makeBatch({ status: "parsing" }) });

    const wrapper = mountModal();
    await flushPromises();

    selectFile(makeFile());
    await flushPromises();
    clickButton("attendance-ai-upload");
    await flushPromises();

    expect(document.querySelector('[data-testid="attendance-ai-status-failed"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="attendance-ai-retry"]')).toBeTruthy();

    clickButton("attendance-ai-retry");
    await flushPromises();

    expect(apiMocks.retryAiImportBatch).toHaveBeenCalledWith("batch-ai-1");
    wrapper.unmount();
  });

  it("打开弹窗加载历史批次，有失败行的批次可下载失败明细", async () => {
    apiMocks.listAiImportBatches.mockResolvedValue({
      code: 200,
      data: {
        total: 2,
        items: [
          makeBatch({ id: "batch-old-1", status: "completed", new_count: 5, fail_count: 2, created_at: "2026-10-17T09:00:00" }),
          makeBatch({ id: "batch-old-2", status: "parsed", new_count: 0, fail_count: 0 }),
        ],
      },
    });
    apiMocks.exportAiBatchFailures.mockResolvedValue({
      code: 200,
      data: { filename: "考勤导入失败明细-batch-ol.xlsx", content_base64: "aGk=" },
    });

    const wrapper = mount(AttendanceAiImportModal, {
      props: { open: false },
      attachTo: document.body,
    });
    await flushPromises();
    // watch 非 immediate：以 open 翻转触发 resetState + loadHistory
    await wrapper.setProps({ open: true });
    await flushPromises();

    expect(apiMocks.listAiImportBatches).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    const history = document.querySelector('[data-testid="attendance-ai-history"]');
    expect(history).not.toBeNull();
    expect(history?.textContent).toContain("失败 2");
    expect(document.querySelector('[data-testid="attendance-ai-failures-batch-old-1"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="attendance-ai-failures-batch-old-2"]')).toBeNull();

    clickButton("attendance-ai-failures-batch-old-1");
    await flushPromises();

    expect(apiMocks.exportAiBatchFailures).toHaveBeenCalledWith("batch-old-1");
    wrapper.unmount();
  });
});
