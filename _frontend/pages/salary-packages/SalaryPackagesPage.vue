<script setup lang="ts">
/**
 * 定薪调薪页：左员工检索列表 + 右方案详情（信息头+薪带对标+当前方案+定薪历史）
 * 主从布局；调薪弹窗新旧对比（SalaryPackageEditorModal）。在职员工方可发起调薪。
 */
import { computed, onMounted, ref } from "vue";

import { Badge, Button, Input } from "@/components";
import { ScrollArea } from "@/components/ui/scroll-area";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { getErrorMessage, notifyError } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { getBandComparison, getOrgTree, getPositionOptions, listEmployeeSalaryPackages } from "@/hr/api/reference";
import { listEmployees } from "@/hr/api/employee";
import SalaryPackageEditorModal from "@/hr/components/salary/SalaryPackageEditorModal.vue";
import {
  EMPLOYEE_STATUS_LABELS,
  type Employee,
  type EmployeeStatus,
  type BandComparison,
  type OrgTreeNode,
  type PositionOption,
  type SalaryPackageRecord,
} from "@/hr/types/employee";
import { SALARY_PACKAGE_REASON_LABELS } from "@/hr/types/salary";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:salary_package:write"));

/** 可发起调薪的在职状态（与发薪覆盖面一致） */
const ACTIVE_STATUSES: EmployeeStatus[] = ["probation", "regular", "intern"];

/* ── 左侧员工检索 ── */

const keyword = ref("");
const employees = ref<Employee[]>([]);
const selectedEmployee = ref<Employee | null>(null);
const employeesLoading = ref(false);

const orgTree = ref<OrgTreeNode[]>([]);
const positionOptions = ref<PositionOption[]>([]);

function findOrgNode(nodes: OrgTreeNode[], id: string | null): OrgTreeNode | null {
  if (!id) return null;
  for (const node of nodes) {
    if (node.id === id) return node;
    const child = findOrgNode(node.children ?? [], id);
    if (child) return child;
  }
  return null;
}

function orgNameOf(orgId: string | null): string {
  return findOrgNode(orgTree.value, orgId)?.name ?? "--";
}

function positionNameOf(positionId: string | null): string {
  return positionOptions.value.find((option) => option.id === positionId)?.name ?? "--";
}

async function loadEmployees() {
  employeesLoading.value = true;
  try {
    const res = await listEmployees({ page: 1, page_size: 50, keyword: keyword.value || undefined });
    employees.value = (res.data ?? []).filter((item) =>
      ACTIVE_STATUSES.includes(item.status as EmployeeStatus),
    );
  } catch (error) {
    notifyError(error, getErrorMessage(error, "员工列表加载失败"));
    employees.value = [];
  } finally {
    employeesLoading.value = false;
  }
}

function handleSearch() {
  void loadEmployees();
}

/* ── 右侧方案详情 ── */

const packages = ref<SalaryPackageRecord[]>([]);
const comparison = ref<BandComparison | null>(null);
const detailLoading = ref(false);

const currentPackages = computed(() => packages.value.filter((row) => !row.effective_to));

const COMPARISON_HINTS: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  below: { label: "低于带宽下限", variant: "destructive" },
  within: { label: "带宽区间内", variant: "default" },
  above: { label: "高于带宽上限", variant: "secondary" },
  none: { label: "暂无生效薪带", variant: "outline" },
};

const comparisonHint = computed(() =>
  comparison.value ? COMPARISON_HINTS[comparison.value.position] ?? COMPARISON_HINTS.none : null,
);

async function selectEmployee(employee: Employee) {
  selectedEmployee.value = employee;
  detailLoading.value = true;
  packages.value = [];
  comparison.value = null;
  try {
    const [packageRes, comparisonRes] = await Promise.all([
      listEmployeeSalaryPackages(employee.id),
      getBandComparison(employee.id),
    ]);
    packages.value = packageRes.data ?? [];
    comparison.value = comparisonRes.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "薪酬方案加载失败"));
  } finally {
    detailLoading.value = false;
  }
}

/* ── 调薪弹窗 ── */

const editorOpen = ref(false);

function openEditor() {
  if (!selectedEmployee.value) return;
  editorOpen.value = true;
}

async function handleSaved() {
  if (selectedEmployee.value) await selectEmployee(selectedEmployee.value);
}

onMounted(() => {
  void loadEmployees();
  void getOrgTree()
    .then((res) => {
      orgTree.value = res.data ?? [];
    })
    .catch(() => {
      orgTree.value = [];
    });
  void getPositionOptions()
    .then((res) => {
      positionOptions.value = res.data ?? [];
    })
    .catch(() => {
      positionOptions.value = [];
    });
});
</script>

