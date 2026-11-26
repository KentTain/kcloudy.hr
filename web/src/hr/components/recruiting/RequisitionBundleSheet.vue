<script setup lang="ts">
/**
 * 招聘聚合单侧滑（流程测试载体）：查看态展示父（需求字段）- 子（申请明细行）-
 * 孙（行内 Offer 快照）三级；新建/编辑态以同构表单提交聚合载荷（明细按行
 * upsert：带 application_id 更新、不带新建、缺失删除）。
 */
import { computed, ref, watch } from "vue";
import { Pencil, Plus, Trash2 } from "@lucide/vue";
import {
  Badge,
  Button,
  Checkbox,
  DescriptionList,
  Input,
  Label,
  OrganizationSelect,
  Select,
  Textarea,
} from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import {
  createRequisitionBundle,
  getRequisitionBundle,
  updateRequisitionBundle,
} from "@/hr/api/requisitionBundle";
import { getPositionOptions } from "@/hr/api/reference";
import {
  APPLICATION_STAGE_LABELS,
  APPLICATION_STAGE_VARIANTS,
  OFFER_STATUS_LABELS,
  REQUISITION_PRIORITY_LABELS,
  REQUISITION_PRIORITY_OPTIONS,
  REQUISITION_STATUS_LABELS,
  REQUISITION_STATUS_VARIANTS,
  type RequisitionBundleApplication,
  type RequisitionBundleDetail,
  type RequisitionBundlePayload,
  type RequisitionPriority,
} from "@/hr/types/recruiting";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  /** null = 新建态；否则查看/编辑既有聚合单 */
  requisitionId: string | null;
  canWrite: boolean;
  /** 打开即进编辑态（列表行编辑入口；不可编辑时回落查看态） */
  initialEdit?: boolean;
  /** 组织/岗位 ID → 名称解析（列表页同源映射；查看态展示用） */
  orgNameOf?: (orgId: string | null) => string;
  positionNameOf?: (positionId: string | null) => string;
}>();

const emit = defineEmits<{ saved: [] }>();

type SheetMode = "view" | "edit" | "create";

// reka Select 不接受空字符串 value，「不关联岗位」用哨兵值表达
const NO_POSITION = "__none__";

const mode = ref<SheetMode>("view");
const detail = ref<RequisitionBundleDetail | null>(null);
const loading = ref(false);
const submitting = ref(false);
const positionOptions = ref<{ id: string; name: string }[]>([]);

/* ── 表单状态（父字段） ── */

const title = ref("");
const orgIds = ref<string[]>([]);
const positionId = ref(NO_POSITION);
const headcount = ref("1");
const jobLevel = ref("");
const salaryMin = ref("");
const salaryMax = ref("");
const priority = ref<RequisitionPriority>("medium");
const jd = ref("");

/* ── 表单状态（明细行：子字段 + 行内 Offer 孙字段） ── */

interface RowState {
  application_id: string | null;
  candidate_name: string;
  candidate_phone: string;
  candidate_email: string;
  match_score: string;
  offer_enabled: boolean;
  monthly_salary: string;
  sign_on_bonus: string;
  year_end_bonus: string;
  valid_until: string;
}

const rows = ref<RowState[]>([]);

function emptyRow(): RowState {
  return {
    application_id: null,
    candidate_name: "",
    candidate_phone: "",
    candidate_email: "",
    match_score: "",
    offer_enabled: false,
    monthly_salary: "",
    sign_on_bonus: "",
    year_end_bonus: "",
    valid_until: "",
  };
}

const canSubmit = computed(() => props.canWrite && (mode.value === "create" || mode.value === "edit"));
const isClosed = computed(() => detail.value?.status === "closed");

function numberOrNull(value: string): number | null {
  return value === "" ? null : Number(value);
}

function resetForm(source?: RequisitionBundleDetail | null) {
  title.value = source?.title ?? "";
  orgIds.value = source ? [source.org_id] : [];
  positionId.value = source?.position_id ?? NO_POSITION;
  headcount.value = source ? String(source.headcount) : "1";
  jobLevel.value = source?.job_level ?? "";
  salaryMin.value = source?.salary_min === null || source?.salary_min === undefined ? "" : String(source.salary_min);
  salaryMax.value = source?.salary_max === null || source?.salary_max === undefined ? "" : String(source.salary_max);
  priority.value = source?.priority ?? "medium";
  jd.value = source?.jd ?? "";
  rows.value = source
    ? source.applications.map((item) => toRowState(item))
    : [emptyRow()];
}

