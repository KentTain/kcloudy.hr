<script setup lang="ts">
/**
 * 需求详情侧滑：需求信息卡 + 渠道发布状态 + 三段漏斗 FunnelBar + 候选人表格（阶段流转）。
 * 漏斗点击阶段联动过滤候选人表格；流转后漏斗计数与表格同步刷新。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, DescriptionList, Table } from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import {
  closeRequisition,
  generateJdDraft,
  getRequisition,
  getRequisitionFunnel,
  listRequisitionApplications,
  offlinePosting,
  updateApplicationStage,
} from "@/hr/api/recruiting";
import FunnelBar from "@/hr/components/recruiting/FunnelBar.vue";
import {
  APPLICATION_STAGE_LABELS,
  APPLICATION_STAGE_VARIANTS,
  CHANNEL_LABELS,
  POSTING_STATUS_LABELS,
  POSTING_STATUS_VARIANTS,
  REQUISITION_PRIORITY_LABELS,
  REQUISITION_PRIORITY_VARIANTS,
  REQUISITION_STATUS_LABELS,
  REQUISITION_STATUS_VARIANTS,
  STAGE_TRANSITIONS,
  type Application,
  type ApplicationStage,
  type FunnelStat,
  type Requisition,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  requisitionId: string | null;
  canWrite: boolean;
  canReadCandidates: boolean;
  /** 组织/岗位 ID → 名称解析（列表页同源映射） */
  orgNameOf: (orgId: string | null) => string;
  positionNameOf: (positionId: string | null) => string;
}>();

const emit = defineEmits<{
  refresh: [];
  publish: [requisition: Requisition];
}>();

const requisition = ref<Requisition | null>(null);
const funnelStats = ref<FunnelStat[]>([]);
const applications = ref<Application[]>([]);
const loading = ref(false);
const stageFilter = ref<ApplicationStage | "">("");
const jdDraft = ref("");
const jdGenerating = ref(false);

const salaryRange = computed(() => {
  const item = requisition.value;
  if (!item) return "--";
  if (item.salary_min === null && item.salary_max === null) return "--";
  const min = item.salary_min ?? "";
  const max = item.salary_max ?? "";
  return `${min} ~ ${max} 元/月`;
});

const infoItems = computed(() => {
  const item = requisition.value;
  if (!item) return [];
  return [
    { label: "招聘部门", value: props.orgNameOf(item.org_id) },
    { label: "岗位", value: props.positionNameOf(item.position_id) },
    { label: "要求职级", value: item.job_level ?? "--" },
    { label: "人数（已入职/招聘）", value: `${item.filled_count} / ${item.headcount}` },
    { label: "薪酬区间", value: salaryRange.value },
    { label: "优先级", value: REQUISITION_PRIORITY_LABELS[item.priority] ?? item.priority },
  ];
});

async function loadAll() {
  if (!props.requisitionId) return;
  loading.value = true;
  try {
    const [reqRes, funnelRes] = await Promise.allSettled([
      getRequisition(props.requisitionId),
      getRequisitionFunnel(props.requisitionId),
    ]);
    requisition.value = reqRes.value?.data ?? null;
    funnelStats.value = funnelRes.value?.data?.stats ?? [];
    if (props.canReadCandidates) {
      await loadApplications();
    }
  } finally {
    loading.value = false;
  }
}

async function loadApplications() {
  if (!props.requisitionId) return;
  try {
    const res = await listRequisitionApplications(props.requisitionId, {
      page: 1,
      page_size: 50,
      stage: stageFilter.value || undefined,
    });
    applications.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "投递列表加载失败"));
    applications.value = [];
  }
}

watch(open, (value) => {
  if (!value) return;
  requisition.value = null;
  funnelStats.value = [];
  applications.value = [];
  stageFilter.value = "";
  jdDraft.value = "";
  void loadAll();
});

