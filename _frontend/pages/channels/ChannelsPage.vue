<script setup lang="ts">
/**
 * 渠道管理页：渠道卡片栅格（接入状态/凭证状态/同步开关/统计）+ 手动同步
 * + 已发布职位侧滑。凭证本身在 iam 平台设置维护，本页只读投影并跳转入口。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { Badge, Button, Table } from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { listChannelPostings, listChannels, testChannelConnection, triggerChannelSync } from "@/hr/api/recruiting";
import {
  CHANNEL_LABELS,
  POSTING_STATUS_LABELS,
  POSTING_STATUS_VARIANTS,
  type ChannelCard,
  type RequisitionPosting,
} from "@/hr/types/recruiting";

const router = useRouter();
const userStore = useUserStore();
const canSync = computed(() => userStore.hasPermission("hr:channel:sync"));

const channels = ref<ChannelCard[]>([]);
const loading = ref(false);

function accessStatusOf(item: ChannelCard): { label: string; variant: "default" | "secondary" | "destructive" | "outline" } {
  if (!item.enabled) return { label: "已禁用", variant: "destructive" };
  if (item.configured) return { label: "已配置", variant: "default" };
  return { label: "未配置", variant: "secondary" };
}

async function loadChannels() {
  loading.value = true;
  try {
    const res = await listChannels();
    channels.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "渠道清单加载失败"));
    channels.value = [];
  } finally {
    loading.value = false;
  }
}

async function handleSync(item: ChannelCard) {
  if (!(await confirmAction(`确定手动触发「${item.name}」候选人拉取？任务将异步执行，完成后站内信回告。`))) return;
  try {
    const res = await triggerChannelSync(item.channel);
    notifySuccess(`同步任务已提交（任务 ID：${res.data?.task_id ?? "--"}）`);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "同步任务提交失败"));
  }
}

const testingChannel = ref<string | null>(null);

async function handleTestConnection(item: ChannelCard) {
  testingChannel.value = item.channel;
  try {
    const res = await testChannelConnection(item.channel);
    if (res.data?.ok) {
      notifySuccess(`「${item.name}」${res.data.message}`);
    } else {
      notifyError(new Error(res.data?.message ?? "连通失败"), `「${item.name}」连通失败`);
    }
  } catch (error) {
    notifyError(error, getErrorMessage(error, "连通测试请求失败"));
  } finally {
    testingChannel.value = null;
  }
}

/* ── 已发布职位侧滑 ── */

const postingsOpen = ref(false);
const postingsChannel = ref<ChannelCard | null>(null);
const postings = ref<RequisitionPosting[]>([]);
const postingsLoading = ref(false);

async function openPostings(item: ChannelCard) {
  postingsChannel.value = item;
  postingsOpen.value = true;
  postingsLoading.value = true;
  try {
    const res = await listChannelPostings(item.channel);
    postings.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "已发布职位加载失败"));
    postings.value = [];
  } finally {
    postingsLoading.value = false;
  }
}

const postingColumns = [
  { key: "requisition_id", title: "需求 ID", width: "220px" },
  { key: "status", title: "同步状态", width: "100px" },
  { key: "external_post_id", title: "外部职位 ID", width: "180px" },
  { key: "published_at", title: "发布时间", width: "150px" },
];

function openPlatformSettings() {
  void router.push("/iam/platform-settings");
}

onMounted(() => {
  void loadChannels();
});
</script>

<template>
  <AppPage title="渠道管理" description="招聘渠道接入状态与同步操作：凭证在 iam 平台设置维护，本页只读投影">
    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <div class="min-h-0 flex-1 overflow-auto p-5">
        <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="channel-grid">
          <div
            v-for="item in channels"
            :key="item.channel"
            class="flex flex-col gap-3 rounded-lg border p-4"
            data-testid="channel-card"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-medium">{{ item.name }}</span>
              <Badge :variant="accessStatusOf(item).variant" :data-testid="`channel-status-${item.channel}`">
                {{ accessStatusOf(item).label }}
              </Badge>
            </div>

            <div class="text-muted-foreground flex flex-col gap-1 text-xs">
              <span>
                凭证：{{ item.configured ? "已配置" : "未配置（在平台设置维护）" }}
              </span>
              <span>定时同步：{{ item.sync_enabled ? "已开启" : "未开启" }}</span>
              <span>
                最近同步：{{ item.last_sync_at?.slice(0, 19).replace("T", " ") ?? "--" }}
                · 累计归集：{{ item.collected_total }}
              </span>
            </div>

            <div class="mt-auto flex flex-wrap items-center gap-2 border-t pt-2">
              <Button
                v-if="canSync && item.configured && item.enabled"
                variant="outline"
                size="sm"
                :data-testid="`channel-sync-${item.channel}`"
                @click="handleSync(item)"
              >
                手动同步
              </Button>
              <Button
                v-if="canSync && item.configured && item.enabled"
                variant="outline"
                size="sm"
                :disabled="testingChannel === item.channel"
                :data-testid="`channel-test-${item.channel}`"
                @click="handleTestConnection(item)"
              >
                {{ testingChannel === item.channel ? "测试中…" : "连通测试" }}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                :data-testid="`channel-postings-${item.channel}`"
                @click="openPostings(item)"
              >
                已发布职位
              </Button>
              <Button variant="link" size="sm" class="text-muted-foreground h-auto p-0" @click="openPlatformSettings">
                配置凭证
              </Button>
            </div>
          </div>

          <div
            v-if="!channels.length && !loading"
            class="text-muted-foreground col-span-full py-10 text-center"
            data-testid="channel-empty"
          >
            暂无渠道接入
          </div>
        </div>
        <p class="text-muted-foreground mt-4 text-xs">
          内推（{{ CHANNEL_LABELS.internal }}）为内置免凭证渠道，站内投递直达；外部渠道凭证与同步频率在平台设置
          hr_channel_{code} 配置块维护。
        </p>
      </div>
    </div>

    <!-- 已发布职位侧滑 -->
    <Sheet :open="postingsOpen" @update:open="postingsOpen = $event">
      <SheetContent side="right" class="flex w-full flex-col gap-0 overflow-hidden sm:max-w-2xl" data-testid="channel-postings-sheet">
        <SheetHeader class="shrink-0 border-b px-5 py-4">
          <SheetTitle data-testid="channel-postings-title">{{ postingsChannel?.name ?? "--" }} · 已发布职位</SheetTitle>
          <SheetDescription>渠道职位同步状态（发布/下线操作在招聘需求详情完成）</SheetDescription>
        </SheetHeader>
        <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
          <Table
            :columns="postingColumns"
            :data="postings"
            :loading="postingsLoading"
            empty-text="该渠道暂无发布职位"
            data-testid="channel-postings-table"
          >
            <template #requisition_id="{ row }">
              {{ (row as RequisitionPosting).requisition_id }}
            </template>
            <template #status="{ row }">
              <Badge :variant="POSTING_STATUS_VARIANTS[(row as RequisitionPosting).status]">
                {{ POSTING_STATUS_LABELS[(row as RequisitionPosting).status] ?? (row as RequisitionPosting).status }}
              </Badge>
            </template>
            <template #external_post_id="{ row }">
              {{ (row as RequisitionPosting).external_post_id ?? "--" }}
            </template>
            <template #published_at="{ row }">
              {{ (row as RequisitionPosting).published_at?.slice(0, 19).replace("T", " ") ?? "--" }}
            </template>
          </Table>
        </div>
      </SheetContent>
    </Sheet>
  </AppPage>
</template>
