<script setup lang="ts">
/**
 * 员工详情抽屉：八信息域 Tabs（概览/任职/个人/联系/合同/附件/薪酬/扩展属性）
 * + 底部员工切换条 + 头部异动/更多操作。
 * Tab 懒加载（loaded 标记）+ 自增 seq 竞态守卫（切换员工时丢弃在途响应）。
 */
import { MoreHorizontalIcon } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import {
  Badge,
  buildSettingFormSpec,
  Button,
  DescriptionList,
  type DescriptionItem,
  FileDropzone,
  type DynamicFormField,
  type DynamicFormDataType,
} from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Label } from "@/components";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components";
import { JsonRender } from "@/components/json-render";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import {
  deleteEmployee,
  getEmployeeAttributes,
  getEmployeeDetail,
  getSensitiveView,
  listEmployeeChanges,
  openAccount,
  saveEmployeeAttributes,
} from "@/hr/api/employee";
import {
  deleteAttachment,
  deleteContract,
  getAttachmentDownloadUrl,
  listEmployeeAttachments,
  listEmployeeContracts,
  terminateContract,
  uploadEmployeeAttachment,
} from "@/hr/api/contract";
import { listFieldGroups } from "@/hr/api/field";
import { getOrgTree, getPositionOptions, getBandComparison, listEmployeeSalaryPackages } from "@/hr/api/reference";
import EmployeeChangeModal from "@/hr/components/employee/EmployeeChangeModal.vue";
import EmployeeContractModal from "@/hr/components/employee/EmployeeContractModal.vue";
import EmployeeFormModal from "@/hr/components/employee/EmployeeFormModal.vue";
import EmployeeSwitchBar from "@/hr/components/employee/EmployeeSwitchBar.vue";
import FieldDefinitionManager from "@/hr/components/employee/FieldDefinitionManager.vue";
import {
  ATTACHMENT_DOC_TYPES,
  ATTRIBUTE_DATA_TYPE_LABELS,
  CHANGE_TYPE_LABELS,
  CONTRACT_STATUS_LABELS,
  EMPLOYEE_STATUS_LABELS,
  EMPLOYEE_STATUS_VARIANTS,
  SALARY_REASON_LABELS,
  contractTypeLabel,
  isActiveEmployee,
  type AccountOpenResult,
  type Attachment,
  type AttributeValueItem,
  type BandComparison,
  type ChangeRecord,
  type ChangeType,
  type Contract,
  type Employee,
  type EmployeeDetail,
  type FieldGroup,
  type SensitiveView,
  type SalaryPackageRecord,
} from "@/hr/types/employee";

/** 后端预置属性组（TenantInitializer seed 同源；custom/自建组进「扩展属性」Tab） */
const PRESET_GROUP_CODES = ["basic", "education", "contacts", "work", "custom"];

const BAND_POSITION_META: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline" }> = {
  below: { label: "低于带宽", variant: "secondary" },
  within: { label: "带宽内", variant: "default" },
  above: { label: "高于带宽", variant: "destructive" },
  none: { label: "未配置薪带", variant: "outline" },
};

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  employeeId: string | null;
  /** 切换条数据源（当前列表页数据） */
  employees: Employee[];
}>();

const emit = defineEmits<{
  /** 任一变更操作后通知列表刷新（重拉列表+统计） */
  refresh: [];
  /** 切换条跳转 */
  switch: [employee: Employee];
}>();

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:employee:write"));
const canSensitive = computed(() => userStore.hasPermission("hr:employee:sensitive"));
const canDelete = computed(() => userStore.hasPermission("hr:employee:delete"));
const canSalaryRead = computed(() => userStore.hasPermission("hr:salary_package:read"));
const canContractRead = computed(() => userStore.hasPermission("hr:contract:read"));
const canContractWrite = computed(() => userStore.hasPermission("hr:contract:write"));
const canAttachmentRead = computed(() => userStore.hasPermission("hr:attachment:read"));
const canAttachmentWrite = computed(() => userStore.hasPermission("hr:attachment:write"));

let seq = 0;

const loading = ref(false);
const detail = ref<EmployeeDetail | null>(null);
const activeTab = ref("overview");
const loadedTabs = ref(new Set<string>());

// 各 Tab 数据（懒加载填充）
const changes = ref<ChangeRecord[]>([]);
const attributes = ref<AttributeValueItem[]>([]);
const groups = ref<FieldGroup[]>([]);
const contracts = ref<Contract[]>([]);
const attachments = ref<Attachment[]>([]);
const salaryPackages = ref<SalaryPackageRecord[]>([]);
const bandComparison = ref<BandComparison | null>(null);
const sensitive = ref<SensitiveView | null>(null);

// 扩展属性编辑
const customFormRef = ref<InstanceType<typeof JsonRender>>();
const customBuild = ref(buildSettingFormSpec([]));

