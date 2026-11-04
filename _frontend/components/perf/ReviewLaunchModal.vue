<script setup lang="ts">
/**
 * 发起评估弹窗：scoring 周期选择 + 统一评估人 + 被评人批量圈选（检索逐个加入）。
 * 已存在评估的被评人由后端跳过并在结果中提示 created/skipped。
 */
import { computed, ref, watch } from "vue";

import { Badge, Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label, Select } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { listEmployees } from "@/hr/api/employee";
import { createPerfReviews, listPerfCycles } from "@/hr/api/perf";
import type { PerfCycleItem } from "@/hr/types/perf";

const open = defineModel<boolean>("open", { required: true });

const emit = defineEmits<{ saved: [] }>();

interface PickedEmployee {
  id: string;
  label: string;
}

const ALL = "__scoring_cycle__";

const cycleId = ref(ALL);
const cycleOptions = ref<{ value: string; label: string }[]>([]);
const reviewer = ref<PickedEmployee | null>(null);
const reviewerKeyword = ref("");
const reviewerOptions = ref<PickedEmployee[]>([]);
const targets = ref<PickedEmployee[]>([]);
const targetKeyword = ref("");
const targetOptions = ref<PickedEmployee[]>([]);
const searching = ref<"" | "reviewer" | "target">("");
const submitting = ref(false);

const canSubmit = computed(
  () => cycleId.value !== ALL && reviewer.value && targets.value.length > 0,
);

watch(open, async (value) => {
  if (!value) return;
  cycleId.value = ALL;
  reviewer.value = null;
  reviewerKeyword.value = "";
  reviewerOptions.value = [];
  targets.value = [];
  targetKeyword.value = "";
  targetOptions.value = [];
  try {
    const res = await listPerfCycles({ page: 1, page_size: 100, status: "scoring" });
    cycleOptions.value = (res.data ?? []).map((cycle: PerfCycleItem) => ({
      value: cycle.id,
      label: cycle.name,
    }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "周期加载失败"));
  }
});

async function searchReviewer() {
  const keyword = reviewerKeyword.value.trim();
  if (!keyword) return;
  searching.value = "reviewer";
  try {
    const res = await listEmployees({ page: 1, page_size: 20, keyword });
    reviewerOptions.value = (res.data ?? []).map((employee) => ({
      id: employee.id,
      label: `${employee.name}（${employee.employee_no}）`,
    }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "员工检索失败"));
  } finally {
    searching.value = "";
  }
}

async function searchTarget() {
  const keyword = targetKeyword.value.trim();
  if (!keyword) return;
  searching.value = "target";
  try {
    const res = await listEmployees({ page: 1, page_size: 20, keyword });
    targetOptions.value = (res.data ?? []).map((employee) => ({
      id: employee.id,
      label: `${employee.name}（${employee.employee_no}）`,
    }));
  } catch (error) {
    notifyError(error, getErrorMessage(error, "员工检索失败"));
  } finally {
    searching.value = "";
  }
}

function addTarget(option: PickedEmployee) {
  if (!targets.value.some((item) => item.id === option.id)) {
    targets.value.push(option);
  }
  targetKeyword.value = "";
  targetOptions.value = [];
}

function removeTarget(id: string) {
  targets.value = targets.value.filter((item) => item.id !== id);
}

