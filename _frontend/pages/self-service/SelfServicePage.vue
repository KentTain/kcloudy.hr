<script setup lang="ts">
/**
 * 员工自助页（console）：我的档案 / 我的薪酬单 / 我的目标 / 我的绩效 / 团队成员（本人组织子树）。
 * 未关联员工档案时降级空态；团队成员经组织树映射部门名（懒加载，仅团队页签激活时请求）。
 * self_editable 属性变更走统一审批流（申请变更弹窗 + 我的申请列表弹窗）。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  DescriptionList,
  Dialog,
  DialogContent,
  Input,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useDataTable,
} from "@/components";
import { Progress } from "@/components/ui/progress";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { getOrgTree } from "@/hr/api/reference";
import {
  cancelChangeRequest,
  getMyGoals,
  getMyPaySlip,
  getMyProfile,
  getMyReviews,
  listMyChangeRequests,
  listMyPaySlips,
  listTeamEmployees,
  submitChangeRequest,
  updateMyGoalProgress,
} from "@/hr/api/selfService";
import {
  EMPLOYEE_STATUS_LABELS,
  EMPLOYEE_STATUS_VARIANTS,
  type AttributeValueItem,
  type OrgTreeNode,
} from "@/hr/types/employee";
import {
  PERF_CYCLE_STATUS_LABELS,
  PERF_CYCLE_STATUS_VARIANTS,
  PERF_GOAL_STATUS_LABELS,
  PERF_REVIEW_STATUS_LABELS,
  PERF_REVIEW_STATUS_VARIANTS,
  type PerfRating,
} from "@/hr/types/perf";
import type {
  ChangeRequestSummary,
  MyGoalGroup,
  MyProfileData,
  MyReviewItem,
  PaySlipDetail,
  PaySlipSummary,
  TeamEmployee,
} from "@/hr/types/selfService";

type TabKey = "profile" | "payslips" | "goals" | "reviews" | "team";

const activeTab = ref<TabKey>("profile");
const profileMissing = ref(false);
const loadingProfile = ref(false);

const profileData = ref<MyProfileData | null>(null);
const paySlips = ref<PaySlipSummary[]>([]);
const paySlipsLoaded = ref(false);
const paySlipDetail = ref<PaySlipDetail | null>(null);
const detailOpen = ref(false);
const orgTree = ref<OrgTreeNode[]>([]);

const profile = computed(() => profileData.value?.profile ?? null);
const attributes = computed<AttributeValueItem[]>(() => profileData.value?.attributes ?? []);

async function loadProfile() {
  loadingProfile.value = true;
  try {
    profileData.value = (await getMyProfile()).data ?? null;
    profileMissing.value = profileData.value === null;
  } catch (error) {
    profileMissing.value = true;
    notifyError(getErrorMessage(error, "档案加载失败"));
  } finally {
    loadingProfile.value = false;
  }
}

loadProfile();

/* ── 我的档案展示 ── */

const profileHeader = computed(() => {
  const p = profile.value;
  if (!p) return [];
  return [
    { label: "工号", value: p.employee_no },
    { label: "姓名", value: p.name },
    { label: "手机号", value: p.phone },
    { label: "工作邮箱", value: p.work_email },
  ];
});

const baseInfoItems = computed(() => {
  const p = profile.value;
  if (!p) return [];
  return [
    { label: "性别", value: p.gender },
    { label: "入职日期", value: p.hire_date },
    { label: "转正日期", value: p.regular_date },
    { label: "职级", value: p.job_level },
  ];
});

const attributeItems = computed(() =>
  attributes.value.map((item) => ({
    label: item.name,
    value: item.value === null || item.value === undefined || item.value === "" ? "--" : String(item.value),
  })),
);

/* ── 档案变更申请（self_editable 属性，走统一审批流） ── */

const changeOpen = ref(false);
const myRequestsOpen = ref(false);
const changeTitle = ref("");
const changeDraft = ref<Record<string, string>>({});
const changeSubmitting = ref(false);

const selfEditableAttributes = computed(() =>
  attributes.value.filter((item) => item.ext_data?.self_editable === true),
);

function openChangeModal() {
  const draft: Record<string, string> = {};
  selfEditableAttributes.value.forEach((item) => {
    draft[item.definition_id] = item.value === null || item.value === undefined ? "" : String(item.value);
  });
  changeDraft.value = draft;
  changeTitle.value = "";
  changeOpen.value = true;
}

