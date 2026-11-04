<script setup lang="ts">
/**
 * 发薪批次页：批次列表 ⇄ 批次明细页内视图。明细为员工 × 薪酬项矩阵
 * （列由明细行动态聚合），修正仅 draft 态（金额+备注留痕）；确认/发放/取消/
 * 导出按状态与权限出项。明细页不占路由叶（菜单 16 叶契约约束）。
 */
import { computed, onMounted, ref } from "vue";

import { Badge, Button, Input, Select } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { downloadBase64File } from "@/hr/utils/download";

import {
  cancelPayrollRun,
  confirmPayrollRun,
  createPayrollRun,
  exportPayrollRun,
  getPayrollRun,
  listPayrollEntries,
  listPayrollRuns,
  payPayrollRun,
  updatePayrollEntry,
} from "@/hr/api/salary";
import {
  PAYROLL_STATUS_LABELS,
  PAYROLL_STATUS_VARIANTS,
  type PayrollEntry,
  type PayrollRun,
  type PayrollRunStatus,
} from "@/hr/types/salary";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:payroll:write"));
const canConfirm = computed(() => userStore.hasPermission("hr:payroll:confirm"));
const canExport = computed(() => userStore.hasPermission("hr:payroll:export"));

const money = (value: number | null | undefined) =>
  value == null ? "--" : value.toLocaleString("zh-CN", { minimumFractionDigits: 2 });

/* ── 批次列表 ── */

const runs = ref<PayrollRun[]>([]);
const listLoading = ref(false);
const statusFilter = ref("all");

const statusSelectOptions = computed(() => [
  { value: "all", label: "全部状态" },
  ...(Object.entries(PAYROLL_STATUS_LABELS) as [PayrollRunStatus, string][]).map(([value, label]) => ({
    value,
    label,
  })),
]);

async function loadRuns() {
  listLoading.value = true;
  try {
    const res = await listPayrollRuns({
      page: 1,
      page_size: 50,
      status: statusFilter.value === "all" ? undefined : (statusFilter.value as PayrollRunStatus),
    });
    runs.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "发薪批次加载失败"));
    runs.value = [];
  } finally {
    listLoading.value = false;
  }
}

/* ── 创建批次 ── */

const createOpen = ref(false);
const createPeriod = ref("");
const creating = ref(false);

function openCreate() {
  const now = new Date();
  createPeriod.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  createOpen.value = true;
}

async function handleCreate() {
  if (!/^\d{4}-\d{2}$/.test(createPeriod.value.trim())) {
    notifyError(new Error("期间格式为 YYYY-MM"));
    return;
  }
  creating.value = true;
  try {
    const res = await createPayrollRun(createPeriod.value.trim());
    notifySuccess(`批次已创建，试算任务已提交（任务 ID：${res.data?.task_id ?? "--"}）`);
    createOpen.value = false;
    await loadRuns();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "批次创建失败（同期间可能已存在）"));
  } finally {
    creating.value = false;
  }
}

/* ── 批次明细（页内视图） ── */

const viewMode = ref<"list" | "detail">("list");
const detailRun = ref<PayrollRun | null>(null);
const entries = ref<PayrollEntry[]>([]);
const entriesLoading = ref(false);

interface MatrixRow {
  employee_id: string;
  employee_no: string;
  employee_name: string;
  /** item_id → entry */
  cells: Map<string, PayrollEntry>;
  total: number;
}

interface ItemColumn {
  item_id: string;
  item_code: string;
}

const itemColumns = computed<ItemColumn[]>(() => {
  const seen = new Map<string, ItemColumn>();
  for (const entry of entries.value) {
    if (!seen.has(entry.item_id)) seen.set(entry.item_id, { item_id: entry.item_id, item_code: entry.item_code });
  }
  return [...seen.values()];
});

const matrixRows = computed<MatrixRow[]>(() => {
  const byEmployee = new Map<string, MatrixRow>();
  for (const entry of entries.value) {
    let row = byEmployee.get(entry.employee_id);
    if (!row) {
      row = {
        employee_id: entry.employee_id,
        employee_no: entry.employee_no ?? "--",
        employee_name: entry.employee_name ?? "--",
        cells: new Map(),
        total: 0,
      };
      byEmployee.set(entry.employee_id, row);
    }
    row.cells.set(entry.item_id, entry);
    row.total += entry.amount;
  }
  return [...byEmployee.values()];
});

