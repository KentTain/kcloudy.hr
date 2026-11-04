/**
 * FieldDefinitionManager 单元测试：属性组/定义加载渲染 + 新增定义载荷
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FieldDefinitionManager from "@/hr/components/employee/FieldDefinitionManager.vue";
import type { FieldDefinition, FieldGroup } from "@/hr/types/employee";

const apiMocks = vi.hoisted(() => ({
  listFieldGroups: vi.fn(),
  createFieldGroup: vi.fn(),
  updateFieldGroup: vi.fn(),
  deleteFieldGroup: vi.fn(),
  listFieldDefinitions: vi.fn(),
  createFieldDefinition: vi.fn(),
  updateFieldDefinition: vi.fn(),
  deleteFieldDefinition: vi.fn(),
}));

vi.mock("@/hr/api/field", () => apiMocks);

vi.mock("@/framework/utils/feedback", () => ({
  confirmAction: vi.fn(async () => true),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}));

const GROUPS: FieldGroup[] = [
  { id: "g-custom", code: "custom", name: "自定义信息", sort: 5 },
  { id: "g-basic", code: "basic", name: "基础信息", sort: 1 },
];

const DEFINITIONS: FieldDefinition[] = [
  {
    id: "def-1",
    group_id: "g-custom",
    name: "紧急联系人",
    data_type: "string",
    ext_data: null,
    is_require: false,
    can_edit: true,
    sort: 1,
  },
];

function mountModal() {
  return mount(FieldDefinitionManager, {
    props: { open: true, "onUpdate:open": vi.fn() },
    attachTo: document.body,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  apiMocks.listFieldGroups.mockResolvedValue({ code: 200, data: GROUPS });
  apiMocks.listFieldDefinitions.mockResolvedValue({ code: 200, data: [] });
  apiMocks.createFieldDefinition.mockResolvedValue({ code: 200, data: {} });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("FieldDefinitionManager", () => {
  it("加载属性组并默认选中排序首组，组内定义渲染", async () => {
    mountModal();
    await flushPromises();

    const items = document.querySelectorAll('[data-testid="field-group-item"]');
    expect(items.length).toBe(2);
    // 排序首组 basic（sort=1）默认选中
    expect(items[0].getAttribute("data-group-id")).toBe("g-basic");
    // basic 组暂无定义 → 空态
    expect(document.querySelector('[data-testid="field-definition-table"]')?.textContent).toContain("暂无字段定义");
  });

  it("新增字段定义：载荷带组 ID 与表单值", async () => {
    apiMocks.listFieldDefinitions.mockImplementation((groupId?: string) =>
      Promise.resolve({ code: 200, data: groupId === "g-custom" ? DEFINITIONS : [] }),
    );
    mountModal();
    await flushPromises();

    // 切到 custom 组
    const items = document.querySelectorAll('[data-testid="field-group-item"]');
    (items[1] as HTMLButtonElement).click();
    await flushPromises();

    document.querySelector('[data-testid="field-definition-add"]')?.dispatchEvent(new Event("click"));
    await flushPromises();

    const nameInput = document.querySelector('[data-testid="field-definition-name"] input') as HTMLInputElement;
    nameInput.value = "政治面貌";
    nameInput.dispatchEvent(new Event("input"));

    document.querySelector('[data-testid="field-definition-submit"]')?.dispatchEvent(new Event("click"));
    await flushPromises();

    expect(apiMocks.createFieldDefinition).toHaveBeenCalledTimes(1);
    const payload = apiMocks.createFieldDefinition.mock.calls[0][0];
    expect(payload.group_id).toBe("g-custom");
    expect(payload.name).toBe("政治面貌");
    expect(payload.data_type).toBe("string");
  });
});
