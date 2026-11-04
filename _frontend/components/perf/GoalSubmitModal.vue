<script setup lang="ts">
/**
 * 目标整批提交弹窗：active 周期选择 + 员工检索选择 + 动态目标行（编码/名称/权重/目标值），
 * 权重合计须恰好 100（前端实时提示缺口，后端整批校验兜底）；
 * 同员工同周期提交会替换未完成目标（重提即重新制定）。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label, Select } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listEmployees } from "@/hr/api/employee";
import { listPerfCycles, submitPerfGoals } from "@/hr/api/perf";
import type { PerfCycleItem, PerfGoalDraftRow } from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const emit = defineEmits<{ saved: [] }>();

interface DraftGoal extends PerfGoalDraftRow {
  key: number;
}

const ALL = "__active_cycle__";

let keySeed = 0;
const cycleId = ref(ALL);
const cycleOptions = ref<{ value: string; label: string }[]>([]);
const employeeKeyword = ref("");
const employeeOptions = ref<{ id: string; label: string }[]>([]);
const selectedEmployee = ref<{ id: string; label: string } | null>(null);
const searching = ref(false);
const goals = ref<DraftGoal[]>([]);
const submitting = ref(false);

const selectedCycle = computed(
  () => cycleOptions.value.find((option) => option.value === cycleId.value) ?? null,
);

const totalWeight = computed(() =>
  goals.value.reduce((sum, goal) => sum + (Number(goal.weight) || 0), 0),
);
const weightGap = computed(() => {
  const gap = Math.round((100 - totalWeight.value) * 100) / 100;
  return gap;
});

watch(open, async (value) => {
  if (!value) return;
  cycleId.value = ALL;
  employeeKeyword.value = "";
  employeeOptions.value = [];
  selectedEmployee.value = null;
  goals.value = [{ key: ++keySeed, code: "", name: "", weight: 0, target_value: "" }];
  try {
    const res = await listPerfCycles({ page: 1, page_size: 100, status: "active" });
    cycleOptions.value = (res.data ?? []).map((cycle: PerfCycleItem) => ({
      value: cycle.id,
      label: cycle.name,
    }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "周期加载失败"));
  }
});

async function searchEmployees() {
  const keyword = employeeKeyword.value.trim();
  if (!keyword) return;
  searching.value = true;
  try {
    const res = await listEmployees({
      page: 1,
      page_size: 20,
      keyword,
    });
    employeeOptions.value = (res.data ?? []).map((employee) => ({
      id: employee.id,
      label: `${employee.name}（${employee.employee_no}）`,
    }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "员工检索失败"));
  } finally {
    searching.value = false;
  }
}

function addRow() {
  goals.value.push({ key: ++keySeed, code: "", name: "", weight: 0, target_value: "" });
}

function removeRow(index: number) {
  goals.value.splice(index, 1);
}

function validate(): string | null {
  if (cycleId.value === ALL) return "请选择考核周期";
  if (!selectedEmployee.value) return "请选择目标负责人";
  if (goals.value.length === 0) return "请至少添加一个目标";
  for (const goal of goals.value) {
    if (!goal.code.trim()) return "请填写目标编码";
    if (!goal.name.trim()) return "请填写目标名称";
    if (!(Number(goal.weight) > 0)) return "目标权重须大于 0";
  }
  if (weightGap.value !== 0) {
    return weightGap.value > 0
      ? `权重合计不足 100，尚缺 ${weightGap.value}`
      : `权重合计超出 100，超出 ${-weightGap.value}`;
  }
  return null;
}

async function handleSubmit() {
  const message = validate();
  if (message || !selectedEmployee.value) {
    if (message) notifyError(new Error(message), message);
    return;
  }
  submitting.value = true;
  try {
    await submitPerfGoals({
      cycle_id: cycleId.value,
      employee_id: selectedEmployee.value.id,
      goals: goals.value.map((goal) => ({
        code: goal.code.trim(),
        name: goal.name.trim(),
        weight: Number(goal.weight),
        target_value: goal.target_value.trim() || undefined,
      })),
    });
    notifySuccess("目标已提交");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "目标提交失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-2xl" data-testid="goal-submit-modal">
      <DialogHeader>
        <DialogTitle>制定目标</DialogTitle>
        <DialogDescription>
          同员工同周期整批提交，权重合计须为 100；重复提交会替换该员工未完成目标
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4 py-2">
        <div class="flex flex-col gap-2">
          <Label>考核周期</Label>
          <Select
            v-model="cycleId"
            :options="[...(cycleOptions.length ? [] : [{ value: ALL, label: '加载中…' }]), ...cycleOptions]"
            :disabled="!cycleOptions.length"
            data-testid="goal-cycle-select"
          />
        </div>
        <div class="flex flex-col gap-2">
          <Label>目标负责人</Label>
          <div v-if="selectedEmployee" class="flex items-center gap-2">
            <Badge variant="secondary" data-testid="goal-employee-badge">
              {{ selectedEmployee.label }}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              data-testid="goal-employee-clear"
              @click="selectedEmployee = null"
            >
              重选
            </Button>
          </div>
          <div v-else class="flex gap-2">
            <Input
              v-model="employeeKeyword"
              class="flex-1"
              placeholder="工号/姓名检索在职员工"
              data-testid="goal-employee-input"
              @keyup.enter="searchEmployees"
            />
            <Button
              variant="outline"
              size="sm"
              :disabled="searching"
              data-testid="goal-employee-search"
              @click="searchEmployees"
            >
              搜索
            </Button>
          </div>
          <div
            v-if="!selectedEmployee && employeeOptions.length"
            class="ring-foreground/10 flex max-h-32 flex-col overflow-auto rounded-md ring-1"
          >
            <button
              v-for="option in employeeOptions"
              :key="option.id"
              type="button"
              class="hover:bg-accent px-3 py-1.5 text-left text-sm"
              :data-testid="`goal-employee-option-${option.id}`"
              @click="selectedEmployee = option"
            >
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <Label>目标列表</Label>
            <Button variant="outline" size="sm" data-testid="goal-add-row" @click="addRow">
              加一行
            </Button>
          </div>
          <div class="ring-foreground/10 overflow-hidden rounded-md ring-1">
            <div class="bg-muted/50 grid grid-cols-[1fr_1.4fr_0.7fr_1.2fr_40px] gap-2 px-3 py-2 text-xs text-muted-foreground">
              <span>编码</span><span>名称</span><span>权重</span><span>目标值</span><span />
            </div>
            <div
              v-for="(goal, index) in goals"
              :key="goal.key"
              class="grid grid-cols-[1fr_1.4fr_0.7fr_1.2fr_40px] items-center gap-2 border-t px-3 py-2"
              :data-testid="`goal-row-${index}`"
            >
              <Input v-model="goal.code" placeholder="G1" data-testid="goal-code" />
              <Input v-model="goal.name" placeholder="目标名称" data-testid="goal-name" />
              <Input
                v-model.number="goal.weight"
                type="number"
                data-testid="goal-weight"
              />
              <Input v-model="goal.target_value" placeholder="如 完成率 ≥ 95%" data-testid="goal-target" />
              <Button
                variant="ghost"
                size="icon-sm"
                :disabled="goals.length <= 1"
                :data-testid="`goal-remove-${index}`"
                @click="removeRow(index)"
              >
                ×
              </Button>
            </div>
          </div>
          <div class="flex items-center justify-between text-xs">
            <span
              :class="weightGap === 0 ? 'text-emerald-600' : 'text-destructive'"
              data-testid="goal-weight-summary"
            >
              权重合计 {{ totalWeight }}
              <template v-if="weightGap > 0">，尚缺 {{ weightGap }}</template>
              <template v-else-if="weightGap < 0">，超出 {{ -weightGap }}</template>
              <template v-else>，已满足</template>
            </span>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="goal-submit-cancel" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="goal-submit" @click="handleSubmit">提交</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
