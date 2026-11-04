<script setup lang="ts">
/**
 * 报表分析页：人事/招聘/薪酬/绩效四域切换 + 真日期区间（起止 DateInput，默认近半年）
 * + 组织子树下钻（人事/招聘共用，人事域组织行点击下钻）。
 * 折线图走 ui/chart（unovis）范式，条形（组织分布/漏斗/渠道/薪酬分布）
 * 用 HTML 水平条形；人事域附规则化离职风险名单（Top 20，跟随下钻）。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, DateInput, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";
import { useUserStore } from "@/framework/stores";
import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import {
  exportReport,
  getReportAttritionRisk,
  getReportCompDist,
  getReportOverview,
  getReportPerformance,
  getReportRecruiting,
  getReportTurnover,
} from "@/hr/api/report";
import { getOrgTree } from "@/hr/api/reference";
import ReportAskDialog from "@/hr/components/report/ReportAskDialog.vue";
import TrendLineChart from "@/hr/components/report/TrendLineChart.vue";
import { downloadBase64File } from "@/hr/utils/download";
import {
  defaultReportRange,
  type AttritionRiskData,
  type CompDistData,
  type OverviewData,
  type PerformanceData,
  type RecruitingData,
  type TurnoverData,
} from "@/hr/types/report";
import { PERF_RATINGS } from "@/hr/types/perf";
import { APPLICATION_STAGE_LABELS, CANDIDATE_CHANNEL_LABELS, FUNNEL_SEGMENTS } from "@/hr/types/recruiting";
import type { OrgTreeNode } from "@/hr/types/employee";

type DomainKey = "personnel" | "recruiting" | "compensation" | "performance";

const userStore = useUserStore();
const canSalary = computed(() => userStore.hasPermission("hr:salary_package:read"));
const canExport = computed(() => userStore.hasPermission("hr:report:export"));
const canAsk = computed(() => userStore.hasPermission("hr:report:read"));
const askOpen = ref(false);

const DOMAINS: { value: DomainKey; label: string }[] = [
  { value: "personnel", label: "人事" },
  { value: "recruiting", label: "招聘" },
  { value: "compensation", label: "薪酬" },
  { value: "performance", label: "绩效" },
];

const visibleDomains = computed(() => DOMAINS.filter((d) => d.value !== "compensation" || canSalary.value));

const activeDomain = ref<DomainKey>("personnel");
const initialRange = defaultReportRange();
const dateFrom = ref(initialRange.date_from);
const dateTo = ref(initialRange.date_to);
const drillOrgId = ref<string | null>(null);
const loading = ref(false);

const overview = ref<OverviewData | null>(null);
const turnover = ref<TurnoverData | null>(null);
const recruiting = ref<RecruitingData | null>(null);
const compDist = ref<CompDistData | null>(null);
const performance = ref<PerformanceData | null>(null);
const riskList = ref<AttritionRiskData | null>(null);
const orgTree = ref<OrgTreeNode[]>([]);

const compLoaded = ref(false);
const perfLoaded = ref(false);

function envelope<T>(res: { data: T | null }): T | null {
  return res.data ?? null;
}

function rangeParams() {
  return {
    date_from: dateFrom.value || undefined,
    date_to: dateTo.value || undefined,
    org_id: drillOrgId.value ?? undefined,
  };
}

const EXPORT_DOMAIN_BY_TAB: Record<DomainKey, string> = {
  personnel: "overview",
  recruiting: "recruiting",
  compensation: "comp-dist",
  performance: "performance",
};

const exporting = ref(false);

async function handleExport() {
  if (exporting.value) return;
  exporting.value = true;
  try {
    const res = await exportReport({ ...rangeParams(), domain: EXPORT_DOMAIN_BY_TAB[activeDomain.value] });
    const file = res.data;
    if (!file?.content_base64) {
      notifyError(new Error("报表文件生成失败"));
      return;
    }
    downloadBase64File(file.filename, file.content_base64);
    notifySuccess("报表已导出（已写审计）");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "报表导出失败"));
  } finally {
    exporting.value = false;
  }
}

async function loadPersonnel() {
  const [overviewRes, turnoverRes] = await Promise.all([
    getReportOverview(rangeParams()),
    getReportTurnover(rangeParams()),
  ]);
  overview.value = envelope(overviewRes);
  turnover.value = envelope(turnoverRes);
  await ensureOrgTree();
}

async function loadRisk() {
  riskList.value = envelope(
    await getReportAttritionRisk({ org_id: drillOrgId.value ?? undefined, limit: 20 }),
  );
}

async function loadRecruiting() {
  recruiting.value = envelope(await getReportRecruiting(rangeParams()));
}

async function loadCompensation() {
  if (compLoaded.value) return;
  compDist.value = envelope(await getReportCompDist());
  compLoaded.value = true;
}

async function loadPerformance() {
  if (perfLoaded.value) return;
  performance.value = envelope(await getReportPerformance());
  perfLoaded.value = true;
}

async function ensureOrgTree() {
  if (orgTree.value.length > 0) return;
  const res = await getOrgTree();
  orgTree.value = res.data ?? [];
}

watch(
  [activeDomain, dateFrom, dateTo, drillOrgId],
  async () => {
    loading.value = true;
    try {
      if (activeDomain.value === "personnel") await Promise.all([loadPersonnel(), loadRisk()]);
      else if (activeDomain.value === "recruiting") await loadRecruiting();
      else if (activeDomain.value === "performance") await loadPerformance();
      else {
        await Promise.all([loadCompensation(), ensureOrgTree()]);
      }
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

/* ── 人事域派生 ── */

