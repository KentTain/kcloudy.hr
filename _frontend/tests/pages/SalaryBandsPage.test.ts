/**
 * SalaryBandsPage 页面测试：版本状态渲染（当前生效/未生效/历史只读）、
 * 新建版本预填与提交载荷、未生效版本编辑与删除、带宽校验拦截、写权限显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SalaryBandsPage from "@/hr/pages/salary-bands/SalaryBandsPage.vue";
import type { SalaryBand } from "@/hr/types/salary";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:salary_band:read", "hr:salary_band:write"]),
}));

const apiMocks = vi.hoisted(() => ({
  listSalaryBands: vi.fn(),
  createSalaryBand: vi.fn(),
  updateSalaryBand: vi.fn(),
  deleteSalaryBand: vi.fn(),
}));

vi.mock("@/hr/api/salary", () => ({
  listSalaryBands: apiMocks.listSalaryBands,
  createSalaryBand: apiMocks.createSalaryBand,
  updateSalaryBand: apiMocks.updateSalaryBand,
  deleteSalaryBand: apiMocks.deleteSalaryBand,
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

const BANDS: SalaryBand[] = [
  {
    id: "band-1",
    job_level: "P5",
    min_salary: 18000,
    mid_salary: 25000,
    max_salary: 35000,
    effective_from: "2026-01-01",
    effective_to: null,
  },
  {
    id: "band-2",
    job_level: "M2",
    min_salary: 30000,
    mid_salary: 40000,
    max_salary: 55000,
    effective_from: "2026-12-01",
    effective_to: "2027-12-31",
  },
  {
    id: "band-3",
    job_level: "P4",
    min_salary: 12000,
    mid_salary: 16000,
    max_salary: 22000,
    effective_from: "2025-01-01",
    effective_to: "2026-06-30",
  },
];

function mountPage() {
  return mount(SalaryBandsPage, { attachTo: document.body });
}

function findButton(text: string): HTMLButtonElement | undefined {
  return document
    .querySelectorAll("button")
    .values()
    .find((el) => el.textContent?.trim() === text) as HTMLButtonElement | undefined;
}

/** DialogContent 经 Teleport 渲染到 body，按钮点击走 document 查询 */
function clickButton(testid: string) {
  const el = document.querySelector(`[data-testid="${testid}"]`);
  if (el instanceof HTMLElement) el.click();
}

function setInputValue(selector: string, value: string) {
  const host = document.querySelector(selector);
  const input = host?.querySelector("input") ?? host;
  if (input instanceof HTMLInputElement) {
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:salary_band:read", "hr:salary_band:write"]);
  apiMocks.listSalaryBands.mockResolvedValue({ code: 200, data: BANDS, total: 3, page: 1, page_size: 20 });
  apiMocks.createSalaryBand.mockResolvedValue({ code: 200, data: BANDS[0] });
  apiMocks.updateSalaryBand.mockResolvedValue({ code: 200, data: BANDS[1] });
  apiMocks.deleteSalaryBand.mockResolvedValue({ code: 200, data: null });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SalaryBandsPage", () => {
  it("挂载后渲染版本状态：当前生效/未生效可编辑/历史只读", async () => {
    mountPage();
    await flushPromises();

    const body = document.body.textContent ?? "";
    expect(apiMocks.listSalaryBands).toHaveBeenCalled();
    expect(body).toContain("P5");
    expect(body).toContain("25,000.00");
    expect(body).toContain("当前生效");
    expect(body).toContain("未生效");
    expect(body).toContain("历史版本");
    expect(body).toContain("只读");
    // 带宽条带 mid 标记渲染
    expect(document.querySelector(".bg-primary.rounded-full")).toBeTruthy();
  });

  it("当前版本行「新建版本」预填带宽，提交走创建（自动闭合旧区间）", async () => {
    mountPage();
    await flushPromises();

    const newVersionButton = findButton("新建版本");
    expect(newVersionButton, "当前生效行应渲染新建版本按钮").toBeTruthy();
    newVersionButton!.click();
    await flushPromises();

    const jobLevelHost = document.querySelector('[data-testid="band-job-level-input"]');
    const jobLevelInput = (jobLevelHost?.querySelector("input") ?? jobLevelHost) as HTMLInputElement | null;
    expect(jobLevelInput?.value).toBe("P5");
    expect(jobLevelInput?.disabled).toBe(false);

    clickButton("band-submit");
    await flushPromises();

    expect(apiMocks.createSalaryBand).toHaveBeenCalledWith({
      job_level: "P5",
      min_salary: 18000,
      mid_salary: 25000,
      max_salary: 35000,
      effective_from: "2026-01-01",
      effective_to: undefined,
    });
  });

  it("未生效版本可编辑，提交走更新且职级不可改", async () => {
    mountPage();
    await flushPromises();

    const editButton = findButton("编辑");
    expect(editButton, "未生效版本行应渲染编辑按钮").toBeTruthy();
    editButton!.click();
    await flushPromises();

    const jobLevelHost = document.querySelector('[data-testid="band-job-level-input"]');
    const jobLevelInput = (jobLevelHost?.querySelector("input") ?? jobLevelHost) as HTMLInputElement | null;
    expect(jobLevelInput?.disabled).toBe(true);

    setInputValue('[data-testid="band-mid-input"]', "42000");
    await flushPromises();
    clickButton("band-submit");
    await flushPromises();

    expect(apiMocks.updateSalaryBand).toHaveBeenCalledWith("band-2", {
      min_salary: 30000,
      mid_salary: 42000,
      max_salary: 55000,
      effective_from: "2026-12-01",
      effective_to: "2027-12-31",
    });
  });

  it("min > max 前端拦截，不发起提交", async () => {
    mountPage();
    await flushPromises();

    findButton("新建版本")!.click();
    await flushPromises();
    setInputValue('[data-testid="band-min-input"]', "40000");
    await flushPromises();
    clickButton("band-submit");
    await flushPromises();

    expect(apiMocks.createSalaryBand).not.toHaveBeenCalled();
    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining("下限") }));
  });

  it("未生效版本删除走确认，历史版本无删除入口；写权限隐藏维护入口", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-band"]')).toBeTruthy();

    const removeButton = findButton("删除");
    expect(removeButton).toBeTruthy();
    removeButton!.click();
    await flushPromises();
    expect(apiMocks.deleteSalaryBand).toHaveBeenCalledWith("band-2");
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:salary_band:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-band"]')).toBeNull();
    expect(findButton("新建版本")).toBeUndefined();
    withoutPerm.unmount();
  });
});