// 组织/岗位名称解析（响应仅含 ID）
const orgNameMap = ref<Record<string, string>>({});
const positionNameMap = ref<Record<string, string>>({});

// 弹窗编排
const accountResult = ref<AccountOpenResult | null>(null);
const changeModalOpen = ref(false);
const changeInitialType = ref<ChangeType>("probate");
const contractModalOpen = ref(false);
const renewFrom = ref<Contract | null>(null);
const formModalOpen = ref(false);
const fieldManagerOpen = ref(false);
const uploadingDocType = ref("");

const tabs = computed(() => [
  { value: "overview", label: "概览" },
  { value: "job", label: "任职信息" },
  { value: "personal", label: "个人信息" },
  { value: "contact", label: "联系信息" },
  ...(canContractRead.value ? [{ value: "contracts", label: "合同信息" }] : []),
  ...(canAttachmentRead.value ? [{ value: "attachments", label: "材料附件" }] : []),
  ...(canSalaryRead.value ? [{ value: "salary", label: "薪酬信息" }] : []),
  { value: "custom", label: "扩展属性" },
]);

const orgLabel = computed(() => (detail.value?.org_id ? orgNameMap.value[detail.value.org_id] ?? "--" : "--"));
const positionLabel = computed(() =>
  detail.value?.position_id ? positionNameMap.value[detail.value.position_id] ?? "--" : "--",
);

function groupCodeOf(groupId: string): string {
  return groups.value.find((group) => group.id === groupId)?.code ?? "";
}

/* ── 加载编排 ── */

watch(
  () => [open.value, props.employeeId] as const,
  ([openVal]) => {
    if (openVal && props.employeeId) void initLoad();
  },
  { immediate: true },
);

watch(activeTab, (tab) => {
  if (open.value) void loadTab(tab);
});

async function initLoad() {
  seq += 1;
  const s = seq;
  detail.value = null;
  changes.value = [];
  attributes.value = [];
  groups.value = [];
  contracts.value = [];
  attachments.value = [];
  salaryPackages.value = [];
  bandComparison.value = null;
  sensitive.value = null;
  loadedTabs.value = new Set();
  activeTab.value = "overview";
  loading.value = true;
  try {
    const res = await getEmployeeDetail(props.employeeId as string);
    if (s !== seq) return;
    detail.value = res.data ?? null;
  } catch (error) {
    if (s !== seq) return;
    notifyError(error, getErrorMessage(error, "员工详情加载失败"));
  } finally {
    if (s === seq) loading.value = false;
  }
  await Promise.all([loadTab("overview"), resolveReferenceNames()]);
}

/** 组织/岗位名称解析失败降级 "--"（如 lineManager 无 hr:position:read） */
async function resolveReferenceNames() {
  const s = seq;
  try {
    const res = await getOrgTree();
    if (s !== seq) return;
    const map: Record<string, string> = {};
    const walk = (nodes: { id: string; name: string; children?: unknown[] }[] | undefined) => {
      for (const node of nodes ?? []) {
        map[node.id] = node.name;
        walk(node.children as typeof nodes);
      }
    };
    walk(res.data ?? []);
    orgNameMap.value = map;
  } catch {
    orgNameMap.value = {};
  }
  try {
    const res = await getPositionOptions();
    if (s !== seq) return;
    positionNameMap.value = Object.fromEntries((res.data ?? []).map((p) => [p.id, p.name]));
  } catch {
    positionNameMap.value = {};
  }
}

async function loadTab(tab: string) {
  const employeeId = props.employeeId;
  if (!open.value || !employeeId || !detail.value || loadedTabs.value.has(tab)) return;
  loadedTabs.value.add(tab);
  const s = ++seq;
  try {
    switch (tab) {
      case "overview": {
        const res = await listEmployeeChanges(employeeId, { page: 1, page_size: 50 });
        if (s !== seq) return;
        changes.value = (res.data ?? []).slice().reverse();
        break;
      }
      case "job":
      case "personal":
      case "contact": {
        const [groupsRes, attrsRes] = await Promise.all([
          listFieldGroups(),
          getEmployeeAttributes(employeeId),
        ]);
        if (s !== seq) return;
        groups.value = groupsRes.data ?? [];
        attributes.value = attrsRes.data ?? [];
        break;
      }
      case "contracts": {
        const res = await listEmployeeContracts(employeeId);
        if (s !== seq) return;
        contracts.value = res.data ?? [];
        break;
      }
      case "attachments": {
        const res = await listEmployeeAttachments(employeeId);
        if (s !== seq) return;
        attachments.value = res.data ?? [];
        break;
      }
      case "salary": {
        const [pkgRes, bandRes] = await Promise.all([
          listEmployeeSalaryPackages(employeeId),
          getBandComparison(employeeId).catch(() => null),
        ]);
        if (s !== seq) return;
        salaryPackages.value = pkgRes.data ?? [];
        bandComparison.value = bandRes?.data ?? null;
        break;
      }
      case "custom": {
        const [groupsRes, attrsRes] = await Promise.all([
          listFieldGroups(),
          getEmployeeAttributes(employeeId),
        ]);
        if (s !== seq) return;
        groups.value = groupsRes.data ?? [];
        attributes.value = attrsRes.data ?? [];
        rebuildCustomForm();
        break;
      }
    }
  } catch (error) {
    if (s === seq) notifyError(error, getErrorMessage(error, "数据加载失败"));
  }
}