const columnTotals = computed<Map<string, number>>(() => {
  const totals = new Map<string, number>();
  for (const entry of entries.value) {
    totals.set(entry.item_id, (totals.get(entry.item_id) ?? 0) + entry.amount);
  }
  return totals;
});

const grandTotal = computed(() => entries.value.reduce((sum, entry) => sum + entry.amount, 0));

async function openDetail(run: PayrollRun) {
  viewMode.value = "detail";
  entries.value = [];
  try {
    const [runRes, entriesRes] = await Promise.all([
      run.status === "draft" ? Promise.resolve({ data: run }) : getPayrollRun(run.id),
      listPayrollEntries(run.id),
    ]);
    detailRun.value = (runRes.data as PayrollRun) ?? run;
    entries.value = entriesRes.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "批次明细加载失败"));
    detailRun.value = run;
  }
}

function backToList() {
  viewMode.value = "list";
  detailRun.value = null;
  void loadRuns();
}

/* ── 状态操作 ── */

async function handleConfirm() {
  if (!detailRun.value) return;
  if (!(await confirmAction(`确定确认 ${detailRun.value.period} 批次？确认后明细锁定不可修正。`))) return;
  try {
    const res = await confirmPayrollRun(detailRun.value.id);
    detailRun.value = res.data ?? detailRun.value;
    notifySuccess("批次已确认，明细已锁定");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "批次确认失败"));
  }
}

async function handlePay() {
  if (!detailRun.value) return;
  if (
    !(await confirmAction(
      `确定标记 ${detailRun.value.period} 批次已发放？发放后生成个人薪酬单（员工自助可查）。`,
    ))
  ) {
    return;
  }
  try {
    const res = await payPayrollRun(detailRun.value.id);
    detailRun.value = res.data ?? detailRun.value;
    notifySuccess("批次已标记发放，个人薪酬单已生成");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "标记发放失败"));
  }
}

async function handleCancel(run: PayrollRun) {
  if (!(await confirmAction(`确定取消 ${run.period} 批次？该操作写审计且不可恢复。`))) return;
  try {
    await cancelPayrollRun(run.id);
    notifySuccess("批次已取消");
    if (viewMode.value === "detail" && detailRun.value?.id === run.id) {
      detailRun.value = { ...run, status: "cancelled" };
    }
    await loadRuns();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "批次取消失败（已发放批次不可取消）"));
  }
}

async function handleExport() {
  if (!detailRun.value) return;
  try {
    const res = await exportPayrollRun(detailRun.value.id);
    const file = res.data;
    if (!file?.content_base64) {
      notifyError(new Error("代发文件生成失败"));
      return;
    }
    downloadBase64File(file.filename, file.content_base64);
    notifySuccess("标准代发文件已下载（敏感导出已写审计）");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "标准代发文件导出失败"));
  }
}

/* ── 明细修正弹窗 ── */

const editOpen = ref(false);
const editEntry = ref<PayrollEntry | null>(null);
const editAmount = ref(0);
const editNote = ref("");
const editSubmitting = ref(false);

const editable = computed(() => detailRun.value?.status === "draft" && canWrite.value);

function openEntryEdit(entry: PayrollEntry) {
  editEntry.value = entry;
  editAmount.value = entry.amount;
  editNote.value = "";
  editOpen.value = true;
}

onMounted(() => {
  void loadRuns();
});

async function handleEntrySave() {
  if (!editEntry.value || !detailRun.value) return;
  const amountChanged = Number(editAmount.value) !== editEntry.value.amount;
  if (amountChanged && !editNote.value.trim()) {
    notifyError(new Error("金额修改须填写备注（补发/扣减原因）"));
    return;
  }
  editSubmitting.value = true;
  try {
    const res = await updatePayrollEntry(detailRun.value.id, editEntry.value.id, {
      amount: Number(editAmount.value),
      note: editNote.value.trim() || undefined,
    });
    const updated = res.data;
    if (updated) {
      entries.value = entries.value.map((row) => (row.id === updated.id ? updated : row));
    }
    notifySuccess("明细已修正");
    editOpen.value = false;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "明细修正失败（仅草稿态可修正）"));
  } finally {
    editSubmitting.value = false;
  }
}
</script>