<template>
  <AppPage title="定薪调薪" description="按员工维度维护薪酬方案：区间版本化 + 薪带对标；生效后当期发薪分段折算">
    <template #actions>
      <Button
        v-if="canWrite"
        :disabled="!selectedEmployee"
        data-testid="open-package-editor"
        @click="openEditor"
      >
        发起调薪
      </Button>
    </template>

    <div class="flex h-full min-h-0 gap-4">
      <!-- 左侧员工检索列表 -->
      <div class="bg-card ring-foreground/10 flex w-72 shrink-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm" data-testid="package-employee-panel">
        <div class="flex shrink-0 items-center gap-2 border-b px-4 py-3">
          <Input
            v-model="keyword"
            class="flex-1"
            placeholder="工号/姓名"
            data-testid="package-employee-keyword"
            @keyup.enter="handleSearch"
          />
          <Button variant="outline" size="sm" data-testid="package-employee-search" @click="handleSearch">搜索</Button>
        </div>
        <ScrollArea class="min-h-0 flex-1">
          <div class="flex flex-col gap-1 p-2">
            <button
              v-for="employee in employees"
              :key="employee.id"
              type="button"
              class="flex flex-col items-start gap-0.5 rounded-lg px-3 py-2 text-left hover:bg-accent"
              :class="selectedEmployee?.id === employee.id ? 'bg-accent' : ''"
              :data-testid="`package-employee-${employee.id}`"
              @click="selectEmployee(employee)"
            >
              <span class="font-medium">{{ employee.name }}（{{ employee.employee_no }}）</span>
              <span class="text-muted-foreground text-xs">
                {{ positionNameOf(employee.position_id) }} · {{ employee.job_level || "未定级" }} ·
                {{ EMPLOYEE_STATUS_LABELS[employee.status] ?? employee.status }}
              </span>
            </button>
            <div v-if="!employees.length && !employeesLoading" class="text-muted-foreground py-8 text-center text-xs">
              暂无在职员工
            </div>
          </div>
        </ScrollArea>
      </div>

      <!-- 右侧方案详情区 -->
      <div class="bg-card ring-foreground/10 flex min-w-0 flex-1 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
        <template v-if="selectedEmployee">
          <!-- 员工信息头 -->
          <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-5 py-4" data-testid="package-employee-header">
            <div>
              <div class="flex items-center gap-2">
                <span class="text-base font-medium">{{ selectedEmployee.name }}</span>
                <Badge variant="outline">{{ selectedEmployee.employee_no }}</Badge>
              </div>
              <div class="text-muted-foreground mt-1 text-xs">
                {{ orgNameOf(selectedEmployee.org_id) }} · {{ positionNameOf(selectedEmployee.position_id) }} ·
                职级 {{ selectedEmployee.job_level || "--" }}
              </div>
            </div>
            <Badge
              v-if="comparisonHint && comparison"
              :variant="comparisonHint.variant"
              :data-testid="`band-hint-${comparison.position}`"
            >
              方案总额 {{ comparison.total.toFixed(2) }} 元/月 · {{ comparisonHint.label }}
            </Badge>
          </div>

          <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
            <div class="flex flex-col gap-5">
              <!-- 当前方案 -->
              <section data-testid="package-current">
                <div class="mb-2 text-xs font-medium">当前方案（元/月）</div>
                <table class="w-full text-left text-xs">
                  <thead class="text-muted-foreground border-b">
                    <tr>
                      <th class="py-2 pr-3 font-medium">薪酬项</th>
                      <th class="py-2 pr-3 font-medium">类别</th>
                      <th class="py-2 pr-3 font-medium">金额</th>
                      <th class="py-2 pr-3 font-medium">生效起</th>
                      <th class="py-2 font-medium">原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in currentPackages" :key="row.id" class="border-b last:border-0">
                      <td class="py-2 pr-3">{{ row.item_name ?? row.item_code }}</td>
                      <td class="py-2 pr-3">{{ row.category ?? "--" }}</td>
                      <td class="py-2 pr-3 font-medium">{{ row.amount.toFixed(2) }}</td>
                      <td class="py-2 pr-3">{{ row.effective_from }}</td>
                      <td class="py-2">{{ SALARY_PACKAGE_REASON_LABELS[row.reason] ?? row.reason }}</td>
                    </tr>
                    <tr v-if="!currentPackages.length">
                      <td colspan="5" class="text-muted-foreground py-4 text-center">暂无生效方案</td>
                    </tr>
                  </tbody>
                </table>
              </section>

              <!-- 定薪历史区间 -->
              <section data-testid="package-history">
                <div class="mb-2 text-xs font-medium">定薪历史区间（版本倒序）</div>
                <table class="w-full text-left text-xs">
                  <thead class="text-muted-foreground border-b">
                    <tr>
                      <th class="py-2 pr-3 font-medium">区间</th>
                      <th class="py-2 pr-3 font-medium">薪酬项</th>
                      <th class="py-2 pr-3 font-medium">金额</th>
                      <th class="py-2 pr-3 font-medium">原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="row in packages" :key="row.id" class="border-b last:border-0">
                      <td class="py-2 pr-3">
                        {{ row.effective_from }} ~ {{ row.effective_to ?? "至今" }}
                      </td>
                      <td class="py-2 pr-3">{{ row.item_name ?? row.item_code }}</td>
                      <td class="py-2 pr-3">{{ row.amount.toFixed(2) }}</td>
                      <td class="py-2">{{ SALARY_PACKAGE_REASON_LABELS[row.reason] ?? row.reason }}</td>
                    </tr>
                    <tr v-if="!packages.length">
                      <td colspan="4" class="text-muted-foreground py-4 text-center">暂无定薪记录</td>
                    </tr>
                  </tbody>
                </table>
              </section>
            </div>
          </div>
        </template>
        <div v-else class="text-muted-foreground flex flex-1 items-center justify-center text-sm" data-testid="package-empty-hint">
          从左侧选择员工查看薪酬方案
        </div>
      </div>
    </div>

    <SalaryPackageEditorModal
      v-model:open="editorOpen"
      :employee-id="selectedEmployee?.id ?? ''"
      :employee-name="selectedEmployee?.name ?? ''"
      :current-packages="currentPackages"
      @saved="handleSaved"
    />
  </AppPage>
</template>