function toRowState(item: RequisitionBundleApplication): RowState {
  return {
    application_id: item.application_id,
    candidate_name: item.candidate_name,
    candidate_phone: item.candidate_phone ?? "",
    candidate_email: item.candidate_email ?? "",
    match_score: item.match_score === null ? "" : String(item.match_score),
    offer_enabled: item.offer !== null,
    monthly_salary: item.offer ? String(item.offer.monthly_salary) : "",
    sign_on_bonus: item.offer?.sign_on_bonus === null || item.offer?.sign_on_bonus === undefined ? "" : String(item.offer.sign_on_bonus),
    year_end_bonus: item.offer?.year_end_bonus === null || item.offer?.year_end_bonus === undefined ? "" : String(item.offer.year_end_bonus),
    valid_until: item.offer?.valid_until ? item.offer.valid_until.slice(0, 16) : "",
  };
}

function addRow() {
  rows.value.push(emptyRow());
}

function removeRow(index: number) {
  rows.value.splice(index, 1);
}

watch(open, async (value) => {
  if (!value) return;
  detail.value = null;
  rows.value = [];
  if (!props.requisitionId) {
    mode.value = "create";
    resetForm(null);
  } else {
    loading.value = true;
    try {
      const res = await getRequisitionBundle(props.requisitionId);
      detail.value = res.data ?? null;
    } catch (error) {
      notifyError(getErrorMessage(error, "聚合单详情加载失败"));
    } finally {
      loading.value = false;
    }
    const editable = props.canWrite && detail.value !== null && detail.value.status !== "closed";
    if (props.initialEdit && editable) {
      resetForm(detail.value);
      mode.value = "edit";
    } else {
      mode.value = "view";
    }
  }
  if (canSubmit.value) {
    getPositionOptions()
      .then((res) => {
        positionOptions.value = (res.data ?? []).map((p) => ({ id: p.id, name: p.name }));
      })
      .catch(() => {
        positionOptions.value = [];
      });
  }
});

function startEdit() {
  if (!detail.value) return;
  resetForm(detail.value);
  mode.value = "edit";
}

/* ── 提交 ── */

function buildPayload(): RequisitionBundlePayload {
  return {
    title: title.value.trim(),
    org_id: orgIds.value[0] ?? "",
    position_id: positionId.value === NO_POSITION ? null : positionId.value,
    headcount: Number(headcount.value) || 0,
    job_level: jobLevel.value.trim() || null,
    salary_min: numberOrNull(salaryMin.value),
    salary_max: numberOrNull(salaryMax.value),
    priority: priority.value,
    jd: jd.value.trim() || null,
    applications: rows.value.map((row) => ({
      application_id: row.application_id,
      candidate_name: row.candidate_name.trim(),
      candidate_phone: row.candidate_phone.trim() || null,
      candidate_email: row.candidate_email.trim() || null,
      candidate_source_channel: "manual",
      match_score: numberOrNull(row.match_score),
      offer: row.offer_enabled
        ? {
            monthly_salary: Number(row.monthly_salary) || 0,
            sign_on_bonus: numberOrNull(row.sign_on_bonus),
            year_end_bonus: numberOrNull(row.year_end_bonus),
            valid_until: row.valid_until || null,
          }
        : null,
    })),
  };
}

function validatePayload(payload: RequisitionBundlePayload): string | null {
  if (!payload.title) return "请填写职位名称";
  if (!payload.org_id) return "请选择招聘部门";
  if (!(payload.headcount > 0)) return "招聘人数须大于 0";
  if (
    payload.salary_min !== null &&
    payload.salary_max !== null &&
    payload.salary_min > payload.salary_max
  ) {
    return "薪酬区间下限不可高于上限";
  }
  for (const [index, row] of payload.applications.entries()) {
    const label = `明细行 ${index + 1}`;
    if (!row.candidate_name) return `${label}：请填写候选人姓名`;
    if (!row.candidate_phone && !row.candidate_email) {
      return `${label}：手机号与邮箱至少填写一项`;
    }
    if (row.offer && !(row.offer.monthly_salary > 0)) {
      return `${label}：Offer 月薪须大于 0`;
    }
  }
  return null;
}