<template>
  <AppPage
    :title="viewMode === 'list' ? '发薪批次' : `发薪批次 · ${detailRun?.period ?? ''}`"
    description="月度发薪周期：创建批次异步试算 → 人工修正 → 确认锁定 → 标记发放生成薪酬单"
  >
    <template #actions>
      <Button v-if="viewMode === 'list' && canWrite" data-testid="open-create-run" @click="openCreate">
        创建批次
      </Button>
      <Button v-if="viewMode === 'detail'" variant="outline" data-testid="back-to-list" @click="backToList">
        返回列表
      </Button>
    </template>

    <!-- 批次列表视图 -->
    <div
      v-if="viewMode === 'list'"
      class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm"
    >
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select
          v-model="statusFilter"
          trigger-class="w-32"
          :options="statusSelectOptions"
          data-testid="run-status-filter"
        />
        <Button variant="outline" size="sm" data-testid="run-search" @click="loadRuns">搜索</Button>
      </div>
      <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
        <table class="w-full text-left text-xs" data-testid="run-list-table">
          <thead class="text-muted-foreground border-b">
            <tr>
              <th class="py-2 pr-3 font-medium">期间</th>
              <th class="py-2 pr-3 font-medium">状态</th>
              <th class="py-2 pr-3 font-medium">批次总额（元）</th>
              <th class="py-2 pr-3 font-medium">发放人数</th>
              <th class="py-2 pr-3 font-medium">发薪日</th>
              <th class="py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id" class="border-b last:border-0">
              <td class="py-2 pr-3 font-medium" data-testid="run-period">{{ run.period }}</td>
              <td class="py-2 pr-3">
                <Badge :variant="PAYROLL_STATUS_VARIANTS[run.status]" :data-testid="`run-status-${run.status}`">
                  {{ PAYROLL_STATUS_LABELS[run.status] ?? run.status }}
                </Badge>
              </td>
              <td class="py-2 pr-3">{{ money(run.total_amount) }}</td>
              <td class="py-2 pr-3">{{ run.employee_count ?? "--" }}</td>
              <td class="py-2 pr-3">{{ run.pay_date ?? "--" }}</td>
              <td class="py-2">
                <div class="flex items-center gap-1">
                  <Button variant="ghost" size="sm" :data-testid="`run-detail-${run.id}`" @click="openDetail(run)">
                    进入明细
                  </Button>
                  <Button
                    v-if="canWrite && run.status !== 'paid' && run.status !== 'cancelled'"
                    variant="ghost"
                    size="sm"
                    :data-testid="`run-cancel-${run.id}`"
                    @click="handleCancel(run)"
                  >
                    取消
                  </Button>
                </div>
              </td>
            </tr>
            <tr v-if="!runs.length && !listLoading">
              <td colspan="6" class="text-muted-foreground py-8 text-center" data-testid="run-empty">
                暂无发薪批次
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 批次明细视图 -->
    <div
      v-else
      class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm"
    >
      <!-- 批次信息头 -->
      <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b px-5 py-3" data-testid="run-detail-header">
        <div class="flex items-center gap-3">
          <Badge v-if="detailRun" :variant="PAYROLL_STATUS_VARIANTS[detailRun.status]" :data-testid="`detail-status-${detailRun.status}`">
            {{ PAYROLL_STATUS_LABELS[detailRun?.status ?? "draft"] }}
          </Badge>
          <span class="text-muted-foreground text-xs">
            总额 {{ money(detailRun?.total_amount) }} 元 · 人数 {{ detailRun?.employee_count ?? "--" }} · 发薪日
            {{ detailRun?.pay_date ?? "--" }}
          </span>
        </div>
        <div class="flex items-center gap-2">
          <Button
            v-if="detailRun?.status === 'draft' && canConfirm"
            data-testid="run-confirm"
            @click="handleConfirm"
          >
            确认批次
          </Button>
          <Button
            v-if="detailRun?.status === 'confirmed' && canWrite"
            data-testid="run-pay"
            @click="handlePay"
          >
            标记发放
          </Button>
          <Button
            v-if="canExport && (detailRun?.status === 'confirmed' || detailRun?.status === 'paid')"
            variant="outline"
            data-testid="run-export"
            @click="handleExport"
          >
            导出代发文件
          </Button>
        </div>
      </div>

      <!-- 明细矩阵 -->
      <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
        <table class="w-full text-left text-xs" data-testid="payroll-matrix">
          <thead class="text-muted-foreground border-b">
            <tr>
              <th class="py-2 pr-3 font-medium">员工</th>
              <th v-for="col in itemColumns" :key="col.item_id" class="py-2 pr-3 font-medium">
                {{ col.item_code }}
              </th>
              <th class="py-2 pr-3 font-medium">行小计</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in matrixRows" :key="row.employee_id" class="border-b last:border-0" data-testid="matrix-row">
              <td class="py-2 pr-3 whitespace-nowrap">
                {{ row.employee_name }}（{{ row.employee_no }}）
              </td>
              <td v-for="col in itemColumns" :key="col.item_id" class="py-2 pr-3">
                <button
                  v-if="editable && row.cells.get(col.item_id)"
                  type="button"
                  class="hover:text-primary hover:underline"
                  :data-testid="`matrix-cell-${row.employee_id}-${col.item_id}`"
                  @click="openEntryEdit(row.cells.get(col.item_id)!)"
                >
                  {{ money(row.cells.get(col.item_id)!.amount) }}
                </button>
                <span v-else-if="row.cells.get(col.item_id)">{{ money(row.cells.get(col.item_id)!.amount) }}</span>
                <span v-else class="text-muted-foreground">--</span>
              </td>
              <td class="py-2 pr-3 font-medium">{{ money(row.total) }}</td>
            </tr>
            <tr v-if="matrixRows.length" class="border-t font-medium" data-testid="matrix-footer">
              <td class="py-2 pr-3">列合计</td>
              <td v-for="col in itemColumns" :key="col.item_id" class="py-2 pr-3">
                {{ money(columnTotals.get(col.item_id) ?? 0) }}
              </td>
              <td class="py-2 pr-3">{{ money(grandTotal) }}</td>
            </tr>
            <tr v-if="!matrixRows.length && !entriesLoading">
              <td class="text-muted-foreground py-8 text-center" colspan="99" data-testid="matrix-empty">
                暂无明细（试算任务完成后生成）
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 创建批次弹窗 -->
    <Dialog :open="createOpen" @update:open="createOpen = $event">
      <DialogContent class="sm:max-w-sm" data-testid="create-run-dialog">
        <DialogHeader>
          <DialogTitle>创建发薪批次</DialogTitle>
          <DialogDescription>同期间租户唯一；创建后异步试算生成明细（任务回告）。</DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-1.5">
          <label class="text-sm">期间（YYYY-MM）</label>
          <Input v-model="createPeriod" placeholder="2026-10" data-testid="create-run-period" />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="createOpen = false">取消</Button>
          <Button :disabled="creating" data-testid="create-run-submit" @click="handleCreate">
            {{ creating ? "创建中…" : "创建" }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 明细修正弹窗 -->
    <Dialog :open="editOpen" @update:open="editOpen = $event">
      <DialogContent class="sm:max-w-sm" data-testid="entry-edit-dialog">
        <DialogHeader>
          <DialogTitle>修正明细</DialogTitle>
          <DialogDescription>
            {{ editEntry?.employee_name }} · {{ editEntry?.item_code }}；金额修改须填备注留痕（补发/扣减原因）。
          </DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-1.5">
            <label class="text-sm">金额（元）</label>
            <Input
              :model-value="String(editAmount)"
              type="number"
              data-testid="entry-edit-amount"
              @update:model-value="(v: string) => (editAmount = Number(v) || 0)"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-sm">备注</label>
            <Input v-model="editNote" placeholder="补发/扣减原因" data-testid="entry-edit-note" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="editOpen = false">取消</Button>
          <Button :disabled="editSubmitting" data-testid="entry-edit-submit" @click="handleEntrySave">
            {{ editSubmitting ? "保存中…" : "保存" }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </AppPage>
</template>
