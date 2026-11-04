/**
 * RequisitionsPage 页面测试：列表加载与参照解析（组织/渠道计数）、
 * 新建按钮权限显隐、行内关闭需求走确认弹窗
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RequisitionsPage from "@/hr/pages/requisitions/RequisitionsPage.vue";
import type { OrgTreeNode } from "@/hr/types/employee";
import type { Requisition } from "@/hr/types/recruiting";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:requisition:read"]) }));

const apiMocks = vi.hoisted(() => ({
  listRequisitions: vi.fn(),
  getRequisition: vi.fn(),
  createRequisition: vi.fn(),
  updateRequisition: vi.fn(),
  closeRequisition: vi.fn(),
  publishRequisition: vi.fn(),
  offlinePosting: vi.fn(),
  getRequisitionFunnel: vi.fn(),
  listRequisitionApplications: vi.fn(),
  updateApplicationStage: vi.fn(),
  listChannels: vi.fn(),
  getOrgTree: vi.fn(),
  getPositionOptions: vi.fn(),
}));

vi.mock("@/hr/api/recruiting", () => ({
  listRequisitions: apiMocks.listRequisitions,
  getRequisition: apiMocks.getRequisition,
  createRequisition: apiMocks.createRequisition,
  updateRequisition: apiMocks.updateRequisition,
  closeRequisition: apiMocks.closeRequisition,
  publishRequisition: apiMocks.publishRequisition,
  offlinePosting: apiMocks.offlinePosting,
  generateJdDraft: vi.fn(),
  getRequisitionFunnel: apiMocks.getRequisitionFunnel,
  listRequisitionApplications: apiMocks.listRequisitionApplications,
  updateApplicationStage: apiMocks.updateApplicationStage,
  listChannels: apiMocks.listChannels,
}));

vi.mock("@/hr/api/reference", () => ({
  getOrgTree: apiMocks.getOrgTree,
  getPositionOptions: apiMocks.getPositionOptions,
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

const REQUISITIONS: Requisition[] = [
  {
    id: "req-1",
    req_no: "REQ-2026-001",
    title: "后端工程师（支付方向）",
    org_id: "org-2",
    position_id: "pos-1",
    headcount: 3,
    job_level: "P6",
    salary_min: 20000,
    salary_max: 40000,
    priority: "high",
    status: "recruiting",
    jd: null,
    filled_count: 1,
    postings: [
      { id: "po-1", channel: "internal", status: "published", external_post_id: null, published_at: "2026-10-01T10:00:00" },
      { id: "po-2", channel: "zhilian", status: "publishing", external_post_id: null, published_at: null },
    ],
  },
];

const ORG_TREE: OrgTreeNode[] = [
  { id: "org-1", name: "总公司", children: [{ id: "org-2", name: "研发部", children: [] }] },
];

function mountPage() {
  return mount(RequisitionsPage, { attachTo: document.body });
}

function findButton(text: string): HTMLButtonElement | undefined {
  return document
    .querySelectorAll("button")
    .values()
    .find((el) => el.textContent?.trim() === text) as HTMLButtonElement | undefined;
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:requisition:read", "hr:requisition:write", "hr:candidate:read"]);
  apiMocks.listRequisitions.mockResolvedValue({ code: 200, data: REQUISITIONS, total: 1, page: 1, page_size: 20 });
  apiMocks.getOrgTree.mockResolvedValue({ code: 200, data: ORG_TREE });
  apiMocks.getPositionOptions.mockResolvedValue({
    code: 200,
    data: [{ id: "pos-1", name: "后端工程师", code: "BE", job_level: "P5", status: "active" }],
  });
  apiMocks.listChannels.mockResolvedValue({ code: 200, data: [] });
  apiMocks.closeRequisition.mockResolvedValue({ code: 200, data: { id: "req-1" } });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("RequisitionsPage", () => {
  it("挂载后拉取需求列表与组织参照，并渲染行数据（组织解析/入职招聘比/渠道计数）", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listRequisitions).toHaveBeenCalled();
    expect(apiMocks.getOrgTree).toHaveBeenCalled();
    const body = document.body.textContent ?? "";
    expect(body).toContain("REQ-2026-001");
    expect(body).toContain("后端工程师（支付方向）");
    expect(body).toContain("研发部");
    expect(body).toContain("1 / 3");
    expect(body).toContain("2 个渠道");
  });

  it("新建需求按钮随 hr:requisition:write 权限显隐", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-requisition-form"]')).toBeTruthy();
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:requisition:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="open-requisition-form"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("行内关闭需求：确认后调 closeRequisition 并刷新列表", async () => {
    mountPage();
    await flushPromises();
    expect(apiMocks.listRequisitions).toHaveBeenCalledTimes(1);

    const closeButton = findButton("关闭");
    expect(closeButton, "行操作应内联渲染关闭按钮").toBeTruthy();
    closeButton!.click();
    await flushPromises();

    expect(apiMocks.closeRequisition).toHaveBeenCalledWith("req-1");
    expect(apiMocks.listRequisitions.mock.calls.length).toBeGreaterThanOrEqual(2);
  });
});