const statCards = computed(() => [
  { key: "active", label: "在编人数", value: overview.value?.cards.active_count ?? 0 },
  { key: "probation", label: "试用期人数", value: overview.value?.cards.probation_count ?? 0 },
  { key: "month_hired", label: "本月新入职", value: overview.value?.cards.month_hired_count ?? 0 },
  {
    key: "turnover",
    label: "离职率（近12月）",
    value: `${((overview.value?.cards.turnover_rate ?? 0) * 100).toFixed(1)}%`,
  },
]);

const headcountPoints = computed(() =>
  (overview.value?.headcount_trend ?? []).map((p) => ({ label: p.month, value: p.count })),
);

const turnoverPoints = computed(() =>
  (turnover.value?.points ?? []).map((p) => ({ label: p.month, value: p.rate ?? 0 })),
);

/* ── 组织分布（按组织树聚合下钻） ── */

const distMap = computed(() => {
  const map = new Map<string, number>();
  (overview.value?.org_distribution ?? []).forEach((item) => {
    if (item.org_id) map.set(item.org_id, item.count);
  });
  return map;
});

const unassignedCount = computed(
  () => (overview.value?.org_distribution ?? []).find((item) => !item.org_id)?.count ?? 0,
);

const orgNodeMap = computed(() => {
  const map = new Map<string, OrgTreeNode>();
  const walk = (nodes: OrgTreeNode[]) => {
    nodes.forEach((node) => {
      map.set(node.id, node);
      if (node.children?.length) walk(node.children);
    });
  };
  walk(orgTree.value);
  return map;
});

function subtreeCount(node: OrgTreeNode): number {
  let total = distMap.value.get(node.id) ?? 0;
  node.children?.forEach((child) => {
    total += subtreeCount(child);
  });
  return total;
}

interface OrgRow {
  id: string;
  name: string;
  count: number;
  depth: number;
  expandable: boolean;
}

const expandedOrgs = ref<Set<string>>(new Set());

function buildOrgRows(nodes: OrgTreeNode[], depth: number, rows: OrgRow[]) {
  nodes.forEach((node) => {
    const count = subtreeCount(node);
    if (count <= 0) return;
    const expandable = Boolean(node.children?.length);
    rows.push({ id: node.id, name: node.name, count, depth, expandable });
    if (expandable && expandedOrgs.value.has(node.id)) {
      buildOrgRows(node.children ?? [], depth + 1, rows);
    }
  });
}

const orgRows = computed<OrgRow[]>(() => {
  const rows: OrgRow[] = [];
  buildOrgRows(orgTree.value, 0, rows);
  if (unassignedCount.value > 0) {
    rows.push({ id: "__none__", name: "未分配组织", count: unassignedCount.value, depth: 0, expandable: false });
  }
  return rows;
});