async function handleSubmit() {
  const payload = buildPayload();
  const problem = validatePayload(payload);
  if (problem) {
    notifyError(problem);
    return;
  }
  submitting.value = true;
  try {
    if (mode.value === "create") {
      await createRequisitionBundle(payload);
      notifySuccess("聚合单已创建");
    } else if (props.requisitionId) {
      await updateRequisitionBundle(props.requisitionId, payload);
      notifySuccess("聚合单已保存");
    }
    emit("saved");
    open.value = false;
  } catch (error) {
    notifyError(getErrorMessage(error, "聚合单保存失败"));
  } finally {
    submitting.value = false;
  }
}

/* ── 查看态展示 ── */

const infoItems = computed(() => {
  const item = detail.value;
  if (!item) return [];
  return [
    { label: "需求编号", value: item.req_no },
    { label: "招聘部门", value: props.orgNameOf ? props.orgNameOf(item.org_id) : item.org_id },
    {
      label: "岗位",
      value: props.positionNameOf ? props.positionNameOf(item.position_id) : (item.position_id ?? "--"),
    },
    { label: "招聘人数", value: String(item.headcount) },
    { label: "要求职级", value: item.job_level ?? "--" },
    {
      label: "薪酬区间",
      value:
        item.salary_min === null && item.salary_max === null
          ? "--"
          : `${item.salary_min ?? ""} ~ ${item.salary_max ?? ""} 元/月`,
    },
  ];
});