async function handleSubmitChange() {
  const changes = selfEditableAttributes.value
    .filter((item) => {
      const original = item.value === null || item.value === undefined ? "" : String(item.value);
      return (changeDraft.value[item.definition_id] ?? "") !== original;
    })
    .map((item) => ({ definition_id: item.definition_id, new_value: changeDraft.value[item.definition_id] ?? null }));
  if (!changeTitle.value.trim()) {
    notifyError("请填写申请标题");
    return;
  }
  if (changes.length === 0) {
    notifyError("请至少修改一项属性值");
    return;
  }
  changeSubmitting.value = true;
  try {
    await submitChangeRequest({ title: changeTitle.value.trim(), changes });
    notifySuccess("变更申请已提交，等待审批");
    changeOpen.value = false;
  } catch (error) {
    notifyError(getErrorMessage(error, "变更申请提交失败"));
  } finally {
    changeSubmitting.value = false;
  }
}

const myRequests = ref<ChangeRequestSummary[]>([]);
const myRequestsLoading = ref(false);

const REQUEST_STATUS_LABELS: Record<ChangeRequestSummary["status"], string> = {
  pending: "待审批",
  approved: "已通过",
  rejected: "已驳回",
  cancelled: "已撤销",
};

const REQUEST_STATUS_VARIANTS: Record<ChangeRequestSummary["status"], "default" | "success" | "destructive" | "secondary"> = {
  pending: "default",
  approved: "success",
  rejected: "destructive",
  cancelled: "secondary",
};

async function openMyRequests() {
  myRequestsOpen.value = true;
  myRequestsLoading.value = true;
  try {
    myRequests.value = (await listMyChangeRequests({ page: 1, page_size: 50 })).data ?? [];
  } catch (error) {
    notifyError(getErrorMessage(error, "申请列表加载失败"));
  } finally {
    myRequestsLoading.value = false;
  }
}

async function handleCancelRequest(id: string) {
  try {
    await cancelChangeRequest(id);
    notifySuccess("申请已撤销");
    await openMyRequests();
  } catch (error) {
    notifyError(getErrorMessage(error, "撤销失败"));
  }
}

/* ── 我的薪酬单 ── */

async function loadPaySlips() {
  try {
    paySlips.value = (await listMyPaySlips()).data ?? [];
    paySlipsLoaded.value = true;
  } catch (error) {
    notifyError(getErrorMessage(error, "薪酬单加载失败"));
  }
}

async function openPaySlipDetail(period: string) {
  try {
    paySlipDetail.value = (await getMyPaySlip(period)).data ?? null;
    detailOpen.value = true;
  } catch (error) {
    notifyError(getErrorMessage(error, "薪酬明细加载失败"));
  }
}