/** 变更操作后整体重载（详情 + 当前 Tab 数据） */
async function reload() {
  const current = activeTab.value;
  await initLoad();
  activeTab.value = current;
  if (current !== "overview") await loadTab(current);
}

/* ── 概览 ── */

function yearsSince(date: string | null): number | null {
  if (!date) return null;
  const start = new Date(date).getTime();
  if (Number.isNaN(start)) return null;
  return Math.floor((Date.now() - start) / (365.25 * 24 * 3600 * 1000));
}

const overviewItems = computed<DescriptionItem[]>(() => {
  const d = detail.value;
  if (!d) return [];
  return [
    { label: "性别", value: d.gender === "male" ? "男" : d.gender === "female" ? "女" : "--" },
    { label: "年龄", value: d.birth_date ? `${yearsSince(d.birth_date)} 岁` : "--" },
    { label: "司龄", value: `${yearsSince(d.hire_date) ?? 0} 年` },
    { label: "证件号", value: d.id_card_masked ?? "--" },
    { label: "入职日期", value: d.hire_date },
    { label: "转正日期", value: d.regular_date ?? "--" },
    { label: "离职日期", value: d.offboard_date ?? "--" },
    { label: "银行卡号", value: d.bank_card_masked ?? "--" },
    { label: "开户行", value: d.bank_name ?? "--" },
  ];
});

function changeDetailLines(record: ChangeRecord): string[] {
  const lines: string[] = [];
  const after = record.after_data ?? {};
  const labelMap: Record<string, string> = {
    org_id: "组织",
    position_id: "岗位",
    job_level: "职级",
    reason: "原因",
  };
  for (const [key, value] of Object.entries(after)) {
    if (value == null || value === "") continue;
    if (key === "salary_items" && Array.isArray(value)) {
      lines.push(`薪酬项调整 ${value.length} 项`);
      continue;
    }
    const label = labelMap[key];
    if (label) lines.push(`${label}: ${typeof value === "string" ? value : String(value)}`);
  }
  return lines;
}

/* ── 任职/个人/联系（EAV 只读）── */

function attributeItemsByGroups(codes: string[]): AttributeValueItem[] {
  const codeSet = new Set(codes);
  return attributes.value
    .filter((item) => codeSet.has(groupCodeOf(item.group_id)))
    .sort((a, b) => a.sort - b.sort);
}

const jobItems = computed(() => attributeItemsByGroups(["work"]));
const personalItems = computed(() => attributeItemsByGroups(["basic", "education"]));
const contactItems = computed(() => attributeItemsByGroups(["contacts"]));

function displayValue(item: AttributeValueItem): string {
  if (item.value == null) return "--";
  if (item.data_type === "boolean") return item.value ? "是" : "否";
  if (item.data_type === "json") return "";
  if (item.data_type === "date_time") return String(item.value).slice(0, 10);
  return String(item.value);
}

function jsonRecords(item: AttributeValueItem): Record<string, unknown>[] | null {
  if (item.data_type !== "json" || item.value == null || !Array.isArray(item.value)) return null;
  return item.value.filter((entry) => entry && typeof entry === "object") as Record<string, unknown>[];
}

function jsonScalar(item: AttributeValueItem): string | null {
  if (item.data_type !== "json" || item.value == null || Array.isArray(item.value)) return null;
  return JSON.stringify(item.value, null, 2);
}

/* ── 敏感明文 ── */

async function showSensitive() {
  if (!props.employeeId) return;
  try {
    const res = await getSensitiveView(props.employeeId);
    sensitive.value = res.data ?? null;
    notifySuccess("已查看明文（操作已记录审计）");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "明文查看失败"));
  }
}

/* ── 头部操作 ── */

function openChange(type: ChangeType) {
  changeInitialType.value = type;
  changeModalOpen.value = true;
}

async function openAccountFor() {
  if (!props.employeeId) return;
  try {
    const res = await openAccount(props.employeeId);
    accountResult.value = res.data ?? null;
  } catch (error) {
    notifyError(error, getErrorMessage(error, "账号开通失败"));
  }
}

