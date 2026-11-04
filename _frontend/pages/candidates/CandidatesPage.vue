<script setup lang="ts">
/**
 * 候选人管理页：全局漏斗统计卡（点击联动阶段筛选）+ 筛选栏（阶段/渠道/需求/关键词/黑名单）
 * + 投递卡片流（操作随阶段出项）+ 手工录入/安排面试/发起 Offer/详情侧滑/合并弹窗。
 * 卡片流为手动分页（Pagination），漏斗需 hr:requisition:read，无权限时降级隐藏。
 */
import { computed, onMounted, ref } from "vue";

import { Button, Checkbox, Input, Pagination, Select } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import {
  getGlobalFunnel,
  listRequisitions,
  updateApplicationStage,
} from "@/hr/api/recruiting";
import { listCandidateCards } from "@/hr/api/candidate";
import { acceptOffer, getApplicationOffer, rejectOffer } from "@/hr/api/offer";
import CandidateCard from "@/hr/components/candidate/CandidateCard.vue";
import CandidateDetailSheet from "@/hr/components/candidate/CandidateDetailSheet.vue";
import CandidateFormModal from "@/hr/components/candidate/CandidateFormModal.vue";
import InterviewScheduleModal from "@/hr/components/candidate/InterviewScheduleModal.vue";
import MergeCandidateModal from "@/hr/components/candidate/MergeCandidateModal.vue";
import OfferFormModal from "@/hr/components/candidate/OfferFormModal.vue";
import OfferOnboardModal from "@/hr/components/candidate/OfferOnboardModal.vue";
import FunnelBar from "@/hr/components/recruiting/FunnelBar.vue";
import {
  APPLICATION_STAGE_LABELS,
  CANDIDATE_CHANNEL_LABELS,
  type Application,
  type ApplicationStage,
  type Candidate,
  type FunnelStat,
  type Requisition,
} from "@/hr/types/recruiting";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:candidate:write"));
const canInterview = computed(() => userStore.hasPermission("hr:interview:write"));
const canOffer = computed(() => userStore.hasPermission("hr:offer:write"));
const canMerge = computed(() => userStore.hasPermission("hr:candidate:merge"));
const canReadFunnel = computed(() => userStore.hasPermission("hr:requisition:read"));

/* ── 全局漏斗（点击联动阶段筛选） ── */

const funnelStats = ref<FunnelStat[]>([]);

async function loadFunnel() {
  if (!canReadFunnel.value) {
    funnelStats.value = [];
    return;
  }
  try {
    const res = await getGlobalFunnel();
    funnelStats.value = res.data?.stats ?? [];
  } catch {
    // 漏斗仅统计辅助，失败降级为空不阻断卡片流
    funnelStats.value = [];
  }
}

/* ── 筛选 ── */

const stageFilter = ref<ApplicationStage | "">("");
const channelFilter = ref("all");
const requisitionFilter = ref("all");
const keyword = ref("");
const includeBlacklist = ref(false);

const stageOptions = [
  { value: "all", label: "全部阶段" },
  ...(Object.keys(APPLICATION_STAGE_LABELS) as ApplicationStage[]).map((value) => ({
    value,
    label: APPLICATION_STAGE_LABELS[value],
  })),
];

const channelOptions = [
  { value: "all", label: "全部渠道" },
  ...Object.entries(CANDIDATE_CHANNEL_LABELS).map(([value, label]) => ({ value, label })),
];

const requisitionOptions = ref<{ value: string; label: string }[]>([]);

/** Select 哨兵 "all" ↔ FunnelBar 选中态 "" 的双值映射 */
const stageFilterProxy = computed<string>({
  get: () => stageFilter.value || "all",
  set: (value) => {
    stageFilter.value = value === "all" ? "" : (value as ApplicationStage);
  },
});

async function loadRequisitionOptions() {
  try {
    const res = await listRequisitions({ page: 1, page_size: 100 });
    requisitionOptions.value = [
      { value: "all", label: "全部需求" },
      ...(res.data ?? []).map((item: Requisition) => ({ value: item.id, label: `${item.title}（${item.req_no}）` })),
    ];
  } catch {
    requisitionOptions.value = [{ value: "all", label: "全部需求" }];
  }
}