function formatAmount(amount: number | null | undefined): string {
  return `¥${Number(amount ?? 0).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/* ── 我的目标（active 周期行内更新进度） ── */

const myGoals = ref<MyGoalGroup[]>([]);
const goalsLoaded = ref(false);
const goalsLoading = ref(false);
const goalEdits = ref<Record<string, { progress: string; actual_value: string }>>({});
const goalSaving = ref<Record<string, boolean>>({});

async function loadMyGoals() {
  goalsLoading.value = true;
  try {
    myGoals.value = (await getMyGoals()).data ?? [];
    goalsLoaded.value = true;
    const edits: Record<string, { progress: string; actual_value: string }> = {};
    myGoals.value
      .filter((group) => group.cycle_status === "active")
      .forEach((group) =>
        group.goals.forEach((goal) => {
          edits[goal.id] = { progress: String(goal.progress), actual_value: goal.actual_value ?? "" };
        }),
      );
    goalEdits.value = edits;
  } catch (error) {
    notifyError(getErrorMessage(error, "目标加载失败"));
  } finally {
    goalsLoading.value = false;
  }
}

async function saveGoalProgress(goalId: string) {
  const edit = goalEdits.value[goalId];
  if (!edit) return;
  goalSaving.value = { ...goalSaving.value, [goalId]: true };
  try {
    await updateMyGoalProgress(goalId, {
      progress: Number(edit.progress),
      actual_value: edit.actual_value || null,
    });
    notifySuccess("进度已更新");
    await loadMyGoals();
  } catch (error) {
    notifyError(getErrorMessage(error, "进度更新失败"));
  } finally {
    goalSaving.value = { ...goalSaving.value, [goalId]: false };
  }
}

/* ── 我的绩效 ── */

const myReviews = ref<MyReviewItem[]>([]);
const reviewsLoaded = ref(false);

async function loadMyReviews() {
  try {
    myReviews.value = (await getMyReviews()).data ?? [];
    reviewsLoaded.value = true;
  } catch (error) {
    notifyError(getErrorMessage(error, "绩效加载失败"));
  }
}

function formatRating(rating: PerfRating | null): string {
  return rating ?? "--";
}

/* ── 团队成员（懒加载 + 部门名映射） ── */

function orgNameOf(orgId: string | null): string {
  if (!orgId) return "--";
  const found = new Map<string, string>();
  const walk = (nodes: OrgTreeNode[]) => {
    nodes.forEach((node) => {
      found.set(node.id, node.name);
      if (node.children?.length) walk(node.children);
    });
  };
  walk(orgTree.value);
  return found.get(orgId) ?? orgId;
}

const teamColumns: ColumnDef<TeamEmployee>[] = [
  { accessorKey: "employee_no", header: "工号" },
  { accessorKey: "name", header: "姓名" },
  {
    id: "org",
    header: "部门",
    cell: ({ row }) => orgNameOf(row.original.org_id),
  },
  { accessorKey: "job_level", header: "职级", cell: ({ getValue }) => (getValue() as string | null) ?? "--" },
  {
    accessorKey: "status",
    header: "状态",
    cell: ({ row }) =>
      h(Badge, { variant: EMPLOYEE_STATUS_VARIANTS[row.original.status] }, () => EMPLOYEE_STATUS_LABELS[row.original.status]),
  },
  { accessorKey: "hire_date", header: "入职日期" },
];

async function ensureTeamDeps() {
  if (orgTree.value.length > 0) return;
  try {
    orgTree.value = (await getOrgTree()).data ?? [];
  } catch {
    orgTree.value = [];
  }
}

const teamDataTable = useDataTable<TeamEmployee>({
  columns: teamColumns,
  remoteFetchFn: async ({ page, page_size }) => {
    await ensureTeamDeps();
    const res = await listTeamEmployees({ page, page_size });
    return {
      code: res.code,
      data: res.data ?? [],
      msg: res.msg,
      page: res.page,
      page_size: res.page_size,
      total: res.total,
    };
  },
  enabled: () => activeTab.value === "team",
});

function switchTab(value: string | number) {
  activeTab.value = value as TabKey;
  if (activeTab.value === "payslips" && !paySlipsLoaded.value) void loadPaySlips();
  if (activeTab.value === "goals" && !goalsLoaded.value) void loadMyGoals();
  if (activeTab.value === "reviews" && !reviewsLoaded.value) void loadMyReviews();
}
</script>

<template>
  <AppPage title="员工自助" description="我的档案、薪酬单、目标、绩效与团队成员信息">
    <div
      v-if="profileMissing"
      class="bg-card ring-foreground/10 flex h-full min-h-0 items-center justify-center rounded-xl text-sm ring-1 shadow-sm"
      data-testid="self-profile-missing"
    >
      <div class="flex flex-col items-center gap-2 py-16 text-muted-foreground">
        <p class="text-base">尚未关联员工档案</p>
        <p class="text-xs">请联系 HR 在员工管理中关联本人档案后使用自助功能</p>
      </div>
    </div>

    <div v-else class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <Tabs :model-value="activeTab" class="flex min-h-0 flex-1 flex-col" @update:model-value="switchTab">
        <div class="shrink-0 border-b px-5 py-3">
          <TabsList>
            <TabsTrigger value="profile" :data-testid="'self-tab-profile'">我的档案</TabsTrigger>
            <TabsTrigger value="payslips" :data-testid="'self-tab-payslips'">我的薪酬单</TabsTrigger>
            <TabsTrigger value="goals" :data-testid="'self-tab-goals'">我的目标</TabsTrigger>
            <TabsTrigger value="reviews" :data-testid="'self-tab-reviews'">我的绩效</TabsTrigger>
            <TabsTrigger value="team" :data-testid="'self-tab-team'">团队成员</TabsTrigger>
          </TabsList>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-5" data-testid="self-body">
        <!-- 我的档案 -->
        <TabsContent v-if="activeTab === 'profile'" value="profile" class="flex flex-col gap-4" data-testid="self-profile">
          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm">
            <div class="flex items-center gap-3">
              <span class="text-lg font-semibold" data-testid="self-profile-name">{{ profile?.name ?? "--" }}</span>
              <Badge v-if="profile" :variant="EMPLOYEE_STATUS_VARIANTS[profile.status]">
                {{ EMPLOYEE_STATUS_LABELS[profile.status] }}
              </Badge>
            </div>
            <DescriptionList class="mt-3" :items="profileHeader" :columns="4" />
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="self-base-info">
            <p class="mb-3 font-medium">基础信息</p>
            <DescriptionList :items="baseInfoItems" :columns="4" />
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="self-attributes">
            <div class="mb-3 flex items-center justify-between">
              <p class="font-medium">扩展属性</p>
              <div class="flex gap-2">
                <Button
                  v-if="selfEditableAttributes.length > 0"
                  variant="outline"
                  size="sm"
                  data-testid="self-change-request-open"
                  @click="openChangeModal"
                >
                  申请变更
                </Button>
                <Button variant="outline" size="sm" data-testid="self-my-requests-open" @click="openMyRequests">
                  我的申请
                </Button>
              </div>
            </div>
            <DescriptionList :items="attributeItems" :columns="3" />
            <p v-if="attributeItems.length === 0" class="py-4 text-center text-muted-foreground">暂无扩展属性</p>
          </div>
        </TabsContent>

        <!-- 我的薪酬单 -->
        <TabsContent v-else-if="activeTab === 'payslips'" value="payslips" class="flex flex-col gap-3" data-testid="self-payslips">
          <div class="ring-foreground/10 bg-card overflow-hidden rounded-xl ring-1 shadow-sm">
            <table class="w-full text-sm" data-testid="self-payslip-table">
              <thead>
                <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
                  <th class="px-4 py-2 font-medium">薪资期间</th>
                  <th class="px-4 py-2 font-medium">发薪日</th>
                  <th class="px-4 py-2 font-medium">项目数</th>
                  <th class="px-4 py-2 font-medium">应发合计</th>
                  <th class="px-4 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="slip in paySlips" :key="slip.period" class="border-t" :data-testid="`self-payslip-${slip.period}`">
                  <td class="px-4 py-2">{{ slip.period }}</td>
                  <td class="px-4 py-2">{{ slip.pay_date }}</td>
                  <td class="px-4 py-2">{{ slip.item_count }}</td>
                  <td class="px-4 py-2 tabular-nums">{{ formatAmount(slip.total_amount) }}</td>
                  <td class="px-4 py-2">
                    <Button variant="outline" size="sm" :data-testid="`self-payslip-detail-${slip.period}`" @click="openPaySlipDetail(slip.period)">
                      查看明细
                    </Button>
                  </td>
                </tr>
                <tr v-if="paySlips.length === 0">
                  <td colspan="5" class="text-muted-foreground px-4 py-8 text-center">暂无已发放薪酬单</td>
                </tr>
              </tbody>
            </table>
          </div>
        </TabsContent>

        <!-- 我的目标 -->
        <TabsContent v-else-if="activeTab === 'goals'" value="goals" class="flex flex-col gap-4" data-testid="self-goals">
          <div
            v-for="group in myGoals"
            :key="group.cycle_id"
            class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm"
            :data-testid="`self-goal-cycle-${group.cycle_id}`"
          >
            <div class="mb-3 flex items-center gap-2">
              <span class="font-medium">{{ group.cycle_name }}</span>
              <Badge :variant="PERF_CYCLE_STATUS_VARIANTS[group.cycle_status]">
                {{ PERF_CYCLE_STATUS_LABELS[group.cycle_status] }}
              </Badge>
              <span class="text-muted-foreground text-xs">{{ group.start_date }} ~ {{ group.end_date }}</span>
            </div>
            <div class="flex flex-col gap-3">
              <div
                v-for="goal in group.goals"
                :key="goal.id"
                class="border-foreground/10 rounded-lg border p-3"
                :data-testid="`self-goal-${goal.id}`"
              >
                <div class="flex items-center gap-2">
                  <span class="font-medium">{{ goal.name }}</span>
                  <Badge variant="outline">权重 {{ goal.weight }}%</Badge>
                  <Badge variant="secondary">{{ PERF_GOAL_STATUS_LABELS[goal.status] }}</Badge>
                  <span v-if="goal.target_value" class="text-muted-foreground text-xs">目标：{{ goal.target_value }}</span>
                </div>
                <div class="mt-2 flex items-center gap-3">
                  <Progress class="h-2 flex-1" :model-value="goal.progress" />
                  <span class="w-10 text-right text-xs tabular-nums">{{ goal.progress }}%</span>
                  <span v-if="goal.actual_value" class="text-muted-foreground text-xs">实际：{{ goal.actual_value }}</span>
                </div>
                <div v-if="group.cycle_status === 'active'" class="mt-2 flex items-center gap-2">
                  <Input
                    v-model="goalEdits[goal.id].progress"
                    type="number"
                    class="w-24"
                    placeholder="进度"
                    :data-testid="`self-goal-progress-${goal.id}`"
                  />
                  <Input
                    v-model="goalEdits[goal.id].actual_value"
                    class="w-48"
                    placeholder="实际值"
                    :data-testid="`self-goal-actual-${goal.id}`"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    :disabled="goalSaving[goal.id]"
                    :data-testid="`self-goal-save-${goal.id}`"
                    @click="saveGoalProgress(goal.id)"
                  >
                    保存
                  </Button>
                </div>
              </div>
            </div>
          </div>
          <div
            v-if="goalsLoaded && myGoals.length === 0"
            class="ring-foreground/10 bg-card rounded-xl py-12 text-center text-muted-foreground ring-1 shadow-sm"
          >
            暂无考核目标
          </div>
        </TabsContent>

        <!-- 我的绩效 -->
        <TabsContent v-else-if="activeTab === 'reviews'" value="reviews" class="flex flex-col gap-3" data-testid="self-reviews">
          <div class="ring-foreground/10 bg-card overflow-hidden rounded-xl ring-1 shadow-sm">
            <table class="w-full text-sm" data-testid="self-review-table">
              <thead>
                <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
                  <th class="px-4 py-2 font-medium">考核周期</th>
                  <th class="px-4 py-2 font-medium">状态</th>
                  <th class="px-4 py-2 font-medium">自评</th>
                  <th class="px-4 py-2 font-medium">评分</th>
                  <th class="px-4 py-2 font-medium">最终评级</th>
                  <th class="px-4 py-2 font-medium">绩效系数</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="review in myReviews" :key="review.id" class="border-t" :data-testid="`self-review-${review.id}`">
                  <td class="px-4 py-2">
                    {{ review.cycle_name }}
                    <Badge class="ml-1" :variant="PERF_CYCLE_STATUS_VARIANTS[review.cycle_status]">
                      {{ PERF_CYCLE_STATUS_LABELS[review.cycle_status] }}
                    </Badge>
                  </td>
                  <td class="px-4 py-2">
                    <Badge :variant="PERF_REVIEW_STATUS_VARIANTS[review.status]">
                      {{ PERF_REVIEW_STATUS_LABELS[review.status] }}
                    </Badge>
                  </td>
                  <td class="px-4 py-2 tabular-nums">{{ review.self_score ?? "--" }}</td>
                  <td class="px-4 py-2 tabular-nums">{{ review.score ?? "--" }}</td>
                  <td class="px-4 py-2 font-medium">{{ formatRating(review.final_rating) }}</td>
                  <td class="px-4 py-2 tabular-nums">{{ review.coefficient ?? "--" }}</td>
                </tr>
                <tr v-if="myReviews.length === 0">
                  <td colspan="6" class="text-muted-foreground px-4 py-8 text-center">暂无评估记录</td>
                </tr>
              </tbody>
            </table>
          </div>
        </TabsContent>

        <!-- 团队成员 -->
        <TabsContent v-else value="team" class="flex min-h-0 flex-1 flex-col" data-testid="self-team">
          <div class="ring-foreground/10 bg-card flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl ring-1 shadow-sm">
            <DataTable :data-table="teamDataTable" :fixed-layout="true" data-testid="self-team-table" />
          </div>
        </TabsContent>
        </div>
      </Tabs>
    </div>

    <!-- 薪酬明细弹窗 -->
    <Dialog v-model:open="detailOpen">
      <DialogContent class="sm:max-w-lg" data-testid="self-payslip-detail-modal">
        <div v-if="paySlipDetail">
          <p class="text-muted-foreground text-xs">
            {{ paySlipDetail.period }} · 发薪日 {{ paySlipDetail.pay_date }}
          </p>
          <table class="mt-3 w-full text-sm" data-testid="self-payslip-items">
            <thead>
              <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
                <th class="px-3 py-2 font-medium">薪酬项</th>
                <th class="px-3 py-2 font-medium">金额</th>
                <th class="px-3 py-2 font-medium">备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in paySlipDetail.items" :key="item.item_code" class="border-t" :data-testid="`self-payslip-item-${item.item_code}`">
                <td class="px-3 py-2">{{ item.item_code }}</td>
                <td class="px-3 py-2 tabular-nums">{{ formatAmount(item.amount) }}</td>
                <td class="text-muted-foreground px-3 py-2">{{ item.note ?? "--" }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t font-medium">
                <td class="px-3 py-2">合计</td>
                <td class="px-3 py-2 tabular-nums">{{ formatAmount(paySlipDetail.total_amount) }}</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      </DialogContent>
    </Dialog>

    <!-- 申请变更弹窗（self_editable 属性） -->
    <Dialog v-model:open="changeOpen">
      <DialogContent class="sm:max-w-lg" data-testid="self-change-request-modal">
        <div class="flex flex-col gap-3">
          <div>
            <p class="font-medium">申请档案变更</p>
            <p class="text-muted-foreground mt-1 text-xs">仅支持自助可改属性；提交后走统一审批流，审批通过前原值不变</p>
          </div>
          <Input v-model="changeTitle" placeholder="申请标题（如：更新联系方式）" data-testid="self-change-title" />
          <div class="flex flex-col gap-3">
            <div v-for="item in selfEditableAttributes" :key="item.definition_id" class="flex items-center gap-2">
              <span class="w-28 shrink-0 text-sm">{{ item.name }}</span>
              <Input
                v-model="changeDraft[item.definition_id]"
                :placeholder="`原值：${item.value ?? '--'}`"
                :data-testid="`self-change-input-${item.definition_id}`"
              />
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <Button variant="outline" size="sm" @click="changeOpen = false">取消</Button>
            <Button size="sm" :disabled="changeSubmitting" data-testid="self-change-submit" @click="handleSubmitChange">
              提交申请
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <!-- 我的申请列表弹窗 -->
    <Dialog v-model:open="myRequestsOpen">
      <DialogContent class="sm:max-w-2xl" data-testid="self-my-requests-modal">
        <p class="font-medium">我的变更申请</p>
        <table class="w-full text-sm" data-testid="self-my-requests-table">
          <thead>
            <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
              <th class="px-3 py-2 font-medium">标题</th>
              <th class="px-3 py-2 font-medium">状态</th>
              <th class="px-3 py-2 font-medium">提交时间</th>
              <th class="px-3 py-2 font-medium">审批意见</th>
              <th class="px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="request in myRequests" :key="request.id" class="border-t" :data-testid="`self-request-${request.id}`">
              <td class="px-3 py-2">{{ request.title }}</td>
              <td class="px-3 py-2">
                <Badge :variant="REQUEST_STATUS_VARIANTS[request.status]">
                  {{ REQUEST_STATUS_LABELS[request.status] }}
                </Badge>
              </td>
              <td class="text-muted-foreground px-3 py-2 text-xs">{{ request.created_at ?? "--" }}</td>
              <td class="text-muted-foreground px-3 py-2 text-xs">{{ request.approve_comment ?? "--" }}</td>
              <td class="px-3 py-2">
                <Button
                  v-if="request.status === 'pending'"
                  variant="outline"
                  size="sm"
                  :data-testid="`self-request-cancel-${request.id}`"
                  @click="handleCancelRequest(request.id)"
                >
                  撤销
                </Button>
                <span v-else class="text-muted-foreground text-xs">--</span>
              </td>
            </tr>
            <tr v-if="myRequests.length === 0 && !myRequestsLoading">
              <td colspan="5" class="text-muted-foreground px-3 py-8 text-center">暂无申请记录</td>
            </tr>
          </tbody>
        </table>
      </DialogContent>
    </Dialog>
  </AppPage>
</template>