/** JD 智能草稿（即时生成不落库；失败提示走手动编辑兜底） */
async function handleGenerateJd() {
  if (!props.requisitionId || jdGenerating.value) return;
  jdGenerating.value = true;
  try {
    const res = await generateJdDraft(props.requisitionId);
    jdDraft.value = res.data?.jd_draft ?? "";
    if (jdDraft.value) notifySuccess("JD 草稿已生成，可复制后手动编辑保存");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "JD 草稿生成失败，请手动编辑"));
  } finally {
    jdGenerating.value = false;
  }
}

function handleStageSelect(stage: ApplicationStage | "") {
  stageFilter.value = stage;
  if (props.canReadCandidates) void loadApplications();
}

const applicationColumns = [
  { key: "candidate", title: "候选人", width: "130px" },
  { key: "match_score", title: "匹配分", width: "80px" },
  { key: "stage", title: "当前阶段", width: "100px" },
  { key: "apply_time", title: "投递时间", width: "150px" },
  { key: "actions", title: "流转", width: "220px", align: "right" as const },
];

async function handleStageChange(application: Application, target: ApplicationStage) {
  try {
    await updateApplicationStage(application.id, target);
    notifySuccess(`已流转至「${APPLICATION_STAGE_LABELS[target]}」`);
    await loadAll();
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "阶段流转失败"));
  }
}

async function handleOfflinePosting(postingId: string) {
  if (!(await confirmAction("确定下线该渠道职位？"))) return;
  try {
    await offlinePosting(postingId);
    notifySuccess("渠道职位已下线");
    await loadAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "下线失败"));
  }
}

async function handleClose() {
  const item = requisition.value;
  if (!item) return;
  if (!(await confirmAction(`确定关闭需求「${item.title}」？关闭后不可再接受投递与流转。`))) return;
  try {
    await closeRequisition(item.id);
    notifySuccess("需求已关闭");
    await loadAll();
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "关闭需求失败"));
  }
}

function postingStatusLabel(status: string): string {
  return POSTING_STATUS_LABELS[status] ?? status;
}

function postingStatusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  return POSTING_STATUS_VARIANTS[status] ?? "outline";
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent side="right" class="flex w-full flex-col gap-0 overflow-hidden sm:max-w-4xl" data-testid="requisition-detail-sheet">
      <SheetHeader class="shrink-0 border-b px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <SheetTitle class="flex items-center gap-2" data-testid="requisition-detail-title">
              {{ requisition?.title ?? "需求详情" }}
              <Badge v-if="requisition" :variant="REQUISITION_STATUS_VARIANTS[requisition.status]">
                {{ REQUISITION_STATUS_LABELS[requisition.status] ?? requisition.status }}
              </Badge>
            </SheetTitle>
            <SheetDescription class="mt-1">
              {{ requisition?.req_no ?? "--" }}
              <Badge v-if="requisition" variant="outline" class="ml-2">
                {{ REQUISITION_PRIORITY_LABELS[requisition.priority] ?? requisition.priority }}优先
              </Badge>
            </SheetDescription>
          </div>
          <div v-if="canWrite && requisition && requisition.status !== 'closed'" class="flex shrink-0 gap-2">
            <Button
              variant="outline"
              size="sm"
              data-testid="detail-publish"
              @click="emit('publish', requisition)"
            >
              发布到渠道
            </Button>
            <Button variant="outline" size="sm" data-testid="detail-close" @click="handleClose">关闭需求</Button>
          </div>
        </div>
      </SheetHeader>

      <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-5 py-4">
        <!-- 需求信息卡 -->
        <DescriptionList :items="infoItems" :columns="3" data-testid="requisition-detail-info" />
        <div v-if="requisition?.jd || canWrite" class="flex flex-col gap-1.5">
          <div class="flex items-center justify-between">
            <p class="text-muted-foreground text-xs font-medium">职位描述（JD）</p>
            <Button
              v-if="canWrite"
              variant="link"
              size="sm"
              class="h-auto p-0"
              :disabled="jdGenerating"
              data-testid="detail-jd-generate"
              @click="handleGenerateJd"
            >
              {{ jdGenerating ? "生成中…" : "生成 AI 草稿" }}
            </Button>
          </div>
          <p v-if="requisition?.jd" class="text-sm whitespace-pre-wrap">{{ requisition.jd }}</p>
          <div
            v-if="jdDraft"
            class="rounded-md border px-3 py-2"
            data-testid="detail-jd-draft"
          >
            <p class="text-muted-foreground mb-1 text-xs">AI 草稿（未保存，可复制到编辑弹窗）</p>
            <p class="text-sm whitespace-pre-wrap">{{ jdDraft }}</p>
          </div>
        </div>

        <!-- 渠道发布状态 -->
        <div v-if="requisition?.postings?.length" class="flex flex-col gap-2" data-testid="requisition-postings">
          <p class="text-muted-foreground text-xs font-medium">渠道发布状态</p>
          <div
            v-for="posting in requisition.postings"
            :key="posting.id"
            class="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm"
            :data-testid="`posting-row-${posting.channel}`"
          >
            <span class="font-medium">{{ CHANNEL_LABELS[posting.channel as keyof typeof CHANNEL_LABELS] ?? posting.channel }}</span>
            <Badge :variant="postingStatusVariant(posting.status)">
              {{ postingStatusLabel(posting.status) }}
            </Badge>
            <span v-if="posting.external_post_id" class="text-muted-foreground text-xs">
              外部职位：{{ posting.external_post_id }}
            </span>
            <span v-if="posting.published_at" class="text-muted-foreground text-xs">
              {{ posting.published_at.slice(0, 19).replace("T", " ") }}
            </span>
            <Button
              v-if="canWrite && posting.status === 'published'"
              variant="link"
              size="sm"
              class="ml-auto h-auto p-0"
              @click="handleOfflinePosting(posting.id)"
            >
              下线
            </Button>
          </div>
        </div>

        <!-- 三段漏斗 -->
        <FunnelBar :stats="funnelStats" :selected="stageFilter" @stage-select="handleStageSelect" />

        <!-- 候选人表格 -->
        <div v-if="canReadCandidates" class="flex flex-col gap-2">
          <p class="text-muted-foreground text-xs font-medium">
            投递候选人{{ stageFilter ? `（${APPLICATION_STAGE_LABELS[stageFilter]}）` : "" }}
          </p>
          <Table
            :columns="applicationColumns"
            :data="applications"
            :loading="loading"
            empty-text="该需求暂无投递"
            data-testid="requisition-applications-table"
          >
            <template #candidate="{ row }">
              {{ (row as Application).candidate_name ?? "--" }}
            </template>
            <template #match_score="{ row }">
              {{ (row as Application).match_score === null ? "--" : (row as Application).match_score }}
            </template>
            <template #stage="{ row }">
              <Badge :variant="APPLICATION_STAGE_VARIANTS[(row as Application).stage]">
                {{ APPLICATION_STAGE_LABELS[(row as Application).stage] ?? (row as Application).stage }}
              </Badge>
            </template>
            <template #apply_time="{ row }">
              {{ (row as Application).apply_time?.slice(0, 10) ?? "--" }}
            </template>
            <template #actions="{ row }">
              <div class="flex flex-wrap justify-end gap-1">
                <Button
                  v-for="target in STAGE_TRANSITIONS[(row as Application).stage]"
                  :key="target"
                  variant="link"
                  size="sm"
                  class="h-auto p-0"
                  :class="target === 'rejected' || target === 'withdrawn' ? 'text-destructive' : ''"
                  :data-testid="`stage-move-${(row as Application).id}-${target}`"
                  @click="handleStageChange(row as Application, target)"
                >
                  {{ APPLICATION_STAGE_LABELS[target] }}
                </Button>
                <span v-if="!STAGE_TRANSITIONS[(row as Application).stage].length" class="text-muted-foreground text-xs">
                  --
                </span>
              </div>
            </template>
          </Table>
        </div>
      </div>
    </SheetContent>
  </Sheet>
</template>
