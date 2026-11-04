<script setup lang="ts">
/**
 * 团队工作台（console）：团队招聘（本人组织子树）/ 我的面试（面试官归属）/
 * 待我评分（评估人归属 + scoring 态周期 + 未评分）。数据按归属裁剪，越权后端 403。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Dialog,
  DialogContent,
  Input,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";
import { useUserStore } from "@/framework/stores";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { getOrgTree } from "@/hr/api/reference";
import {
  listTeamInterviews,
  listTeamRequisitions,
  listTeamReviews,
  submitTeamReviewScore,
} from "@/hr/api/team";
import type { OrgTreeNode } from "@/hr/types/employee";
import { PERF_RATINGS } from "@/hr/types/perf";
import {
  INTERVIEW_FORM_LABELS,
  INTERVIEW_RESULT_LABELS,
  INTERVIEW_RESULT_VARIANTS,
  REQUISITION_PRIORITY_LABELS,
  REQUISITION_PRIORITY_VARIANTS,
  REQUISITION_STATUS_LABELS,
  REQUISITION_STATUS_VARIANTS,
  type Requisition,
} from "@/hr/types/recruiting";
import type { TeamInterviewItem, TeamReviewItem } from "@/hr/types/selfService";

type TabKey = "requisitions" | "interviews" | "reviews";

const userStore = useUserStore();
// 团队工作台仅组织负责人可用（/users/me organizations.is_leader）
const isLeader = computed(() =>
  (userStore.userInfo?.organizations ?? []).some((org) => org.is_leader)
);

const activeTab = ref<TabKey>("requisitions");
const orgTree = ref<OrgTreeNode[]>([]);

function orgNameOf(orgId: string | null): string {
  if (!orgId) return "--";
  const names = new Map<string, string>();
  const walk = (nodes: OrgTreeNode[]) => {
    nodes.forEach((node) => {
      names.set(node.id, node.name);
      if (node.children?.length) walk(node.children);
    });
  };
  walk(orgTree.value);
  return names.get(orgId) ?? orgId;
}

async function ensureOrgTree() {
  if (orgTree.value.length > 0) return;
  try {
    orgTree.value = (await getOrgTree()).data ?? [];
  } catch {
    orgTree.value = [];
  }
}

/* ── 团队招聘 ── */

function salaryRangeOf(item: Requisition): string {
  if (item.salary_min === null && item.salary_max === null) return "--";
  return `${item.salary_min ?? ""} ~ ${item.salary_max ?? ""}`;
}

const requisitionColumns: ColumnDef<Requisition>[] = [
  { accessorKey: "req_no", header: "需求编号", size: 140 },
  { accessorKey: "title", header: "职位名称", size: 180 },
  {
    accessorKey: "org_id",
    header: "部门",
    size: 120,
    cell: ({ row }) => orgNameOf(row.original.org_id),
  },
  {
    id: "headcount",
    header: "入职/招聘",
    size: 90,
    cell: ({ row }) => `${row.original.filled_count} / ${row.original.headcount}`,
  },
  {
    id: "salary",
    header: "薪酬区间",
    size: 130,
    cell: ({ row }) => h("span", { class: "text-muted-foreground" }, salaryRangeOf(row.original)),
  },
  {
    accessorKey: "priority",
    header: "优先级",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: REQUISITION_PRIORITY_VARIANTS[row.original.priority] },
        () => REQUISITION_PRIORITY_LABELS[row.original.priority]
      ),
  },
  {
    accessorKey: "status",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: REQUISITION_STATUS_VARIANTS[row.original.status] },
        () => REQUISITION_STATUS_LABELS[row.original.status]
      ),
  },
];

const requisitionTable = useDataTable<Requisition>({
  columns: requisitionColumns,
  remoteFetchFn: async ({ page, page_size }) => {
    await ensureOrgTree();
    return listTeamRequisitions({ page, page_size });
  },
  enabled: () => isLeader.value && activeTab.value === "requisitions",
});

/* ── 我的面试 ── */

const interviews = ref<TeamInterviewItem[]>([]);
const interviewsLoaded = ref(false);
const interviewsLoading = ref(false);

async function loadInterviews() {
  interviewsLoading.value = true;
  try {
    interviews.value = (await listTeamInterviews()).data ?? [];
    interviewsLoaded.value = true;
  } catch (error) {
    notifyError(getErrorMessage(error, "面试列表加载失败"));
  } finally {
    interviewsLoading.value = false;
  }
}

/* ── 待我评分 ── */