function handleFunnelStageSelect(stage: ApplicationStage | "") {
  stageFilter.value = stage;
  void loadCards();
}

function handleResetFilters() {
  stageFilter.value = "";
  channelFilter.value = "all";
  requisitionFilter.value = "all";
  keyword.value = "";
  includeBlacklist.value = false;
  page.value = 1;
  void loadCards();
}

/* ── 投递卡片流（手动分页） ── */

const rows = ref<Application[]>([]);
const loading = ref(false);
const page = ref(1);
const pageSize = ref(12);
const total = ref(0);

async function loadCards() {
  loading.value = true;
  try {
    const res = await listCandidateCards({
      page: page.value,
      page_size: pageSize.value,
      stage: stageFilter.value || undefined,
      channel: channelFilter.value === "all" ? undefined : channelFilter.value,
      requisition_id: requisitionFilter.value === "all" ? undefined : requisitionFilter.value,
      keyword: keyword.value || undefined,
      include_blacklist: includeBlacklist.value || undefined,
    });
    rows.value = res.data ?? [];
    total.value = res.total || 0;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "候选人卡片加载失败"));
    rows.value = [];
    total.value = 0;
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.value = 1;
  void loadCards();
}

function handlePageChange(value: number) {
  page.value = value;
  void loadCards();
}

function handlePageSizeChange(value: number) {
  pageSize.value = value;
  page.value = 1;
  void loadCards();
}

function refreshAll() {
  void loadCards();
  void loadFunnel();
}

/* ── 阶段流转 ── */

async function handleStageChange(application: Application, target: ApplicationStage) {
  const destructive = target === "rejected" || target === "withdrawn" || target === "onboard_abandoned";
  if (destructive && !(await confirmAction(`确定将「${application.candidate_name ?? "该候选人"}」流转至「${APPLICATION_STAGE_LABELS[target]}」？`))) {
    return;
  }
  try {
    await updateApplicationStage(application.id, target);
    notifySuccess(`已流转至「${APPLICATION_STAGE_LABELS[target]}」`);
    refreshAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "阶段流转失败"));
  }
}

/* ── 录入 / 面试 / Offer / 详情 / 合并 ── */

const formOpen = ref(false);

const interviewOpen = ref(false);
const interviewTarget = ref<Application | null>(null);

const offerOpen = ref(false);
const offerTarget = ref<Application | null>(null);

const onboardOpen = ref(false);
const onboardTarget = ref<Application | null>(null);

const detailOpen = ref(false);
const detailCandidateId = ref<string | null>(null);

const mergeOpen = ref(false);
const mergeSource = ref<{ id: string; name: string } | null>(null);

/** Offer 状态机操作：卡片出项按申请查 offer 再调 accept/reject（offer_id 前端不持有） */
async function applyOfferAction(
  application: Application,
  action: "accept" | "reject",
): Promise<void> {
  const label = action === "accept" ? "接受" : "拒绝";
  try {
    const offerRes = await getApplicationOffer(application.id);
    const offer = offerRes.data;
    if (!offer) {
      notifyError(new Error("未找到该投递的 Offer 单，请确认 Offer 已发送"));
      return;
    }
    await (action === "accept" ? acceptOffer(offer.id) : rejectOffer(offer.id));
    notifySuccess(`已${label} Offer，申请${action === "accept" ? "进入待入职" : "已淘汰"}`);
    refreshAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, `Offer ${label}失败`));
  }
}

function openInterview(application: Application) {
  interviewTarget.value = application;
  interviewOpen.value = true;
}

function openOffer(application: Application) {
  offerTarget.value = application;
  offerOpen.value = true;
}

function openOnboard(application: Application) {
  onboardTarget.value = application;
  onboardOpen.value = true;
}

function openDetail(application: Application) {
  detailCandidateId.value = application.candidate_id;
  detailOpen.value = true;
}