async function deleteEmployeeFor() {
  if (!props.employeeId || !detail.value) return;
  if (!(await confirmAction(`确定删除员工「${detail.value.name}」？该操作不可恢复。`))) return;
  try {
    await deleteEmployee(props.employeeId);
    notifySuccess("员工已删除");
    open.value = false;
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}

async function copyAccountResult() {
  if (!accountResult.value) return;
  try {
    await navigator.clipboard.writeText(
      `账号：${accountResult.value.username}\n初始密码：${accountResult.value.initial_password}`,
    );
    notifySuccess("已复制账号与初始密码");
  } catch {
    notifyError(new Error("复制失败，请手动复制"));
  }
}

/* ── 合同操作 ── */

async function terminateContractFor(contract: Contract) {
  if (!(await confirmAction(`确定终止合同「${contract.contract_no}」？`))) return;
  try {
    await terminateContract(contract.id);
    notifySuccess("合同已终止");
    await reload();
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "终止失败"));
  }
}

async function removeContract(contract: Contract) {
  if (!(await confirmAction(`确定删除合同「${contract.contract_no}」？`))) return;
  try {
    await deleteContract(contract.id);
    notifySuccess("合同已删除");
    await reload();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}

/* ── 附件操作 ── */

function attachmentsByDocType(docType: string): Attachment[] {
  return attachments.value.filter((item) => item.doc_type === docType);
}

async function uploadAttachment(docType: string, files: File[]) {
  const file = files[0];
  if (!file || !props.employeeId) return;
  uploadingDocType.value = docType;
  try {
    await uploadEmployeeAttachment(props.employeeId, docType, file);
    notifySuccess("附件已上传");
    loadedTabs.value.delete("attachments");
    await loadTab("attachments");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "附件上传失败"));
  } finally {
    uploadingDocType.value = "";
  }
}

async function downloadAttachment(attachment: Attachment) {
  try {
    const res = await getAttachmentDownloadUrl(attachment.id);
    if (res.data?.url) window.open(res.data.url, "_blank");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "下载链接获取失败"));
  }
}