const reviews = ref<TeamReviewItem[]>([]);
const reviewsLoaded = ref(false);
const scoreOpen = ref(false);
const scoreSubmitting = ref(false);
const scoringReview = ref<TeamReviewItem | null>(null);
const scoreForm = ref({ score: "", rating: "", self_score: "" });

const ratingOptions = PERF_RATINGS.map((value) => ({ value, label: value }));

async function loadReviews() {
  try {
    reviews.value = (await listTeamReviews()).data ?? [];
    reviewsLoaded.value = true;
  } catch (error) {
    notifyError(getErrorMessage(error, "待评分列表加载失败"));
  }
}

function openScoreModal(review: TeamReviewItem) {
  scoringReview.value = review;
  scoreForm.value = { score: "", rating: "", self_score: "" };
  scoreOpen.value = true;
}

async function handleSubmitScore() {
  if (!scoringReview.value) return;
  if (!scoreForm.value.score || !scoreForm.value.rating) {
    notifyError("请填写评分与评级");
    return;
  }
  scoreSubmitting.value = true;
  try {
    await submitTeamReviewScore(scoringReview.value.id, {
      score: Number(scoreForm.value.score),
      rating: scoreForm.value.rating,
      self_score: scoreForm.value.self_score ? Number(scoreForm.value.self_score) : null,
    });
    notifySuccess("评分已提交");
    scoreOpen.value = false;
    await loadReviews();
  } catch (error) {
    notifyError(getErrorMessage(error, "评分提交失败"));
  } finally {
    scoreSubmitting.value = false;
  }
}

function switchTab(value: string | number) {
  activeTab.value = value as TabKey;
  if (activeTab.value === "interviews" && !interviewsLoaded.value) void loadInterviews();
  if (activeTab.value === "reviews" && !reviewsLoaded.value) void loadReviews();
}
</script>

