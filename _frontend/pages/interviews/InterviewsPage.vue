<script setup lang="ts">
/**
 * 面试日程页：周视图（今日起 7 天按日分组日程列）/ 列表视图切换
 * + 内存筛选（需求关键词/结论/我参与的）+ 周平移 + 快捷安排与面试评价弹窗。
 * 数据源为 weekly 聚合接口（无独立列表端点），列表视图由日程数据扁平化而来。
 */
import { computed, onMounted, ref } from "vue";

import { Badge, Button, Checkbox, Input, Select, Table } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { getErrorMessage, notifyError } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { getWeeklyInterviews } from "@/hr/api/interview";
import InterviewQuickScheduleModal from "@/hr/components/interview/InterviewQuickScheduleModal.vue";
import InterviewReviewModal from "@/hr/components/interview/InterviewReviewModal.vue";
import {
  INTERVIEW_FORM_LABELS,
  INTERVIEW_RESULT_LABELS,
  INTERVIEW_RESULT_VARIANTS,
  type InterviewDayItem,
  type InterviewForm,
} from "@/hr/types/recruiting";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:interview:write"));
const currentUserId = computed(() => userStore.userInfo?.id ?? "");

/* ── 视图与周平移 ── */

const viewMode = ref<"week" | "list">("week");
const startDate = ref(todayStr());

const WEEKDAY_LABELS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

