/**
 * ChannelsPage 页面测试：渠道卡片渲染（接入状态/凭证/统计）、手动同步
 * 任务提交、已发布职位侧滑加载、同步按钮权限显隐
 */
import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChannelsPage from "@/hr/pages/channels/ChannelsPage.vue";
import type { ChannelCard } from "@/hr/types/recruiting";

const permState = vi.hoisted(() => ({ granted: new Set<string>(["hr:channel:read"]) }));

const routerPush = vi.hoisted(() => vi.fn());

const apiMocks = vi.hoisted(() => ({
  listChannels: vi.fn(),
  triggerChannelSync: vi.fn(),
  testChannelConnection: vi.fn(),
  listChannelPostings: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/hr/api/recruiting", () => ({
  listChannels: apiMocks.listChannels,
  triggerChannelSync: apiMocks.triggerChannelSync,
  testChannelConnection: apiMocks.testChannelConnection,
  listChannelPostings: apiMocks.listChannelPostings,
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

const CHANNELS: ChannelCard[] = [
  {
    channel: "zhilian",
    name: "智联招聘",
    configured: true,
    enabled: true,
    sync_enabled: true,
    collected_total: 12,
    last_sync_at: "2026-10-16T08:00:00",
  },
  {
    channel: "internal",
    name: "站内直投",
    configured: true,
    enabled: true,
    sync_enabled: false,
    collected_total: 3,
    last_sync_at: null,
  },
];

function mountPage() {
  return mount(ChannelsPage, { attachTo: document.body });
}

beforeEach(() => {
  vi.resetAllMocks();
  permState.granted = new Set(["hr:channel:read", "hr:channel:sync"]);
  apiMocks.listChannels.mockResolvedValue({ code: 200, data: CHANNELS });
  apiMocks.triggerChannelSync.mockResolvedValue({ code: 200, data: { task_id: "task-1", channel: "zhilian" } });
  apiMocks.testChannelConnection.mockResolvedValue({
    code: 200,
    data: { channel: "zhilian", ok: true, message: "凭证有效，渠道连通正常" },
  });
  apiMocks.listChannelPostings.mockResolvedValue({
    code: 200,
    data: [
      {
        id: "po-1",
        requisition_id: "req-1",
        channel: "zhilian",
        status: "published",
        external_post_id: "ZL-889",
        published_at: "2026-10-01T10:00:00",
      },
    ],
  });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("ChannelsPage", () => {
  it("挂载后拉取渠道清单并渲染卡片状态与统计", async () => {
    mountPage();
    await flushPromises();

    expect(apiMocks.listChannels).toHaveBeenCalled();
    expect(document.querySelectorAll('[data-testid="channel-card"]').length).toBe(2);
    expect(document.querySelector('[data-testid="channel-status-zhilian"]')?.textContent).toContain("已配置");
    const body = document.body.textContent ?? "";
    expect(body).toContain("累计归集：12");
    expect(body).toContain("站内直投");
  });

  it("手动同步走确认弹窗并提交任务（返回任务 ID）", async () => {
    mountPage();
    await flushPromises();

    const syncButton = document.querySelector<HTMLButtonElement>('[data-testid="channel-sync-zhilian"]');
    expect(syncButton).toBeTruthy();
    syncButton!.click();
    await flushPromises();

    expect(apiMocks.triggerChannelSync).toHaveBeenCalledWith("zhilian");
    const { notifySuccess } = await import("@/framework/utils/feedback");
    expect(notifySuccess).toHaveBeenCalledWith(expect.stringContaining("task-1"));
  });

  it("已发布职位侧滑按渠道加载 posting 列表", async () => {
    mountPage();
    await flushPromises();

    const postingsButton = document.querySelector<HTMLButtonElement>('[data-testid="channel-postings-zhilian"]');
    postingsButton!.click();
    await flushPromises();

    expect(apiMocks.listChannelPostings).toHaveBeenCalledWith("zhilian");
    expect(document.querySelector('[data-testid="channel-postings-sheet"]')).toBeTruthy();
    const body = document.body.textContent ?? "";
    expect(body).toContain("ZL-889");
    expect(body).toContain("已发布");
  });

  it("同步按钮随 hr:channel:sync 权限显隐，配置凭证跳转平台设置", async () => {
    const withPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="channel-sync-zhilian"]')).toBeTruthy();

    const settingsLink = [...document.querySelectorAll("button")].find((el) =>
      el.textContent?.includes("配置凭证"),
    );
    settingsLink!.click();
    expect(routerPush).toHaveBeenCalledWith("/iam/platform-settings");
    withPerm.unmount();
    document.body.innerHTML = "";

    permState.granted = new Set(["hr:channel:read"]);
    const withoutPerm = mountPage();
    await flushPromises();
    expect(document.querySelector('[data-testid="channel-sync-zhilian"]')).toBeNull();
    expect(document.querySelector('[data-testid="channel-test-zhilian"]')).toBeNull();
    withoutPerm.unmount();
  });

  it("连通测试点击调 test-connection，成功/失败分别提示", async () => {
    mountPage();
    await flushPromises();

    const testButton = document.querySelector<HTMLButtonElement>('[data-testid="channel-test-zhilian"]');
    expect(testButton).toBeTruthy();
    testButton!.click();
    await flushPromises();
    expect(apiMocks.testChannelConnection).toHaveBeenCalledWith("zhilian");
    const { notifySuccess } = await import("@/framework/utils/feedback");
    expect(notifySuccess).toHaveBeenCalledWith(expect.stringContaining("连通正常"));

    apiMocks.testChannelConnection.mockResolvedValue({
      code: 200,
      data: { channel: "zhilian", ok: false, message: "token 获取失败" },
    });
    const { notifyError } = await import("@/framework/utils/feedback");
    (notifyError as ReturnType<typeof vi.fn>).mockClear();
    testButton!.click();
    await flushPromises();
    expect(notifyError).toHaveBeenCalled();
  });
});
