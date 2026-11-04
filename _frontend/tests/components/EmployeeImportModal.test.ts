/**
 * EmployeeImportModal 单元测试：CSV 文件解析行数 + dryRun 预检/确认导入载荷
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmployeeImportModal from "@/hr/components/employee/EmployeeImportModal.vue";

const apiMocks = vi.hoisted(() => ({
  importEmployees: vi.fn(),
}));

vi.mock("@/hr/api/employee", () => ({
  importEmployees: apiMocks.importEmployees,
}));

vi.mock("@/framework/utils/feedback", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const RESULT = {
  dry_run: true,
  total: 1,
  success_count: 1,
  failure_count: 0,
  rows: [{ row_index: 0, success: true, employee_no: "EMP001", error: null }],
};

function mountModal() {
  return mount(EmployeeImportModal, {
    props: { open: true, "onUpdate:open": vi.fn(), onImported: vi.fn() },
    attachTo: document.body,
  });
}

function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  expect(el, `missing button ${testid}`).toBeTruthy();
  (el as HTMLButtonElement).click();
}

const CSV = "姓名,入职日期\n张三,2026-05-01\n李四,2026-06-01\n";

/** jsdom File 无 text()，补桩返回构造内容 */
function makeCsvFile(): File {
  const file = new File([CSV], "rows.csv", { type: "text/csv" });
  Object.defineProperty(file, "text", { value: async () => CSV });
  return file;
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.importEmployees.mockResolvedValue({ code: 200, data: RESULT });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("EmployeeImportModal", () => {
  it("选择文件后解析出行并回显计数", async () => {
    const wrapper = mountModal();
    await flushPromises();

    const dropzone = wrapper.findComponent({ name: "FileDropzone" });
    expect(dropzone.exists()).toBe(true);
    await dropzone.vm.$emit("select", [makeCsvFile()]);
    await flushPromises();

    const counter = document.querySelector('[data-testid="import-row-count"]');
    expect(counter?.textContent).toContain("2");
  });

  it("预检走 dry_run:true，确认导入走 dry_run:false", async () => {
    const wrapper = mountModal();
    await flushPromises();

    const dropzone = wrapper.findComponent({ name: "FileDropzone" });
    await dropzone.vm.$emit("select", [makeCsvFile()]);
    await flushPromises();

    clickButton("import-dry-run");
    await flushPromises();
    expect(apiMocks.importEmployees).toHaveBeenCalledWith({
      dry_run: true,
      rows: [
        expect.objectContaining({ name: "张三", hire_date: "2026-05-01" }),
        expect.objectContaining({ name: "李四", hire_date: "2026-06-01" }),
      ],
    });
    expect(document.querySelector('[data-testid="import-result-summary"]')?.textContent).toContain("成功 1");

    clickButton("import-confirm");
    await flushPromises();
    expect(apiMocks.importEmployees).toHaveBeenCalledTimes(2);
    expect(apiMocks.importEmployees.mock.calls[1][0].dry_run).toBe(false);
  });

  it("未解析文件时预检/导入被拦截", async () => {
    mountModal();
    await flushPromises();

    clickButton("import-dry-run");
    await flushPromises();
    expect(apiMocks.importEmployees).not.toHaveBeenCalled();
  });
});