async function handleSubmit() {
  if (cycleId.value === ALL) {
    notifyError(new Error("请选择考核周期"), "请选择考核周期");
    return;
  }
  if (!reviewer.value) {
    notifyError(new Error("请选择评估人"), "请选择评估人");
    return;
  }
  if (targets.value.length === 0) {
    notifyError(new Error("请添加被评人"), "请添加被评人");
    return;
  }
  submitting.value = true;
  try {
    const res = await createPerfReviews({
      cycle_id: cycleId.value,
      items: targets.value.map((target) => ({
        employee_id: target.id,
        reviewer_employee_id: reviewer.value!.id,
      })),
    });
    const { created, skipped } = res.data ?? { created: 0, skipped: 0 };
    notifySuccess(`已发起 ${created} 条评估${skipped ? `，${skipped} 条已存在跳过` : ""}`);
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "发起评估失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-2xl" data-testid="review-launch-modal">
      <DialogHeader>
        <DialogTitle>发起评估</DialogTitle>
        <DialogDescription>
          仅评分中周期可发起；被评人批量圈选，统一指定评估人；已存在评估的被评人自动跳过
        </DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4 py-2">
        <div class="flex flex-col gap-2">
          <Label>考核周期</Label>
          <Select
            v-model="cycleId"
            :options="[...(cycleOptions.length ? [] : [{ value: ALL, label: '加载中…' }]), ...cycleOptions]"
            :disabled="!cycleOptions.length"
            data-testid="review-launch-cycle"
          />
        </div>

        <div class="flex flex-col gap-2">
          <Label>评估人</Label>
          <div v-if="reviewer" class="flex items-center gap-2">
            <Badge variant="secondary" data-testid="review-launch-reviewer-badge">
              {{ reviewer.label }}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              data-testid="review-launch-reviewer-clear"
              @click="reviewer = null"
            >
              重选
            </Button>
          </div>
          <template v-else>
            <div class="flex gap-2">
              <Input
                v-model="reviewerKeyword"
                class="flex-1"
                placeholder="工号/姓名检索评估人"
                data-testid="review-launch-reviewer-input"
                @keyup.enter="searchReviewer"
              />
              <Button
                variant="outline"
                size="sm"
                :disabled="searching === 'reviewer'"
                data-testid="review-launch-reviewer-search"
                @click="searchReviewer"
              >
                搜索
              </Button>
            </div>
            <div
              v-if="reviewerOptions.length"
              class="ring-foreground/10 flex max-h-32 flex-col overflow-auto rounded-md ring-1"
            >
              <button
                v-for="option in reviewerOptions"
                :key="option.id"
                type="button"
                class="hover:bg-accent px-3 py-1.5 text-left text-sm"
                :data-testid="`review-launch-reviewer-option-${option.id}`"
                @click="reviewer = option"
              >
                {{ option.label }}
              </button>
            </div>
          </template>
        </div>

        <div class="flex flex-col gap-2">
          <div class="flex items-center justify-between">
            <Label>被评人（{{ targets.length }}）</Label>
          </div>
          <div v-if="targets.length" class="flex flex-wrap gap-2">
            <Badge
              v-for="target in targets"
              :key="target.id"
              variant="outline"
              :data-testid="`review-launch-target-${target.id}`"
            >
              {{ target.label }}
              <button
                type="button"
                class="text-muted-foreground hover:text-foreground"
                :data-testid="`review-launch-target-remove-${target.id}`"
                @click="removeTarget(target.id)"
              >
                ×
              </button>
            </Badge>
          </div>
          <div class="flex gap-2">
            <Input
              v-model="targetKeyword"
              class="flex-1"
              placeholder="工号/姓名检索在职员工"
              data-testid="review-launch-target-input"
              @keyup.enter="searchTarget"
            />
            <Button
              variant="outline"
              size="sm"
              :disabled="searching === 'target'"
              data-testid="review-launch-target-search"
              @click="searchTarget"
            >
              搜索
            </Button>
          </div>
          <div
            v-if="targetOptions.length"
            class="ring-foreground/10 flex max-h-32 flex-col overflow-auto rounded-md ring-1"
          >
            <button
              v-for="option in targetOptions"
              :key="option.id"
              type="button"
              class="hover:bg-accent px-3 py-1.5 text-left text-sm"
              :data-testid="`review-launch-target-option-${option.id}`"
              @click="addTarget(option)"
            >
              {{ option.label }}
            </button>
          </div>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" data-testid="review-launch-cancel" @click="open = false">取消</Button>
        <Button :disabled="!canSubmit || submitting" data-testid="review-launch-submit" @click="handleSubmit">
          发起
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
