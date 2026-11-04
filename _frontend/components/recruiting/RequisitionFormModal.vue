<script setup lang="ts">
/**
 * 招聘需求创建弹窗（三步：岗位信息 → 任职要求 → 预算渠道）。
 * channels 非空提交后立即发布；外部渠道按渠道管理凭证状态出项（拉取失败降级仅站内）。
 */
import { computed, ref, watch } from "vue";

import { Button } from "@/components";
import { Checkbox } from "@/components";
import { Input, Select, Textarea } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";
import { OrganizationSelect } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { createRequisition, listChannels } from "@/hr/api/recruiting";
import { getPositionOptions } from "@/hr/api/reference";
import {
  CHANNEL_LABELS,
  INTERNAL_CHANNEL,
  REQUISITION_PRIORITY_OPTIONS,
  type ChannelCard,
  type RecruitingChannel,
  type RequisitionPriority,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const emit = defineEmits<{ saved: [] }>();

const STEPS = ["岗位信息", "任职要求", "预算渠道"] as const;

// reka Select 不接受空字符串 value，「不关联岗位」用哨兵值表达
const NO_POSITION = "__none__";

const submitting = ref(false);
const step = ref(0);

/* Step1 岗位信息 */
const title = ref("");
const orgIds = ref<string[]>([]);
const positionId = ref(NO_POSITION);
const headcountInput = ref("1");

/* Step2 任职要求 */
const jobLevel = ref("");
const jd = ref("");

/* Step3 预算渠道 */
const salaryMinInput = ref("");
const salaryMaxInput = ref("");
const priority = ref<RequisitionPriority>("medium");
const selectedChannels = ref<RecruitingChannel[]>([]);
const channelCards = ref<ChannelCard[]>([]);
const channelsLoaded = ref(false);

const positionOptions = ref<{ id: string; name: string }[]>([]);

function toggleChannel(channel: RecruitingChannel, checked: boolean) {
  if (checked) {
    if (!selectedChannels.value.includes(channel)) selectedChannels.value.push(channel);
  } else {
    selectedChannels.value = selectedChannels.value.filter((item) => item !== channel);
  }
}

const channelOptions = computed(() => {
  const cards = new Map(channelCards.value.map((card) => [card.channel, card]));
  return (Object.keys(CHANNEL_LABELS) as RecruitingChannel[]).map((channel) => {
    const card = cards.get(channel);
    // 内部渠道恒可选；外部渠道需渠道管理已配置凭证（配置加载失败时仅出内部渠道）
    const available = channel === INTERNAL_CHANNEL || Boolean(card?.configured);
    return { channel, label: CHANNEL_LABELS[channel], available };
  });
});

watch(open, async (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  step.value = 0;
  title.value = "";
  orgIds.value = [];
  positionId.value = NO_POSITION;
  headcountInput.value = "1";
  jobLevel.value = "";
  jd.value = "";
  salaryMinInput.value = "";
  salaryMaxInput.value = "";
  priority.value = "medium";
  selectedChannels.value = [INTERNAL_CHANNEL];
  try {
    const [positionRes, channelRes] = await Promise.allSettled([
      getPositionOptions(),
      listChannels(),
    ]);
    positionOptions.value = (positionRes.value?.data ?? []).map((p) => ({ id: p.id, name: p.name }));
    channelCards.value = channelRes.value?.data ?? [];
  } catch {
    positionOptions.value = [];
    channelCards.value = [];
  } finally {
    channelsLoaded.value = true;
  }
}, { immediate: true });

function validateStep(current: number): string | null {
  if (current === 0) {
    if (!title.value.trim()) return "请填写职位名称";
    if (!orgIds.value[0]) return "请选择招聘部门";
    const headcount = Number(headcountInput.value);
    if (!Number.isInteger(headcount) || headcount <= 0) return "招聘人数须为正整数";
  }
  if (current === 2) {
    const min = salaryMinInput.value.trim() === "" ? null : Number(salaryMinInput.value);
    const max = salaryMaxInput.value.trim() === "" ? null : Number(salaryMaxInput.value);
    if (min !== null && (!Number.isFinite(min) || min < 0)) return "薪酬下限须为非负数字";
    if (max !== null && (!Number.isFinite(max) || max < 0)) return "薪酬上限须为非负数字";
    if (min !== null && max !== null && min > max) return "薪酬下限不可高于上限";
    if (!selectedChannels.value.length) return "请至少选择一个发布渠道";
  }
  return null;
}

function handleNext() {
  const error = validateStep(step.value);
  if (error) {
    notifyError(new Error(error));
    return;
  }
  step.value += 1;
}

function handlePrev() {
  step.value = Math.max(0, step.value - 1);
}

async function handleSubmit() {
  const error = validateStep(2);
  if (error) {
    notifyError(new Error(error));
    return;
  }
  submitting.value = true;
  try {
    const headcount = Number(headcountInput.value);
    const min = salaryMinInput.value.trim() === "" ? undefined : Number(salaryMinInput.value);
    const max = salaryMaxInput.value.trim() === "" ? undefined : Number(salaryMaxInput.value);
    await createRequisition({
      title: title.value.trim(),
      org_id: orgIds.value[0],
      position_id: positionId.value === NO_POSITION ? undefined : positionId.value,
      headcount,
      job_level: jobLevel.value.trim() || undefined,
      salary_min: min,
      salary_max: max,
      priority: priority.value,
      jd: jd.value.trim() || undefined,
      channels: selectedChannels.value,
    });
    notifySuccess(
      selectedChannels.value.some((channel) => channel !== INTERNAL_CHANNEL)
        ? "需求已创建，外部渠道发布中"
        : "需求已创建",
    );
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "需求创建失败"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-lg" data-testid="requisition-form-dialog">
      <DialogHeader>
        <DialogTitle>新建招聘需求</DialogTitle>
        <DialogDescription>需求编号自动生成；勾选外部渠道时创建后立即发布。</DialogDescription>
      </DialogHeader>

      <!-- 步骤条 -->
      <div class="flex items-center gap-2" data-testid="requisition-steps">
        <template v-for="(label, index) in STEPS" :key="label">
          <div
            class="flex items-center gap-1.5 text-xs"
            :class="index === step ? 'text-primary font-medium' : 'text-muted-foreground'"
          >
            <span
              class="flex size-5 items-center justify-center rounded-full border text-[10px]"
              :class="index <= step ? 'border-primary text-primary' : ''"
            >
              {{ index + 1 }}
            </span>
            {{ label }}
          </div>
          <div v-if="index < STEPS.length - 1" class="bg-border h-px w-6" />
        </template>
      </div>

      <!-- Step1 岗位信息 -->
      <div v-if="step === 0" class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>职位名称 *</Label>
          <Input v-model="title" placeholder="如 后端工程师（支付方向）" data-testid="req-title-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>招聘部门 *</Label>
          <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="选择部门" />
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>岗位</Label>
            <Select
              v-model="positionId"
              trigger-class="w-full"
              :options="[{ value: NO_POSITION, label: '不关联岗位' }, ...positionOptions.map((p) => ({ value: p.id, label: p.name }))]"
              data-testid="req-position-select"
            />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>招聘人数 *</Label>
            <Input v-model="headcountInput" type="number" min="1" data-testid="req-headcount-input" />
          </div>
        </div>
      </div>

      <!-- Step2 任职要求 -->
      <div v-else-if="step === 1" class="flex flex-col gap-4">
        <div class="flex flex-col gap-1.5">
          <Label>要求职级</Label>
          <Input v-model="jobLevel" placeholder="如 P6 / M2" data-testid="req-job-level-input" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>职位描述（JD）</Label>
          <Textarea v-model="jd" :rows="6" placeholder="职责与任职要求" data-testid="req-jd-input" />
        </div>
      </div>

      <!-- Step3 预算渠道 -->
      <div v-else class="flex flex-col gap-4">
        <div class="grid grid-cols-2 gap-4">
          <div class="flex flex-col gap-1.5">
            <Label>薪酬下限（元/月）</Label>
            <Input v-model="salaryMinInput" type="number" min="0" data-testid="req-salary-min-input" />
          </div>
          <div class="flex flex-col gap-1.5">
            <Label>薪酬上限（元/月）</Label>
            <Input v-model="salaryMaxInput" type="number" min="0" data-testid="req-salary-max-input" />
          </div>
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>优先级</Label>
          <Select v-model="priority" :options="REQUISITION_PRIORITY_OPTIONS" data-testid="req-priority-select" />
        </div>
        <div class="flex flex-col gap-1.5">
          <Label>发布渠道</Label>
          <div class="flex flex-col gap-2" data-testid="req-channel-group">
            <label
              v-for="option in channelOptions"
              :key="option.channel"
              class="flex items-center gap-2 text-sm"
              :class="option.available ? '' : 'text-muted-foreground opacity-60'"
            >
              <Checkbox
                :model-value="selectedChannels.includes(option.channel)"
                :disabled="!option.available"
                :data-testid="`req-channel-${option.channel}`"
                @update:model-value="toggleChannel(option.channel, $event === true)"
              />
              {{ option.label }}
              <span v-if="!option.available" class="text-muted-foreground text-xs">（未配置凭证）</span>
            </label>
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button v-if="step > 0" variant="outline" data-testid="req-step-prev" @click="handlePrev">上一步</Button>
        <Button v-if="step < STEPS.length - 1" data-testid="req-step-next" @click="handleNext">下一步</Button>
        <Button v-else :disabled="submitting" data-testid="req-submit" @click="handleSubmit">
          {{ submitting ? "提交中…" : "提交" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