function toggleOrgRow(row: OrgRow) {
  if (!row.expandable) return;
  const next = new Set(expandedOrgs.value);
  if (next.has(row.id)) next.delete(row.id);
  else next.add(row.id);
  expandedOrgs.value = next;
}

const orgDistMax = computed(() => Math.max(1, ...orgRows.value.map((row) => row.count)));

/* ── 组织下钻（人事/招聘共用） ── */

const drillOrgName = computed(
  () => orgNodeMap.value.get(drillOrgId.value ?? "")?.name ?? drillOrgId.value ?? "",
);

function drillTo(row: OrgRow) {
  if (row.id === "__none__") return;
  drillOrgId.value = row.id;
}

function resetDrill() {
  drillOrgId.value = null;
}

/* ── 离职风险名单派生 ── */

const RISK_LEVEL_META: Record<string, { label: string; variant: "default" | "secondary" | "destructive" }> = {
  high: { label: "高风险", variant: "destructive" },
  mid: { label: "中风险", variant: "default" },
  low: { label: "低风险", variant: "secondary" },
};

const riskRows = computed(() =>
  (riskList.value?.items ?? []).map((item) => ({
    ...item,
    orgName: item.org_id ? (orgNodeMap.value.get(item.org_id)?.name ?? "未分配组织") : "未分配组织",
    levelLabel: RISK_LEVEL_META[item.level]?.label ?? item.level,
    levelVariant: RISK_LEVEL_META[item.level]?.variant ?? ("secondary" as const),
  })),
);

/* ── 招聘域派生 ── */

const funnelRows = computed(() => {
  const items = recruiting.value?.funnel ?? [];
  const max = Math.max(1, ...items.map((item) => item.count));
  return items.map((item) => ({
    stage: item.stage,
    label: APPLICATION_STAGE_LABELS[item.stage as keyof typeof APPLICATION_STAGE_LABELS] ?? item.stage,
    count: item.count,
    percent: Math.round((item.count / max) * 100),
  }));
});

interface ChannelRow {
  channel: string;
  label: string;
  total: number;
  hired: number;
  rate: string;
  percent: number;
}

/** 录用转化分母=全阶段投递合计，分子=录用段（pre_hire→onboarded）合计，对齐候选人页三段漏斗口径 */
const HIRE_STAGES = FUNNEL_SEGMENTS.find((segment) => segment.key === "hire")?.stages ?? [];

const channelRows = computed<ChannelRow[]>(() =>
  (recruiting.value?.channels ?? []).map((item) => {
    const total = Object.values(item.stages).reduce((sum, count) => sum + count, 0);
    const hired = HIRE_STAGES.reduce((sum, stage) => sum + (item.stages[stage] ?? 0), 0);
    return {
      channel: item.channel,
      label: CANDIDATE_CHANNEL_LABELS[item.channel] ?? item.channel ?? "未知渠道",
      total,
      hired,
      rate: total > 0 ? `${((hired / total) * 100).toFixed(1)}%` : "0.0%",
      percent: 0,
    };
  }),
);

const channelMax = computed(() => Math.max(1, ...channelRows.value.map((row) => row.total)));

/* ── 薪酬域派生 ── */

interface CompRow {
  key: string;
  label: string;
  count: number;
  mid: number;
  percent: number;
}

function toCompRows(items: CompDistItem[], labelOf: (key: string | null) => string): CompRow[] {
  const max = Math.max(1, ...items.map((item) => item.count));
  return items.map((item) => ({
    key: item.key ?? "__none__",
    label: labelOf(item.key),
    count: item.count,
    mid: item.mid_amount,
    percent: Math.round((item.count / max) * 100),
  }));
}

const levelRows = computed(() => toCompRows(compDist.value?.by_level ?? [], (key) => key ?? "未定级"));
const compOrgRows = computed(() => toCompRows(compDist.value?.by_org ?? [], (key) => orgNodeMap.value.get(key ?? "")?.name ?? "未分配组织"));

/* ── 绩效域派生 ── */