function todayStr(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function dayLabel(iso: string): string {
  const date = new Date(`${iso}T00:00:00`);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function weekdayLabel(iso: string): string {
  return WEEKDAY_LABELS[new Date(`${iso}T00:00:00`).getDay()];
}

function shiftWeek(days: number) {
  startDate.value = days === 0 ? todayStr() : addDays(startDate.value, days);
  void loadWeek();
}

/* ── 数据加载 ── */

const days = ref<{ date: string; items: InterviewDayItem[] }[]>([]);
const loading = ref(false);

async function loadWeek() {
  loading.value = true;
  try {
    const res = await getWeeklyInterviews(startDate.value);
    const raw = res.data?.days ?? {};
    days.value = Object.keys(raw)
      .sort()
      .map((date) => ({ date, items: raw[date] ?? [] }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "面试日程加载失败"));
    days.value = [];
  } finally {
    loading.value = false;
  }
}

const allItems = computed(() => days.value.flatMap((day) => day.items));

/* ── 内存筛选 ── */

const keyword = ref("");
const resultFilter = ref("all");
const mineOnly = ref(false);

const resultOptions = [
  { value: "all", label: "全部结论" },
  ...Object.entries(INTERVIEW_RESULT_LABELS).map(([value, label]) => ({ value, label })),
];

const filteredItems = computed(() =>
  allItems.value.filter((item) => {
    if (resultFilter.value !== "all" && item.result !== resultFilter.value) return false;
    if (mineOnly.value && item.interviewer_id !== currentUserId.value) return false;
    if (keyword.value && !(item.requisition_title ?? "").includes(keyword.value.trim())) return false;
    return true;
  }),
);

const filteredDays = computed(() =>
  days.value.map((day) => ({
    ...day,
    items: filteredItems.value.filter((item) => item.scheduled_at.slice(0, 10) === day.date),
  })),
);

function handleResetFilters() {
  keyword.value = "";
  resultFilter.value = "all";
  mineOnly.value = false;
}

/* ── 弹窗编排 ── */

const quickOpen = ref(false);
const quickPresetDate = ref<string | null>(null);

const reviewOpen = ref(false);
const reviewTarget = ref<InterviewDayItem | null>(null);

function openQuickSchedule(presetDate: string | null) {
  quickPresetDate.value = presetDate;
  quickOpen.value = true;
}

function openReview(item: InterviewDayItem) {
  reviewTarget.value = item;
  reviewOpen.value = true;
}

function handleSaved() {
  void loadWeek();
}

const listColumns = [
  { key: "candidate", title: "候选人", width: "110px" },
  { key: "requisition", title: "应聘需求", width: "200px" },
  { key: "round", title: "轮次", width: "70px" },
  { key: "scheduled_at", title: "时间", width: "150px" },
  { key: "interview_form", title: "形式", width: "90px" },
  { key: "result", title: "结论", width: "90px" },
  { key: "actions", title: "操作", width: "90px", align: "right" as const },
];

const overdueIds = computed(() => {
  const now = Date.now();
  return new Set(
    filteredItems.value
      .filter((item) => item.result === "pending" && new Date(item.scheduled_at).getTime() < now)
      .map((item) => item.id),
  );
});

function timeOf(item: InterviewDayItem): string {
  return item.scheduled_at.slice(5, 16).replace("T", " ");
}

function formLabel(form: string): string {
  return INTERVIEW_FORM_LABELS[form as InterviewForm] ?? form;
}

onMounted(() => {
  void loadWeek();
});
</script>

<template>
  <AppPage title="面试日程" description="跨需求面试安排：周视图日程、评价与改期、快捷安排">
    <template #actions>
      <div class="flex items-center gap-2">
        <div class="flex overflow-hidden rounded-md border" data-testid="interview-view-toggle">
          <Button
            variant="ghost"
            size="sm"
            :class="viewMode === 'week' ? 'bg-accent' : ''"
            data-testid="interview-view-week"
            @click="viewMode = 'week'"
          >
            周视图
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :class="viewMode === 'list' ? 'bg-accent' : ''"
            data-testid="interview-view-list"
            @click="viewMode = 'list'"
          >
            列表视图
          </Button>
        </div>
        <Button v-if="canWrite" data-testid="open-interview-quick" @click="openQuickSchedule(null)">安排面试</Button>
      </div>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 筛选栏 + 周平移 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Button variant="outline" size="sm" data-testid="interview-week-prev" @click="shiftWeek(-7)">上一周</Button>
        <Button variant="outline" size="sm" data-testid="interview-week-this" @click="shiftWeek(0)">本周</Button>
        <Button variant="outline" size="sm" data-testid="interview-week-next" @click="shiftWeek(7)">下一周</Button>
        <Input
          v-model="keyword"
          class="w-40"
          placeholder="按需求名称"
          data-testid="interview-keyword-input"
        />
        <Select v-model="resultFilter" trigger-class="w-32" :options="resultOptions" data-testid="interview-result-filter" />
        <label class="flex items-center gap-1.5 text-sm">
          <Checkbox
            :model-value="mineOnly"
            data-testid="interview-mine-only"
            @update:model-value="mineOnly = $event === true"
          />
          我参与的
        </label>
        <Button variant="ghost" size="sm" data-testid="interview-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 主内容区 -->
      <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
        <!-- 周视图：今日起 7 天按日分组 -->
        <div
          v-if="viewMode === 'week'"
          class="grid gap-3"
          style="grid-template-columns: repeat(7, minmax(150px, 1fr))"
          data-testid="interview-week-grid"
        >
          <div
            v-for="day in filteredDays"
            :key="day.date"
            class="flex min-h-0 flex-col gap-2 rounded-lg border p-2"
            :class="day.date === startDate ? 'border-primary/40 bg-primary/5' : ''"
            :data-testid="`interview-day-${day.date}`"
          >
            <div class="flex shrink-0 items-center justify-between px-1">
              <div class="flex items-baseline gap-1">
                <span class="font-medium">{{ dayLabel(day.date) }}</span>
                <span class="text-muted-foreground text-xs">{{ weekdayLabel(day.date) }}</span>
                <Badge v-if="day.date === todayStr()" variant="outline" class="ml-1">今天</Badge>
              </div>
              <span class="text-muted-foreground text-xs">{{ day.items.length }}</span>
            </div>
            <button
              v-for="item in day.items"
              :key="item.id"
              type="button"
              class="flex flex-col gap-1 rounded-md border px-2.5 py-2 text-left text-xs hover:bg-accent"
              :class="overdueIds.has(item.id) ? 'border-destructive/40' : ''"
              :data-testid="`interview-card-${item.id}`"
              @click="openReview(item)"
            >
              <span class="flex items-center justify-between gap-1">
                <span class="text-sm font-medium">{{ item.candidate_name }}</span>
                <Badge :variant="INTERVIEW_RESULT_VARIANTS[item.result]">
                  {{ INTERVIEW_RESULT_LABELS[item.result] ?? item.result }}
                </Badge>
              </span>
              <span class="text-muted-foreground truncate">{{ item.requisition_title }}</span>
              <span>第 {{ item.round }} 轮 · {{ timeOf(item) }}</span>
              <span class="text-muted-foreground">{{ formLabel(item.interview_form) }}</span>
            </button>
            <p v-if="!day.items.length" class="text-muted-foreground px-1 py-3 text-center text-xs">无安排</p>
            <Button
              v-if="canWrite"
              variant="ghost"
              size="sm"
              class="text-muted-foreground mt-auto"
              :data-testid="`interview-day-add-${day.date}`"
              @click="openQuickSchedule(day.date)"
            >
              + 安排
            </Button>
          </div>
        </div>

        <!-- 列表视图：日程数据扁平化 -->
        <Table
          v-else
          :columns="listColumns"
          :data="filteredItems"
          :loading="loading"
          empty-text="所选时间段内无面试安排"
          data-testid="interview-list-table"
        >
          <template #candidate="{ row }">
            <button
              type="button"
              class="hover:underline"
              :data-testid="`interview-review-${(row as InterviewDayItem).id}`"
              @click="openReview(row as InterviewDayItem)"
            >
              {{ (row as InterviewDayItem).candidate_name }}
            </button>
          </template>
          <template #requisition="{ row }">
            {{ (row as InterviewDayItem).requisition_title }}
          </template>
          <template #round="{ row }">第 {{ (row as InterviewDayItem).round }} 轮</template>
          <template #scheduled_at="{ row }">
            <span :class="overdueIds.has((row as InterviewDayItem).id) ? 'text-destructive' : ''">
              {{ timeOf(row as InterviewDayItem) }}
              <span v-if="overdueIds.has((row as InterviewDayItem).id)">（超时未评价）</span>
            </span>
          </template>
          <template #interview_form="{ row }">
            {{ formLabel((row as InterviewDayItem).interview_form) }}
          </template>
          <template #result="{ row }">
            <Badge :variant="INTERVIEW_RESULT_VARIANTS[(row as InterviewDayItem).result]">
              {{ INTERVIEW_RESULT_LABELS[(row as InterviewDayItem).result] ?? (row as InterviewDayItem).result }}
            </Badge>
          </template>
          <template #actions="{ row }">
            <Button
              variant="link"
              size="sm"
              class="h-auto p-0"
              :data-testid="`interview-review-action-${(row as InterviewDayItem).id}`"
              @click="openReview(row as InterviewDayItem)"
            >
              评价
            </Button>
          </template>
        </Table>
      </div>
    </div>

    <!-- 快捷安排弹窗 -->
    <InterviewQuickScheduleModal v-model:open="quickOpen" :preset-date="quickPresetDate" @saved="handleSaved" />

    <!-- 面试评价弹窗（结论/反馈/改期/AI 纪要） -->
    <InterviewReviewModal v-model:open="reviewOpen" :interview="reviewTarget" @saved="handleSaved" />
  </AppPage>
</template>