onMounted(() => {
  void loadFunnel();
  void loadRequisitionOptions();
  void loadCards();
});
</script>

<template>
  <AppPage title="候选人管理" description="候选人卡片流：漏斗跟踪、阶段流转、面试安排与 Offer 发放">
    <template #actions>
      <Button v-if="canWrite" data-testid="open-candidate-form" @click="formOpen = true">录入候选人</Button>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col gap-4 overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 全局漏斗统计卡 -->
      <div v-if="canReadFunnel && funnelStats.length" class="shrink-0 px-5 pt-4">
        <FunnelBar :stats="funnelStats" :selected="stageFilter" @stage-select="handleFunnelStageSelect" />
      </div>

      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 pb-3" :class="canReadFunnel && funnelStats.length ? '' : 'pt-4'">
        <Select v-model="stageFilterProxy" trigger-class="w-32" :options="stageOptions" data-testid="candidate-stage-filter" />
        <Select v-model="channelFilter" trigger-class="w-32" :options="channelOptions" data-testid="candidate-channel-filter" />
        <Select v-model="requisitionFilter" trigger-class="w-52" :options="requisitionOptions" data-testid="candidate-requisition-filter" />
        <Input
          v-model="keyword"
          class="w-44"
          placeholder="姓名/手机/邮箱"
          data-testid="candidate-keyword-input"
          @keyup.enter="handleSearch"
        />
        <label class="flex items-center gap-1.5 text-sm">
          <Checkbox
            :model-value="includeBlacklist"
            data-testid="candidate-include-blacklist"
            @update:model-value="includeBlacklist = $event === true; handleSearch()"
          />
          含黑名单
        </label>
        <Button variant="outline" size="sm" data-testid="candidate-search" @click="handleSearch">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="candidate-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 卡片流 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pb-4">
        <div
          v-if="rows.length"
          class="grid min-h-0 flex-1 auto-rows-min content-start gap-3 overflow-auto"
          data-testid="candidate-card-grid"
        >
          <CandidateCard
            v-for="application in rows"
            :key="application.id"
            :application="application"
            :can-write="canWrite"
            :can-interview="canInterview"
            :can-offer="canOffer"
            @stage="handleStageChange"
            @interview="openInterview"
            @offer="openOffer"
            @offer-accept="applyOfferAction($event, 'accept')"
            @offer-reject="applyOfferAction($event, 'reject')"
            @onboard="openOnboard"
            @detail="openDetail"
          />
        </div>
        <div
          v-else-if="!loading"
          class="text-muted-foreground flex flex-1 items-center justify-center"
          data-testid="candidate-empty"
        >
          暂无候选人投递
        </div>
        <div class="flex shrink-0 justify-end pt-3">
          <Pagination
            :total="total"
            :page="page"
            :page-size="pageSize"
            data-testid="candidate-pagination"
            @update:page="handlePageChange"
            @update:page-size="handlePageSizeChange"
          />
        </div>
      </div>
    </div>

    <!-- 手工录入弹窗 -->
    <CandidateFormModal v-model:open="formOpen" @saved="refreshAll" />

    <!-- 安排面试弹窗（建面试 + 流转面试中） -->
    <InterviewScheduleModal v-model:open="interviewOpen" :application="interviewTarget" @saved="refreshAll" />

    <!-- 发起 Offer 弹窗（创建 + 发送两连） -->
    <OfferFormModal v-model:open="offerOpen" :application="offerTarget" @saved="refreshAll" />
    <OfferOnboardModal v-model:open="onboardOpen" :application="onboardTarget" @saved="refreshAll" />

    <!-- 候选人详情侧滑 -->
    <CandidateDetailSheet
      v-model:open="detailOpen"
      :candidate-id="detailCandidateId"
      :can-write="canWrite"
      :can-merge="canMerge"
      @refresh="refreshAll"
      @merge="mergeSource = $event; mergeOpen = true"
    />

    <!-- 合并候选人弹窗 -->
    <MergeCandidateModal v-model:open="mergeOpen" :source="mergeSource" @merged="refreshAll" />
  </AppPage>
</template>