function formatDate(value: string | null): string {
  return value ? value.slice(0, 16).replace("T", " ") : "--";
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent
      side="right"
      class="flex w-full flex-col gap-0 overflow-hidden sm:max-w-4xl"
      data-testid="bundle-sheet"
    >
      <SheetHeader class="shrink-0 border-b px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <SheetTitle class="flex items-center gap-2" data-testid="bundle-sheet-title">
              {{ mode === "create" ? "新建聚合单" : (detail?.title ?? "聚合单详情") }}
              <Badge v-if="detail" :variant="REQUISITION_STATUS_VARIANTS[detail.status]">
                {{ REQUISITION_STATUS_LABELS[detail.status] ?? detail.status }}
              </Badge>
            </SheetTitle>
            <SheetDescription class="mt-1">
              {{ mode === "create" ? "父（需求）- 子（申请明细）- 孙（Offer）三级一次提交" : (detail?.req_no ?? "--") }}
              <Badge v-if="detail" variant="outline" class="ml-2">
                {{ REQUISITION_PRIORITY_LABELS[detail.priority] ?? detail.priority }}优先
              </Badge>
            </SheetDescription>
          </div>
          <div v-if="canWrite && mode === 'view' && detail && !isClosed" class="flex shrink-0 gap-2">
            <Button variant="outline" size="sm" data-testid="bundle-edit" @click="startEdit">
              <Pencil class="mr-1 h-4 w-4" />
              编辑
            </Button>
          </div>
        </div>
      </SheetHeader>

      <div class="flex min-h-0 flex-1 flex-col gap-5 overflow-auto px-5 py-4">
        <!-- 加载态 -->
        <p v-if="loading" class="text-muted-foreground text-sm">加载中…</p>

        <!-- 查看态：父信息 + 子明细行 + 行内 Offer 孙对象 -->
        <template v-else-if="mode === 'view' && detail">
          <DescriptionList :items="infoItems" :columns="3" data-testid="bundle-detail-info" />
          <div v-if="detail.jd" class="flex flex-col gap-1.5">
            <p class="text-muted-foreground text-xs font-medium">职位描述（JD）</p>
            <p class="text-sm whitespace-pre-wrap">{{ detail.jd }}</p>
          </div>

          <div class="flex flex-col gap-2">
            <p class="text-muted-foreground text-xs font-medium">
              申请明细（{{ detail.applications.length }} 行）
            </p>
            <p v-if="!detail.applications.length" class="text-muted-foreground text-sm">暂无明细行</p>
            <div
              v-for="(application, index) in detail.applications"
              :key="application.application_id"
              class="flex flex-col gap-3 rounded-md border px-3 py-3"
              :data-testid="`bundle-row-${index}`"
            >
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-medium">{{ application.candidate_name }}</span>
                <Badge :variant="APPLICATION_STAGE_VARIANTS[application.stage]">
                  {{ APPLICATION_STAGE_LABELS[application.stage] ?? application.stage }}
                </Badge>
                <span v-if="application.match_score !== null" class="text-muted-foreground text-xs">
                  匹配分 {{ application.match_score }}
                </span>
                <span class="text-muted-foreground ml-auto text-xs">
                  投递 {{ formatDate(application.apply_time) }}
                </span>
              </div>
              <DescriptionList
                :items="[
                  { label: '手机号', value: application.candidate_phone ?? '--' },
                  { label: '邮箱', value: application.candidate_email ?? '--' },
                  { label: '来源渠道', value: application.candidate_source_channel ?? '--' },
                ]"
                :columns="3"
              />
              <!-- 孙对象：行内 Offer 快照 -->
              <div v-if="application.offer" class="rounded-md bg-muted/40 px-3 py-2" :data-testid="`bundle-offer-${index}`">
                <div class="mb-1 flex items-center gap-2">
                  <p class="text-muted-foreground text-xs font-medium">Offer（孙对象）</p>
                  <Badge variant="secondary">{{ OFFER_STATUS_LABELS[application.offer.status] ?? application.offer.status }}</Badge>
                </div>
                <DescriptionList
                  :items="[
                    { label: '月薪', value: `${application.offer.monthly_salary} 元` },
                    { label: '签约奖', value: application.offer.sign_on_bonus === null ? '--' : `${application.offer.sign_on_bonus} 元` },
                    { label: '年终奖', value: application.offer.year_end_bonus === null ? '--' : `${application.offer.year_end_bonus} 元` },
                    { label: '有效期至', value: formatDate(application.offer.valid_until) },
                  ]"
                  :columns="4"
                />
              </div>
              <p v-else class="text-muted-foreground text-xs">无 Offer（孙对象为空）</p>
            </div>
          </div>
        </template>

        <!-- 新建/编辑态：同构表单 -->
        <template v-else-if="canSubmit">
          <div class="flex flex-col gap-3">
            <p class="text-muted-foreground text-xs font-medium">需求字段（父）</p>
            <div class="grid gap-3 md:grid-cols-2">
              <div class="flex flex-col gap-1">
                <Label for="bundle-title">职位名称 *</Label>
                <Input id="bundle-title" v-model="title" placeholder="如：高级Java工程师" data-testid="bundle-title-input" />
              </div>
              <div class="flex flex-col gap-1">
                <Label>招聘部门 *</Label>
                <OrganizationSelect v-model="orgIds" :multiple="false" placeholder="选择部门" data-testid="bundle-org-select" />
              </div>
              <div class="flex flex-col gap-1">
                <Label for="bundle-headcount">招聘人数 *</Label>
                <Input id="bundle-headcount" v-model="headcount" type="number" min="1" data-testid="bundle-headcount-input" />
              </div>
              <div class="flex flex-col gap-1">
                <Label>岗位</Label>
                <Select v-model="positionId" trigger-class="w-full" :options="[{ value: NO_POSITION, label: '不关联岗位' }, ...positionOptions.map((p) => ({ value: p.id, label: p.name }))]" data-testid="bundle-position-select" />
              </div>
              <div class="flex flex-col gap-1">
                <Label for="bundle-job-level">要求职级</Label>
                <Input id="bundle-job-level" v-model="jobLevel" placeholder="如：P7" />
              </div>
              <div class="flex flex-col gap-1">
                <Label>优先级</Label>
                <Select v-model="priority" trigger-class="w-full" :options="REQUISITION_PRIORITY_OPTIONS" />
              </div>
              <div class="flex flex-col gap-1">
                <Label for="bundle-salary-min">薪酬下限（元/月）</Label>
                <Input id="bundle-salary-min" v-model="salaryMin" type="number" min="0" />
              </div>
              <div class="flex flex-col gap-1">
                <Label for="bundle-salary-max">薪酬上限（元/月）</Label>
                <Input id="bundle-salary-max" v-model="salaryMax" type="number" min="0" />
              </div>
            </div>
            <div class="flex flex-col gap-1">
              <Label for="bundle-jd">职位描述（JD）</Label>
              <Textarea id="bundle-jd" v-model="jd" :rows="3" />
            </div>
          </div>

          <div class="flex flex-col gap-3">
            <div class="flex items-center justify-between">
              <p class="text-muted-foreground text-xs font-medium">申请明细（子，{{ rows.length }} 行）</p>
              <Button variant="outline" size="sm" data-testid="bundle-add-row" @click="addRow">
                <Plus class="mr-1 h-4 w-4" />
                添加明细行
              </Button>
            </div>
            <div
              v-for="(row, index) in rows"
              :key="index"
              class="flex flex-col gap-3 rounded-md border px-3 py-3"
              :data-testid="`bundle-form-row-${index}`"
            >
              <div class="flex items-center justify-between">
                <span class="text-sm font-medium">明细行 {{ index + 1 }}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  class="text-destructive"
                  data-testid="bundle-remove-row"
                  @click="removeRow(index)"
                >
                  <Trash2 class="mr-1 h-4 w-4" />
                  删除行
                </Button>
              </div>
              <div class="grid gap-3 md:grid-cols-2">
                <div class="flex flex-col gap-1">
                  <Label :for="`row-name-${index}`">候选人姓名 *</Label>
                  <Input :id="`row-name-${index}`" v-model="row.candidate_name" />
                </div>
                <div class="flex flex-col gap-1">
                  <Label :for="`row-phone-${index}`">手机号</Label>
                  <Input :id="`row-phone-${index}`" v-model="row.candidate_phone" placeholder="手机号/邮箱至少一项" />
                </div>
                <div class="flex flex-col gap-1">
                  <Label :for="`row-email-${index}`">邮箱</Label>
                  <Input :id="`row-email-${index}`" v-model="row.candidate_email" />
                </div>
                <div class="flex flex-col gap-1">
                  <Label :for="`row-score-${index}`">匹配分</Label>
                  <Input :id="`row-score-${index}`" v-model="row.match_score" type="number" min="0" max="100" />
                </div>
              </div>
              <div class="rounded-md bg-muted/40 px-3 py-2">
                <div class="mb-2 flex items-center gap-2">
                  <Checkbox
                    :id="`row-offer-enabled-${index}`"
                    :model-value="row.offer_enabled"
                    :data-testid="`row-offer-enabled-${index}`"
                    @update:model-value="(checked) => (row.offer_enabled = checked === true)"
                  />
                  <Label :for="`row-offer-enabled-${index}`">发放 Offer（孙对象）</Label>
                </div>
                <div v-if="row.offer_enabled" class="grid gap-3 md:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <Label :for="`row-offer-monthly-${index}`">月薪（元）*</Label>
                    <Input :id="`row-offer-monthly-${index}`" v-model="row.monthly_salary" type="number" min="0" />
                  </div>
                  <div class="flex flex-col gap-1">
                    <Label :for="`row-offer-sign-${index}`">签约奖（元）</Label>
                    <Input :id="`row-offer-sign-${index}`" v-model="row.sign_on_bonus" type="number" min="0" />
                  </div>
                  <div class="flex flex-col gap-1">
                    <Label :for="`row-offer-year-${index}`">年终奖（元）</Label>
                    <Input :id="`row-offer-year-${index}`" v-model="row.year_end_bonus" type="number" min="0" />
                  </div>
                  <div class="flex flex-col gap-1">
                    <Label :for="`row-offer-valid-${index}`">有效期至</Label>
                    <Input :id="`row-offer-valid-${index}`" v-model="row.valid_until" type="datetime-local" />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="flex shrink-0 justify-end gap-2 pb-1">
            <Button variant="outline" @click="open = false" :disabled="submitting">取消</Button>
            <Button data-testid="bundle-submit" :disabled="submitting" @click="handleSubmit">
              {{ submitting ? "提交中…" : "保存" }}
            </Button>
          </div>
        </template>
      </div>
    </SheetContent>
  </Sheet>
</template>