async function removeAttachment(attachment: Attachment) {
  if (!(await confirmAction(`确定删除附件「${attachment.file_name}」？`))) return;
  try {
    await deleteAttachment(attachment.id);
    notifySuccess("附件已删除");
    attachments.value = attachments.value.filter((item) => item.id !== attachment.id);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}

/* ── 扩展属性编辑 ── */

const customItems = computed(() => {
  const preset = new Set(PRESET_GROUP_CODES);
  return attributes.value
    .filter((item) => {
      const code = groupCodeOf(item.group_id);
      return code === "custom" || !preset.has(code);
    })
    .sort((a, b) => a.sort - b.sort);
});

function rebuildCustomForm() {
  const fields: DynamicFormField[] = customItems.value.map((item) => ({
    name: item.definition_id,
    display_name: item.name,
    data_type: item.data_type as DynamicFormDataType,
    value: item.raw_value,
    ext_data: item.ext_data ?? undefined,
    is_require: item.is_require,
    can_edit: item.can_edit,
    index: item.sort,
  }));
  customBuild.value = buildSettingFormSpec(fields);
}

async function saveCustomAttributes() {
  if (!props.employeeId) return;
  const form = customFormRef.value;
  if (!form) return;
  if (!form.validate()) return;
  try {
    const values = form.getValues();
    await saveEmployeeAttributes(props.employeeId, values);
    notifySuccess("扩展属性已保存");
    loadedTabs.value.delete("custom");
    await loadTab("custom");
    emit("refresh");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "保存失败"));
  }
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent
      side="right"
      class="flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl"
      data-testid="employee-detail-drawer"
    >
      <SheetTitle class="sr-only">员工详情</SheetTitle>
      <SheetDescription class="sr-only">员工档案八信息域详情</SheetDescription>

      <!-- 头部 -->
      <div class="shrink-0 border-b px-6 py-4 pr-14" data-testid="drawer-header">
        <div class="flex items-start justify-between gap-4">
          <div class="flex min-w-0 items-center gap-3">
            <div
              class="bg-primary/10 text-primary flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-base font-medium"
            >
              {{ detail?.name?.slice(0, 1) ?? "…" }}
            </div>
            <div class="flex min-w-0 flex-col gap-1">
              <div class="flex items-center gap-2">
                <span class="truncate text-base font-semibold">{{ detail?.name ?? (loading ? "加载中…" : "--") }}</span>
                <Badge v-if="detail" :variant="EMPLOYEE_STATUS_VARIANTS[detail.status]" data-testid="drawer-status-badge">
                  {{ EMPLOYEE_STATUS_LABELS[detail.status] }}
                </Badge>
              </div>
              <div class="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                <span>工号 {{ detail?.employee_no ?? "--" }}</span>
                <span v-if="detail?.phone">{{ detail.phone }}</span>
                <span v-if="detail?.work_email">{{ detail.work_email }}</span>
              </div>
              <div class="text-muted-foreground text-xs">
                {{ orgLabel }} · {{ positionLabel }} · {{ detail?.job_level || "未定级" }}
                <span class="ml-1">（{{ detail?.has_account ? "已开通账号" : "未开通账号" }}）</span>
              </div>
            </div>
          </div>

          <div class="flex shrink-0 items-center gap-2">
            <Button
              v-if="canWrite && detail && isActiveEmployee(detail.status)"
              size="sm"
              data-testid="drawer-change-button"
              @click="openChange('probate')"
            >
              人事异动
            </Button>
            <DropdownMenu v-if="detail">
              <DropdownMenuTrigger as-child>
                <Button variant="outline" size="sm" data-testid="drawer-more-button">
                  <MoreHorizontalIcon class="h-4 w-4" />
                  更多
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" data-testid="drawer-more-menu">
                <DropdownMenuItem
                  v-if="detail && isActiveEmployee(detail.status) && !detail.has_account"
                  data-testid="drawer-action-open-account"
                  @click="openAccountFor"
                >
                  开通系统账号
                </DropdownMenuItem>
                <DropdownMenuItem
                  v-if="canContractWrite && isActiveEmployee(detail.status)"
                  @click="renewFrom = null; contractModalOpen = true"
                >
                  新签合同
                </DropdownMenuItem>
                <DropdownMenuItem
                  v-if="canWrite && detail && isActiveEmployee(detail.status)"
                  data-testid="drawer-action-offboard"
                  @click="openChange('offboard')"
                >
                  办理离职
                </DropdownMenuItem>
                <template v-if="canDelete && detail && !isActiveEmployee(detail.status)">
                  <DropdownMenuSeparator />
                  <DropdownMenuItem class="text-destructive" data-testid="drawer-action-delete" @click="deleteEmployeeFor">
                    删除员工
                  </DropdownMenuItem>
                </template>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>

      <!-- Tabs 主体 -->
      <Tabs v-model="activeTab" class="flex min-h-0 flex-1 flex-col gap-0" data-testid="drawer-tabs">
        <div class="shrink-0 border-b px-6 pt-2">
          <TabsList variant="line">
            <TabsTrigger
              v-for="tab in tabs"
              :key="tab.value"
              :value="tab.value"
              :data-testid="`drawer-tab-${tab.value}`"
            >
              {{ tab.label }}
            </TabsTrigger>
          </TabsList>
        </div>

        <ScrollArea class="min-h-0 flex-1">
          <div class="px-6 py-4">
            <!-- 概览 -->
            <TabsContent value="overview" class="mt-0" data-testid="drawer-panel-overview">
              <div class="flex flex-col gap-6">
                <section class="flex flex-col gap-2">
                  <h3 class="text-muted-foreground text-xs font-medium">概况</h3>
                  <DescriptionList :items="overviewItems" :columns="3" bordered />
                </section>
                <section class="flex flex-col gap-2">
                  <h3 class="text-muted-foreground text-xs font-medium">成长记录</h3>
                  <div v-if="changes.length" class="flex flex-col" data-testid="drawer-timeline">
                    <div v-for="record in changes" :key="record.id" class="flex gap-3">
                      <div class="flex flex-col items-center">
                        <span class="bg-primary/60 mt-1.5 h-2 w-2 shrink-0 rounded-full" />
                        <span class="bg-border w-px flex-1" />
                      </div>
                      <div class="flex-1 pb-4">
                        <div class="flex items-center gap-2">
                          <Badge variant="outline">{{ CHANGE_TYPE_LABELS[record.change_type] ?? record.change_type }}</Badge>
                          <span class="text-muted-foreground text-xs">{{ record.effective_date }}</span>
                        </div>
                        <p v-for="(line, index) in changeDetailLines(record)" :key="index" class="text-muted-foreground mt-1 text-xs">
                          {{ line }}
                        </p>
                      </div>
                    </div>
                  </div>
                  <p v-else class="text-muted-foreground py-4 text-center text-sm">暂无异动记录</p>
                </section>
              </div>
            </TabsContent>

            <!-- 任职信息 -->
            <TabsContent value="job" class="mt-0" data-testid="drawer-panel-job">
              <div class="flex flex-col gap-4">
                <div class="flex items-center justify-between">
                  <DescriptionList
                    class="flex-1"
                    :items="[
                      { label: '组织', value: orgLabel },
                      { label: '岗位', value: positionLabel },
                      { label: '职级', value: detail?.job_level ?? '--' },
                      { label: '入职日期', value: detail?.hire_date ?? '--' },
                      { label: '转正日期', value: detail?.regular_date ?? '--' },
                      { label: '状态', value: detail ? EMPLOYEE_STATUS_LABELS[detail.status] : '--' },
                    ]"
                    :columns="3"
                    bordered
                  />
                </div>
                <Button v-if="canWrite" variant="outline" size="sm" class="self-start" @click="formModalOpen = true">
                  编辑任职信息
                </Button>
                <section v-if="jobItems.length" class="flex flex-col gap-2">
                  <h3 class="text-muted-foreground text-xs font-medium">任职扩展属性</h3>
                  <DescriptionList
                    :items="jobItems.map((item) => ({ label: item.name, value: displayValue(item) }))"
                    :columns="3"
                    bordered
                  />
                </section>
              </div>
            </TabsContent>

            <!-- 个人信息 -->
            <TabsContent value="personal" class="mt-0" data-testid="drawer-panel-personal">
              <div class="flex flex-col gap-4">
                <DescriptionList
                  :items="[
                    { label: '证件号（掩码）', value: detail?.id_card_masked ?? '--' },
                    { label: '性别', value: detail?.gender === 'male' ? '男' : detail?.gender === 'female' ? '女' : '--' },
                    { label: '出生日期', value: detail?.birth_date ?? '--' },
                    { label: '银行卡（掩码）', value: detail?.bank_card_masked ?? '--' },
                  ]"
                  :columns="2"
                  bordered
                />
                <Button
                  v-if="canSensitive"
                  variant="outline"
                  size="sm"
                  class="self-start"
                  data-testid="drawer-sensitive-button"
                  @click="showSensitive"
                >
                  查看明文（写审计）
                </Button>
                <div v-if="sensitive" class="flex flex-col gap-2 rounded-md border p-3" data-testid="drawer-sensitive-view">
                  <p class="text-destructive text-xs">以下为明文信息，本次查看已记录审计日志。</p>
                  <DescriptionList
                    :items="[
                      { label: '证件号', value: sensitive.id_card ?? '--' },
                      { label: '银行卡号', value: sensitive.bank_card ?? '--' },
                    ]"
                    :columns="2"
                    bordered
                  />
                </div>
                <template v-for="item in personalItems" :key="item.definition_id">
                  <section class="flex flex-col gap-2">
                    <h3 class="text-muted-foreground text-xs font-medium">
                      {{ item.name }}（{{ ATTRIBUTE_DATA_TYPE_LABELS[item.data_type] ?? item.data_type }}）
                    </h3>
                    <template v-if="jsonRecords(item)">
                      <div
                        v-for="(record, recordIndex) in jsonRecords(item)"
                        :key="recordIndex"
                        class="rounded-md border p-3"
                      >
                        <DescriptionList
                          :items="Object.entries(record).map(([key, value]) => ({ label: key, value: value == null ? '--' : String(value) }))"
                          :columns="3"
                          bordered
                        />
                      </div>
                      <p v-if="!jsonRecords(item)!.length" class="text-muted-foreground text-sm">未填写</p>
                    </template>
                    <pre v-else-if="jsonScalar(item)" class="bg-muted/40 overflow-x-auto rounded-md border p-3 text-xs">{{ jsonScalar(item) }}</pre>
                    <p v-else class="text-sm">{{ displayValue(item) }}</p>
                  </section>
                </template>
              </div>
            </TabsContent>

            <!-- 联系信息 -->
            <TabsContent value="contact" class="mt-0" data-testid="drawer-panel-contact">
              <div class="flex flex-col gap-4">
                <DescriptionList
                  :items="[
                    { label: '手机号', value: detail?.phone ?? '--' },
                    { label: '工作邮箱', value: detail?.work_email ?? '--' },
                  ]"
                  :columns="2"
                  bordered
                />
                <template v-for="item in contactItems" :key="item.definition_id">
                  <section class="flex flex-col gap-2">
                    <h3 class="text-muted-foreground text-xs font-medium">
                      {{ item.name }}（{{ ATTRIBUTE_DATA_TYPE_LABELS[item.data_type] ?? item.data_type }}）
                    </h3>
                    <template v-if="jsonRecords(item)">
                      <div
                        v-for="(record, recordIndex) in jsonRecords(item)"
                        :key="recordIndex"
                        class="rounded-md border p-3"
                      >
                        <DescriptionList
                          :items="Object.entries(record).map(([key, value]) => ({ label: key, value: value == null ? '--' : String(value) }))"
                          :columns="3"
                          bordered
                        />
                      </div>
                      <p v-if="!jsonRecords(item)!.length" class="text-muted-foreground text-sm">未填写</p>
                    </template>
                    <pre v-else-if="jsonScalar(item)" class="bg-muted/40 overflow-x-auto rounded-md border p-3 text-xs">{{ jsonScalar(item) }}</pre>
                    <p v-else class="text-sm">{{ displayValue(item) }}</p>
                  </section>
                </template>
              </div>
            </TabsContent>

            <!-- 合同信息 -->
            <TabsContent value="contracts" class="mt-0" data-testid="drawer-panel-contracts">
              <div class="flex flex-col gap-3">
                <div class="flex justify-end">
                  <Button
                    v-if="canContractWrite && detail && isActiveEmployee(detail.status)"
                    size="sm"
                    data-testid="drawer-contract-create"
                    @click="renewFrom = null; contractModalOpen = true"
                  >
                    新签合同
                  </Button>
                </div>
                <div v-for="contract in contracts" :key="contract.id" class="flex flex-col gap-2 rounded-md border p-4" data-testid="drawer-contract-card">
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium">{{ contract.contract_no }}</span>
                      <Badge variant="outline">{{ contractTypeLabel(contract.contract_type) }}</Badge>
                      <Badge :variant="contract.status === 'active' ? 'default' : contract.status === 'expired' ? 'secondary' : 'destructive'">
                        {{ CONTRACT_STATUS_LABELS[contract.status] ?? contract.status }}
                      </Badge>
                    </div>
                    <div v-if="canContractWrite" class="flex items-center gap-1">
                      <Button
                        v-if="contract.status === 'active' && isActiveEmployee(detail?.status)"
                        variant="ghost"
                        size="sm"
                        @click="renewFrom = contract; contractModalOpen = true"
                      >
                        续签
                      </Button>
                      <Button v-if="contract.status === 'active'" variant="ghost" size="sm" @click="terminateContractFor(contract)">
                        终止
                      </Button>
                      <Button variant="ghost" size="sm" class="text-destructive" @click="removeContract(contract)">删除</Button>
                    </div>
                  </div>
                  <div class="text-muted-foreground flex flex-wrap gap-x-4 gap-y-0.5 text-xs">
                    <span>{{ contract.start_date }} ~ {{ contract.end_date ?? "无固定期限" }}</span>
                    <span v-if="contract.company">签约主体：{{ contract.company }}</span>
                    <span v-if="contract.signed_date">签订：{{ contract.signed_date }}</span>
                    <span v-if="contract.expiry_remind">到期提醒：开</span>
                  </div>
                  <p v-if="contract.remark" class="text-muted-foreground text-xs">备注：{{ contract.remark }}</p>
                </div>
                <p v-if="!contracts.length" class="text-muted-foreground py-6 text-center text-sm">暂无合同记录</p>
              </div>
            </TabsContent>

            <!-- 材料附件 -->
            <TabsContent value="attachments" class="mt-0" data-testid="drawer-panel-attachments">
              <div class="flex flex-col gap-5">
                <section
                  v-for="docType in ATTACHMENT_DOC_TYPES"
                  :key="docType.value"
                  class="flex flex-col gap-2"
                  :data-testid="`drawer-attachment-group-${docType.value}`"
                >
                  <div class="flex items-center justify-between">
                    <h3 class="text-xs font-medium">
                      {{ docType.label }}
                      <span class="text-muted-foreground ml-1">（{{ attachmentsByDocType(docType.value).length }}）</span>
                    </h3>
                  </div>
                  <div
                    v-if="canAttachmentWrite"
                    class="flex items-center gap-2"
                  >
                    <FileDropzone
                      compact
                      :label="`上传${docType.label}`"
                      :disabled="uploadingDocType === docType.value"
                      @select="(files: File[]) => uploadAttachment(docType.value, files)"
                    />
                  </div>
                  <div
                    v-for="attachment in attachmentsByDocType(docType.value)"
                    :key="attachment.id"
                    class="flex items-center justify-between rounded-md border px-3 py-2"
                    data-testid="drawer-attachment-item"
                  >
                    <span class="truncate text-sm">{{ attachment.file_name }}</span>
                    <span class="flex shrink-0 items-center gap-1">
                      <Button variant="ghost" size="sm" @click="downloadAttachment(attachment)">下载</Button>
                      <Button v-if="canAttachmentWrite" variant="ghost" size="sm" class="text-destructive" @click="removeAttachment(attachment)">
                        删除
                      </Button>
                    </span>
                  </div>
                </section>
              </div>
            </TabsContent>

            <!-- 薪酬信息 -->
            <TabsContent value="salary" class="mt-0" data-testid="drawer-panel-salary">
              <div class="flex flex-col gap-4">
                <section v-if="bandComparison" class="flex flex-col gap-2 rounded-md border p-4" data-testid="drawer-band-comparison">
                  <div class="flex items-center gap-2">
                    <h3 class="text-xs font-medium">薪带对标</h3>
                    <Badge :variant="BAND_POSITION_META[bandComparison.position]?.variant ?? 'outline'">
                      {{ BAND_POSITION_META[bandComparison.position]?.label ?? bandComparison.position }}
                    </Badge>
                  </div>
                  <p class="text-muted-foreground text-xs">
                    职级 {{ bandComparison.job_level || "--" }} · 方案总额
                    <span class="text-foreground font-medium">{{ bandComparison.total.toLocaleString() }}</span> 元/月
                    <template v-if="bandComparison.band_min != null && bandComparison.band_max != null">
                      · 带宽 {{ bandComparison.band_min.toLocaleString() }} ~ {{ bandComparison.band_max.toLocaleString() }}
                    </template>
                  </p>
                </section>
                <section class="flex flex-col gap-2">
                  <h3 class="text-muted-foreground text-xs font-medium">定薪历史</h3>
                  <table v-if="salaryPackages.length" class="w-full text-sm" data-testid="drawer-salary-table">
                    <thead>
                      <tr class="text-muted-foreground border-b text-left">
                        <th class="py-2 pr-3 font-medium">薪酬项</th>
                        <th class="py-2 pr-3 font-medium">金额（元/月）</th>
                        <th class="py-2 pr-3 font-medium">原因</th>
                        <th class="py-2 pr-3 font-medium">生效区间</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="pkg in salaryPackages" :key="pkg.id" class="border-b">
                        <td class="py-2 pr-3">{{ pkg.item_name ?? pkg.item_code ?? pkg.item_id }}</td>
                        <td class="py-2 pr-3">{{ pkg.amount.toLocaleString() }}</td>
                        <td class="py-2 pr-3">{{ SALARY_REASON_LABELS[pkg.reason] ?? pkg.reason }}</td>
                        <td class="py-2 pr-3">{{ pkg.effective_from }} ~ {{ pkg.effective_to ?? "至今" }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <p v-else class="text-muted-foreground py-4 text-center text-sm">暂无定薪记录</p>
                </section>
              </div>
            </TabsContent>

            <!-- 扩展属性 -->
            <TabsContent value="custom" class="mt-0" data-testid="drawer-panel-custom">
              <div class="flex flex-col gap-4">
                <div class="flex items-center justify-between">
                  <h3 class="text-muted-foreground text-xs font-medium">
                    自定义与自建属性组（{{ customItems.length }} 个字段）
                  </h3>
                  <div class="flex items-center gap-2">
                    <Button variant="ghost" size="sm" @click="fieldManagerOpen = true">管理属性定义</Button>
                    <Button size="sm" data-testid="drawer-custom-save" :disabled="!customItems.length" @click="saveCustomAttributes">
                      保存
                    </Button>
                  </div>
                </div>
                <JsonRender
                  v-if="customItems.length"
                  :key="`drawer-custom-${customItems.length}`"
                  ref="customFormRef"
                  :spec="customBuild.spec"
                  :initial-state="customBuild.initialState"
                />
                <p v-else class="text-muted-foreground py-6 text-center text-sm">
                  当前租户暂无自定义扩展属性，可在属性定义管理中添加。
                </p>
              </div>
            </TabsContent>
          </div>
        </ScrollArea>
      </Tabs>

      <!-- 底部员工切换条 -->
      <EmployeeSwitchBar
        :employees="props.employees"
        :current-id="props.employeeId"
        @switch="(employee) => emit('switch', employee)"
      />

      <!-- 账号开通结果 -->
      <Dialog :open="Boolean(accountResult)" @update:open="(value: boolean) => { if (!value) accountResult = null; }">
        <DialogContent class="sm:max-w-sm" data-testid="account-result-dialog">
          <DialogHeader>
            <DialogTitle>账号开通成功</DialogTitle>
            <DialogDescription>初始密码仅本次展示，请立即复制并告知员工。</DialogDescription>
          </DialogHeader>
          <div v-if="accountResult" class="flex flex-col gap-2 rounded-md border p-3 text-sm">
            <div class="flex justify-between">
              <Label>登录账号</Label>
              <span class="font-mono">{{ accountResult.username }}</span>
            </div>
            <div class="flex justify-between">
              <Label>初始密码</Label>
              <span class="font-mono" data-testid="account-initial-password">{{ accountResult.initial_password }}</span>
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <Button variant="outline" @click="copyAccountResult">复制</Button>
            <Button @click="accountResult = null">我已保存</Button>
          </div>
        </DialogContent>
      </Dialog>

      <!-- 人事异动 -->
      <EmployeeChangeModal
        v-model:open="changeModalOpen"
        :employee="detail"
        :initial-type="changeInitialType"
        @saved="reload(); emit('refresh')"
      />

      <!-- 合同新签/续签 -->
      <EmployeeContractModal
        v-model:open="contractModalOpen"
        :employee-id="props.employeeId ?? ''"
        :renew-from="renewFrom"
        @saved="reload(); emit('refresh')"
      />

      <!-- 员工编辑 -->
      <EmployeeFormModal
        v-model:open="formModalOpen"
        mode="edit"
        :employee="detail"
        @saved="reload(); emit('refresh')"
      />

      <!-- 属性定义管理 -->
      <FieldDefinitionManager v-model:open="fieldManagerOpen" />
    </SheetContent>
  </Sheet>
</template>