const perfScorePoints = computed(() =>
  (performance.value?.cycles ?? [])
    .filter((cycle) => cycle.avg_score != null)
    .map((cycle) => ({ label: cycle.cycle_name, value: cycle.avg_score ?? 0 })),
);

const perfDistRows = computed(() => {
  const cycles = performance.value?.cycles ?? [];
  const max = Math.max(
    1,
    ...cycles.flatMap((cycle) => PERF_RATINGS.map((rating) => cycle.ratings[rating] ?? 0)),
  );
  return cycles.map((cycle) => ({
    id: cycle.cycle_id,
    name: cycle.cycle_name,
    total: cycle.total,
    avg: cycle.avg_score,
    bars: PERF_RATINGS.map((rating) => ({
      rating,
      count: cycle.ratings[rating] ?? 0,
      percent: Math.round(((cycle.ratings[rating] ?? 0) / max) * 100),
    })),
  }));
});
</script>

<template>
  <AppPage title="报表分析" description="人事 / 招聘 / 薪酬 / 绩效多维报表与趋势分析">
    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <Tabs v-model="activeDomain" class="flex min-h-0 flex-1 flex-col">
        <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-5 py-3">
          <TabsList>
            <TabsTrigger
              v-for="domain in visibleDomains"
              :key="domain.value"
              :value="domain.value"
              :data-testid="`report-tab-${domain.value}`"
            >
              {{ domain.label }}
            </TabsTrigger>
          </TabsList>
          <div class="flex flex-wrap items-center gap-2">
            <button
              v-if="drillOrgId"
              type="button"
              class="bg-muted hover:bg-muted/70 flex items-center gap-1 rounded-full px-3 py-1 text-xs"
              data-testid="report-drill-chip"
              @click="resetDrill"
            >
              下钻：{{ drillOrgName }} ✕
            </button>
            <DateInput v-model="dateFrom" placeholder="开始日期" class="w-36" data-testid="report-date-from" />
            <span class="text-muted-foreground text-xs">至</span>
            <DateInput v-model="dateTo" placeholder="结束日期" class="w-36" data-testid="report-date-to" />
            <Button
              v-if="canAsk"
              variant="outline"
              data-testid="report-ask"
              @click="askOpen = true"
            >
              AI 问数
            </Button>
            <Button
              v-if="canExport"
              variant="outline"
              :disabled="exporting"
              data-testid="report-export"
              @click="handleExport"
            >
              导出
            </Button>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-5" data-testid="report-body">
          <p v-if="loading" class="py-10 text-center text-muted-foreground">加载中…</p>

          <!-- 人事域 -->
          <TabsContent v-else-if="activeDomain === 'personnel'" value="personnel" class="flex flex-col gap-4">
          <div class="grid shrink-0 grid-cols-2 gap-4 lg:grid-cols-4" data-testid="report-personnel-cards">
            <div
              v-for="card in statCards"
              :key="card.key"
              class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm"
              :data-testid="`report-card-${card.key}`"
            >
              <p class="text-muted-foreground text-xs">{{ card.label }}</p>
              <p class="mt-1 text-2xl font-semibold">{{ card.value }}</p>
            </div>
          </div>

          <p
            v-if="overview?.metric_ref"
            class="text-muted-foreground text-xs"
            data-testid="report-metric-ref-headcount"
          >
            口径 · {{ overview.metric_ref.display_name }}：{{ overview.metric_ref.description }}
            （{{ overview.metric_ref.source === "ontology" ? "治理目录" : "内置口径" }}）
          </p>

          <div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-chart-headcount">
              <p class="mb-2 font-medium">在编人数趋势</p>
              <TrendLineChart :points="headcountPoints" />
            </div>
            <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-chart-turnover">
              <p class="mb-2 font-medium">离职率趋势</p>
              <TrendLineChart :points="turnoverPoints" color="#dc2626" value-suffix="%" />
            </div>
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-org-dist">
            <p class="mb-3 font-medium">组织分布（在编）</p>
            <div class="flex flex-col gap-2">
              <div
                v-for="row in orgRows"
                :key="row.id"
                class="flex items-center gap-3"
                :data-testid="`report-org-row-${row.id}`"
              >
                <button
                  v-if="row.expandable"
                  type="button"
                  class="text-muted-foreground w-4 shrink-0 text-left"
                  :data-testid="`report-org-toggle-${row.id}`"
                  @click="toggleOrgRow(row)"
                >
                  {{ expandedOrgs.has(row.id) ? "▾" : "▸" }}
                </button>
                <span v-else class="w-4 shrink-0" />
                <button
                  v-if="row.id !== '__none__'"
                  type="button"
                  class="w-40 shrink-0 cursor-pointer truncate text-left hover:underline"
                  :style="{ paddingLeft: `${row.depth * 16}px` }"
                  :data-testid="`report-org-drill-${row.id}`"
                  title="点击下钻该组织子树"
                  @click="drillTo(row)"
                >
                  {{ row.name }}
                </button>
                <span v-else class="w-40 shrink-0 truncate" :style="{ paddingLeft: `${row.depth * 16}px` }">{{ row.name }}</span>
                <div class="bg-muted h-2 min-w-0 flex-1 overflow-hidden rounded-full">
                  <div class="h-full rounded-full bg-blue-500" :style="{ width: `${Math.round((row.count / orgDistMax) * 100)}%` }" />
                </div>
                <span class="w-12 shrink-0 text-right tabular-nums">{{ row.count }}</span>
              </div>
              <p v-if="orgRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-risk-panel">
            <p class="mb-3 font-medium">离职风险名单（Top 20 · 规则评分实时）</p>
            <div class="flex flex-col gap-2">
              <div
                v-for="item in riskRows"
                :key="item.employee_id"
                class="flex flex-wrap items-center gap-2"
                :data-testid="`report-risk-item-${item.employee_id}`"
              >
                <Badge :variant="item.levelVariant" data-testid="report-risk-level">{{ item.levelLabel }} {{ item.score }}</Badge>
                <span class="w-36 shrink-0 truncate">
                  {{ item.name }}<template v-if="item.employee_no">（{{ item.employee_no }}）</template>
                </span>
                <span class="text-muted-foreground w-24 shrink-0 truncate text-xs">{{ item.orgName }}</span>
                <span class="flex min-w-0 flex-1 flex-wrap gap-1">
                  <span
                    v-for="factor in item.factors"
                    :key="factor"
                    class="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-xs"
                  >{{ factor }}</span>
                </span>
              </div>
              <p v-if="riskRows.length === 0" class="py-6 text-center text-muted-foreground">暂无风险人员</p>
            </div>
          </div>
        </TabsContent>

        <!-- 招聘域 -->
        <TabsContent v-else-if="activeDomain === 'recruiting'" value="recruiting" class="flex flex-col gap-4">
          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-funnel">
            <p class="mb-3 font-medium">招聘漏斗（全渠道）</p>
            <div class="flex flex-col gap-2">
              <div v-for="row in funnelRows" :key="row.stage" class="flex items-center gap-3" :data-testid="`report-funnel-row-${row.stage}`">
                <span class="w-24 shrink-0 truncate text-right">{{ row.label }}</span>
                <div class="bg-muted h-4 min-w-0 flex-1 overflow-hidden rounded">
                  <div class="bg-blue-500 flex h-full items-center rounded pl-2 text-xs text-white" :style="{ width: `${Math.max(row.percent, row.count > 0 ? 8 : 0)}%` }">
                    {{ row.count > 0 ? row.count : "" }}
                  </div>
                </div>
              </div>
              <p v-if="funnelRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-channels">
            <p class="mb-3 font-medium">渠道转化对比</p>
            <div class="flex flex-col gap-2">
              <div v-for="row in channelRows" :key="row.channel" class="flex items-center gap-3" :data-testid="`report-channel-row-${row.channel}`">
                <span class="w-28 shrink-0 truncate text-right">{{ row.label }}</span>
                <div class="bg-muted h-4 min-w-0 flex-1 overflow-hidden rounded">
                  <div class="h-full rounded bg-blue-500" :style="{ width: `${Math.round((row.total / channelMax) * 100)}%` }" />
                </div>
                <span class="w-32 shrink-0 text-xs text-muted-foreground">
                  录用 {{ row.hired }}/{{ row.total }}（{{ row.rate }}）
                </span>
              </div>
              <p v-if="channelRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>
        </TabsContent>

        <!-- 薪酬域 -->
        <TabsContent v-else-if="activeDomain === 'compensation'" value="compensation" class="flex flex-col gap-4">
          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-comp-level">
            <p class="mb-3 font-medium">职级薪酬分布（在编，金额脱敏）</p>
            <div class="flex flex-col gap-2">
              <div v-for="row in levelRows" :key="row.key" class="flex items-center gap-3" :data-testid="`report-level-row-${row.key}`">
                <span class="w-28 shrink-0 truncate text-right">{{ row.label }}</span>
                <div class="bg-muted h-4 min-w-0 flex-1 overflow-hidden rounded">
                  <div class="h-full rounded bg-blue-500" :style="{ width: `${row.percent}%` }" />
                </div>
                <span class="w-40 shrink-0 text-xs text-muted-foreground">{{ row.count }} 人 · 中位数 {{ row.mid.toLocaleString("zh-CN") }} 元</span>
              </div>
              <p v-if="levelRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-comp-org">
            <p class="mb-3 font-medium">组织薪酬分布（在编，金额脱敏）</p>
            <div class="flex flex-col gap-2">
              <div v-for="row in compOrgRows" :key="row.key" class="flex items-center gap-3" :data-testid="`report-comp-org-row-${row.key}`">
                <span class="w-28 shrink-0 truncate text-right">{{ row.label }}</span>
                <div class="bg-muted h-4 min-w-0 flex-1 overflow-hidden rounded">
                  <div class="h-full rounded bg-blue-500" :style="{ width: `${row.percent}%` }" />
                </div>
                <span class="w-40 shrink-0 text-xs text-muted-foreground">{{ row.count }} 人 · 中位数 {{ row.mid.toLocaleString("zh-CN") }} 元</span>
              </div>
              <p v-if="compOrgRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>
        </TabsContent>

        <!-- 绩效域 -->
        <TabsContent v-else value="performance" class="flex flex-col gap-4">
          <p
            v-if="performance?.metric_ref"
            class="text-muted-foreground text-xs"
            data-testid="report-metric-ref-perf"
          >
            口径 · {{ performance.metric_ref.display_name }}：{{ performance.metric_ref.description }}
            （{{ performance.metric_ref.source === "ontology" ? "治理目录" : "内置口径" }}）
          </p>
          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-perf-trend">
            <p class="mb-2 font-medium">周期均分趋势（closed 周期）</p>
            <TrendLineChart v-if="perfScorePoints.length" :points="perfScorePoints" />
            <p v-else class="py-6 text-center text-muted-foreground">暂无已收口周期数据</p>
          </div>

          <div class="bg-card ring-foreground/10 rounded-xl p-4 ring-1 shadow-sm" data-testid="report-perf-dist">
            <p class="mb-3 font-medium">周期评级分布（最终评级优先）</p>
            <div class="flex flex-col gap-4">
              <div v-for="row in perfDistRows" :key="row.id" :data-testid="`report-perf-cycle-${row.id}`">
                <p class="text-muted-foreground mb-2 text-xs">
                  {{ row.name }} · 共 {{ row.total }} 人
                  <template v-if="row.avg != null"> · 均分 {{ row.avg }}</template>
                </p>
                <div class="flex flex-col gap-1.5">
                  <div v-for="bar in row.bars" :key="bar.rating" class="flex items-center gap-3">
                    <span class="text-muted-foreground w-4 text-xs">{{ bar.rating }}</span>
                    <div class="bg-muted h-4 min-w-0 flex-1 overflow-hidden rounded">
                      <div class="h-full rounded bg-emerald-500" :style="{ width: `${bar.percent}%` }" />
                    </div>
                    <span class="text-muted-foreground w-10 shrink-0 text-right text-xs">{{ bar.count }} 人</span>
                  </div>
                </div>
              </div>
              <p v-if="perfDistRows.length === 0" class="py-6 text-center text-muted-foreground">暂无数据</p>
            </div>
          </div>
        </TabsContent>
        </div>
      </Tabs>
    </div>
    <ReportAskDialog v-model:open="askOpen" />
  </AppPage>
</template>
