/**
 * SalaryItemsPage 页面测试：列表渲染（类别/规则标识/停用态）、关键词筛选传参、
 * 编辑弹窗（编码置灰/提交走更新）、删除被引用拒绝提示、写权限显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SalaryItemsPage from "@/hr/pages/salary-items/SalaryItemsPage.vue";
import type { SalaryItem } from "@/hr/types/salary";

const permState = vi.hoisted(() => ({
  granted: new Set<string>(["hr:salary_item:read", "hr:salary_item:write", "hr:salary_item:delete"]),
}));

const apiMocks = vi.hoisted(() => ({
  listSalaryItems: vi.fn(),
  createSalaryItem: vi.fn(),
  updateSalaryItem: vi.fn(),
  deleteSalaryItem: vi.fn(),
  getSalaryCategories: vi.fn(),
  updateSalaryCategories: vi.fn(),
}));

vi.mock("@/hr/api/salary", () => ({
  listSalaryItems: apiMocks.listSalaryItems,
  createSalaryItem: apiMocks.createSalaryItem,
  updateSalaryItem: apiMocks.updateSalaryItem,
  deleteSalaryItem: apiMocks.deleteSalaryItem,
  getSalaryCategories: apiMocks.getSalaryCategories,
  updateSalaryCategories: apiMocks.updateSalaryCategories,
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

const ITEMS: SalaryItem[] = [
  {
    id: "it-1",
    code: "base_monthly",
    name: "月度基本工资",
    category: "base",
    ext_data: { taxable: true, monthly_fixed: true, unit: "元/月" },
    can_edit: true,
    sort: 10,
  },
  {
    id: "it-2",
    code: "bonus_annual",
    name: "年终奖",
    category: "bonus",
    ext_data: { taxable: true, monthly_fixed: false },
    can_edit: false,
    sort: 20,
  },
];

function mountPage() {
  return mount(SalaryItemsPage, { attachTo: document.body });
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
  permState.granted = new Set(["hr:salary_item:read", "hr:salary_item:write", "hr:salary_item:delete"]);
  apiMocks.listSalaryItems.mockResolvedValue({ code: 200, data: ITEMS, total: 2, page: 1, page_size: 20 });
  apiMocks.getSalaryCategories.mockResolvedValue({ code: 200, data: { categories: ["base", "bonus", "subsidy"] } });
  apiMocks.updateSalaryItem.mockResolvedValue({ code: 200, data: { ...ITEMS[0], name: "月度基本工资（改）" } });
  apiMocks.createSalaryItem.mockResolvedValue({ code: 200, data: ITEMS[0] });
  apiMocks.deleteSalaryItem.mockResolvedValue({ code: 200, data: null });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("SalaryItemsPage", () => {
  it("挂载后拉取薪酬项列表与类别字典，渲染规则标识与停用态", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listSalaryItems).toHaveBeenCalled();
    expect(apiMocks.getSalaryCategories).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("base_monthly");
    expect(body).toContain("月度基本工资");
    expect(body).toContain("计税 · 月度固定");
    expect(body).toContain("已停用");
  });

  it("关键词搜索携带 keyword 参数，all 哨兵不传 category", async () => {
    mountPage();
    await flushPromises();
    expect(apiMocks.listSalaryItems.mock.calls[0][0].category).toBeUndefined();

    setInputValue('[data-testid="salary-item-keyword-input"]', "基本");
    const search = document.querySelector<HTMLButtonElement>('[data-testid="salary-item-search"]');
    search!.click();
    await flushPromises();

    const lastCall = apiMocks.listSalaryItems.mock.calls.at(-1)![0];
    expect(lastCall.keyword).toBe("基本");
    expect(lastCall.category).toBeUndefined();
  });

  it("编辑弹窗编码置灰，改名后提交走更新并保留规则元数据", async () => {
    mountPage();
    await flushPromises();

    const editButton = findButton("编辑");
    expect(editButton, "行内应渲染编辑按钮").toBeTruthy();
    editButton!.click();
    await flushPromises();

    const codeHost = document.querySelector('[data-testid="salary-item-code-input"]');
    const codeInput = (codeHost?.querySelector("input") ?? codeHost) as HTMLInputElement | null;
    expect(codeInput?.disabled).toBe(true);

    setInputValue('[data-testid="salary-item-name-input"]', "月度基本工资（改）");
    await flushPromises();
    clickButton("salary-item-submit");
    await flushPromises();

    expect(apiMocks.updateSalaryItem).toHaveBeenCalledWith("it-1", {
      name: "月度基本工资（改）",
      category: "base",
      ext_data: { taxable: true, social_security_base: false, monthly_fixed: true, unit: "元/月" },
      sort: 10,
    });
  });

  it("删除被引用薪酬项被拒绝时提示仅可停用", async () => {
    apiMocks.deleteSalaryItem.mockRejectedValue({ code: 409, msg: "已被引用" });
    mountPage();
    await flushPromises();

    const removeButton = findButton("删除");
    expect(removeButton).toBeTruthy();
    removeButton!.click();
    await flushPromises();

    expect(apiMocks.deleteSalaryItem).toHaveBeenCalledWith("it-1");
    const { notifyError } = await import("@/framework/utils/feedback");
    expect(notifyError).toHaveBeenCalledWith(expect.anything(), expect.stringContaining("仅可停用"));
  });

  it("新增与维护按钮随写权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-salary-item"]')).toBeTruthy();
    expect(document.querySelector('[data-testid="open-category-manage"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:salary_item:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-create-salary-item"]')).toBeNull();
    expect(document.querySelector('[data-testid="open-category-manage"]')).toBeNull();
    expect(findButton("编辑")).toBeUndefined();
    withoutPerm.unmount();
  });
});