<template>
  <AppPage title="团队工作台" description="团队招聘需求、我参与的面试与待评分的绩效评估">
    <div
      v-if="!isLeader"
      class="ring-foreground/10 bg-card flex h-full min-h-0 flex-col items-center justify-center gap-2 rounded-xl text-sm ring-1 shadow-sm"
      data-testid="team-not-leader"
    >
      <p class="font-medium">仅组织负责人可访问团队工作台</p>
      <p class="text-muted-foreground text-xs">担任组织负责人后即可查看团队招聘、面试与绩效评分</p>
    </div>
    <div v-else class="ring-foreground/10 bg-card flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <Tabs :model-value="activeTab" class="flex min-h-0 flex-1 flex-col" @update:model-value="switchTab">
        <div class="shrink-0 border-b px-5 py-3">
          <TabsList>
            <TabsTrigger value="requisitions" data-testid="team-tab-requisitions">团队招聘</TabsTrigger>
            <TabsTrigger value="interviews" data-testid="team-tab-interviews">我的面试</TabsTrigger>
            <TabsTrigger value="reviews" data-testid="team-tab-reviews">待我评分</TabsTrigger>
          </TabsList>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-5" data-testid="team-body">
          <!-- 团队招聘 -->
          <TabsContent v-if="activeTab === 'requisitions'" value="requisitions" class="flex min-h-0 flex-1 flex-col">
            <div class="ring-foreground/10 bg-card flex min-h-[24rem] flex-col overflow-hidden rounded-xl ring-1 shadow-sm">
              <DataTable :data-table="requisitionTable" :fixed-layout="true" data-testid="team-requisition-table" />
            </div>
          </TabsContent>

          <!-- 我的面试 -->
          <TabsContent v-else-if="activeTab === 'interviews'" value="interviews" class="flex flex-col gap-3">
            <div class="ring-foreground/10 bg-card overflow-hidden rounded-xl ring-1 shadow-sm">
              <table class="w-full text-sm" data-testid="team-interview-table">
                <thead>
                  <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
                    <th class="px-4 py-2 font-medium">候选人</th>
                    <th class="px-4 py-2 font-medium">职位</th>
                    <th class="px-4 py-2 font-medium">轮次</th>
                    <th class="px-4 py-2 font-medium">形式</th>
                    <th class="px-4 py-2 font-medium">安排时间</th>
                    <th class="px-4 py-2 font-medium">结果</th>
                    <th class="px-4 py-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="interview in interviews" :key="interview.id" class="border-t" :data-testid="`team-interview-${interview.id}`">
                    <td class="px-4 py-2">{{ interview.candidate_name }}</td>
                    <td class="px-4 py-2">{{ interview.requisition_title }}</td>
                    <td class="px-4 py-2">第 {{ interview.round }} 轮</td>
                    <td class="px-4 py-2">{{ INTERVIEW_FORM_LABELS[interview.interview_form] ?? interview.interview_form }}</td>
                    <td class="px-4 py-2">{{ interview.scheduled_at }}</td>
                    <td class="px-4 py-2">
                      <Badge :variant="INTERVIEW_RESULT_VARIANTS[interview.result] ?? 'secondary'">
                        {{ INTERVIEW_RESULT_LABELS[interview.result] ?? interview.result }}
                      </Badge>
                    </td>
                    <td class="px-4 py-2">
                      <Button
                        v-if="interview.result === 'pending'"
                        variant="outline"
                        size="sm"
                        :data-testid="`team-interview-evaluate-${interview.id}`"
                        @click="$router.push('/hr/interviews')"
                      >
                        去评价
                      </Button>
                      <span v-else class="text-muted-foreground text-xs">--</span>
                    </td>
                  </tr>
                  <tr v-if="interviewsLoaded && interviews.length === 0">
                    <td colspan="7" class="text-muted-foreground px-4 py-8 text-center">暂无我参与的面试</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TabsContent>

          <!-- 待我评分 -->
          <TabsContent v-else value="reviews" class="flex flex-col gap-3">
            <div class="ring-foreground/10 bg-card overflow-hidden rounded-xl ring-1 shadow-sm">
              <table class="w-full text-sm" data-testid="team-review-table">
                <thead>
                  <tr class="bg-muted/50 text-left text-muted-foreground text-xs">
                    <th class="px-4 py-2 font-medium">考核周期</th>
                    <th class="px-4 py-2 font-medium">工号</th>
                    <th class="px-4 py-2 font-medium">姓名</th>
                    <th class="px-4 py-2 font-medium">目标数</th>
                    <th class="px-4 py-2 font-medium">加权进度</th>
                    <th class="px-4 py-2 font-medium">自评分</th>
                    <th class="px-4 py-2 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="review in reviews" :key="review.id" class="border-t" :data-testid="`team-review-${review.id}`">
                    <td class="px-4 py-2">{{ review.cycle_name }}</td>
                    <td class="px-4 py-2">{{ review.employee_no ?? "--" }}</td>
                    <td class="px-4 py-2">{{ review.employee_name ?? "--" }}</td>
                    <td class="px-4 py-2">{{ review.goal_count }}</td>
                    <td class="px-4 py-2 tabular-nums">{{ review.weighted_progress }}%</td>
                    <td class="px-4 py-2 tabular-nums">{{ review.self_score ?? "--" }}</td>
                    <td class="px-4 py-2">
                      <Button
                        variant="outline"
                        size="sm"
                        :data-testid="`team-review-score-${review.id}`"
                        @click="openScoreModal(review)"
                      >
                        评分
                      </Button>
                    </td>
                  </tr>
                  <tr v-if="reviewsLoaded && reviews.length === 0">
                    <td colspan="7" class="text-muted-foreground px-4 py-8 text-center">暂无待评分的评估</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </TabsContent>
        </div>
      </Tabs>
    </div>

    <!-- 评分弹窗 -->
    <Dialog v-model:open="scoreOpen">
      <DialogContent class="sm:max-w-md" data-testid="team-score-modal">
        <div v-if="scoringReview" class="flex flex-col gap-3">
          <div>
            <p class="font-medium">提交评分</p>
            <p class="text-muted-foreground mt-1 text-xs">
              {{ scoringReview.cycle_name }} · {{ scoringReview.employee_name }}（{{ scoringReview.employee_no ?? "--" }}）·
              目标加权进度 {{ scoringReview.weighted_progress }}%
            </p>
          </div>
          <div class="flex items-center gap-2">
            <span class="w-20 shrink-0 text-sm">评分</span>
            <Input v-model="scoreForm.score" type="number" placeholder="0-100" data-testid="team-score-input" />
          </div>
          <div class="flex items-center gap-2">
            <span class="w-20 shrink-0 text-sm">评级</span>
            <Select
              v-model="scoreForm.rating"
              trigger-class="w-32"
              placeholder="请选择评级"
              :options="ratingOptions"
              data-testid="team-rating-select"
            />
          </div>
          <div class="flex items-center gap-2">
            <span class="w-20 shrink-0 text-sm">自评分</span>
            <Input v-model="scoreForm.self_score" type="number" placeholder="选填" data-testid="team-self-score-input" />
          </div>
          <div class="flex justify-end gap-2">
            <Button variant="outline" size="sm" @click="scoreOpen = false">取消</Button>
            <Button size="sm" :disabled="scoreSubmitting" data-testid="team-score-submit" @click="handleSubmitScore">
              提交评分
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  </AppPage>
</template>
