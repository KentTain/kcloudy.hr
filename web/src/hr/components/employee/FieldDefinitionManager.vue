<script setup lang="ts">
/**
 * 员工扩展属性定义管理（属性组 + 组内字段定义）。
 * 左组右表布局：组列表可增删改；选中组内定义表支持新增/编辑/删除。
 */
import { computed, ref, watch } from "vue";

import { Badge } from "@/components";
import { Button } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Input, Select, Switch, Textarea } from "@/components";
import { Label } from "@/components";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import {
  createFieldDefinition,
  createFieldGroup,
  deleteFieldDefinition,
  deleteFieldGroup,
  listFieldDefinitions,
  listFieldGroups,
  updateFieldDefinition,
  updateFieldGroup,
} from "@/hr/api/field";
import {
  ATTRIBUTE_DATA_TYPE_LABELS,
  type FieldDefinition,
  type FieldGroup,
} from "@/hr/types/employee";

const open = defineModel<boolean>("open", { required: true });

const DATA_TYPE_OPTIONS = Object.entries(ATTRIBUTE_DATA_TYPE_LABELS).map(([value, label]) => ({ value, label }));

const groups = ref<FieldGroup[]>([]);
const definitions = ref<FieldDefinition[]>([]);
const activeGroupId = ref<string>("");
const loading = ref(false);

// 属性组编辑
const groupEditorOpen = ref(false);
const groupEditing = ref<FieldGroup | null>(null);
const groupCode = ref("");
const groupName = ref("");
const groupSort = ref<number>(0);

// 字段定义编辑
const defEditorOpen = ref(false);
const defEditing = ref<FieldDefinition | null>(null);
const defName = ref("");
const defDataType = ref("string");
const defRequire = ref(false);
const defCanEdit = ref(true);
const defSort = ref<number>(0);
const defExtData = ref("");
const extDataError = ref("");

const activeGroup = computed(() => groups.value.find((group) => group.id === activeGroupId.value) ?? null);

watch(open, async (value) => {
  if (value) await loadAll();
}, { immediate: true });

async function loadAll() {
  loading.value = true;
  try {
    const res = await listFieldGroups();
    groups.value = (res.data ?? []).slice().sort((a, b) => a.sort - b.sort);
    if (!groups.value.find((group) => group.id === activeGroupId.value)) {
      activeGroupId.value = groups.value[0]?.id ?? "";
    }
    await loadDefinitions();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "属性组加载失败"));
  } finally {
    loading.value = false;
  }
}

async function loadDefinitions() {
  if (!activeGroupId.value) {
    definitions.value = [];
    return;
  }
  try {
    const res = await listFieldDefinitions(activeGroupId.value);
    definitions.value = (res.data ?? []).slice().sort((a, b) => a.sort - b.sort);
  } catch (error) {
    notifyError(error, getErrorMessage(error, "字段定义加载失败"));
    definitions.value = [];
  }
}

/* ── 属性组 ── */

function openGroupEditor(group: FieldGroup | null) {
  groupEditing.value = group;
  groupCode.value = group?.code ?? "";
  groupName.value = group?.name ?? "";
  groupSort.value = group?.sort ?? groups.value.length;
  groupEditorOpen.value = true;
}

async function submitGroup() {
  if (!groupCode.value.trim() || !groupName.value.trim()) {
    notifyError(new Error("请填写组编码与名称"));
    return;
  }
  try {
    if (groupEditing.value) {
      await updateFieldGroup(groupEditing.value.id, {
        code: groupCode.value,
        name: groupName.value,
        sort: groupSort.value,
      });
      notifySuccess("属性组已更新");
    } else {
      await createFieldGroup({ code: groupCode.value, name: groupName.value, sort: groupSort.value });
      notifySuccess("属性组已创建");
    }
    groupEditorOpen.value = false;
    await loadAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "属性组保存失败"));
  }
}

async function removeGroup(group: FieldGroup) {
  if (!(await confirmAction(`确定删除属性组「${group.name}」？组内字段定义将一并删除。`))) return;
  try {
    await deleteFieldGroup(group.id);
    notifySuccess("属性组已删除");
    if (activeGroupId.value === group.id) activeGroupId.value = "";
    await loadAll();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}

/* ── 字段定义 ── */

function openDefEditor(definition: FieldDefinition | null) {
  defEditing.value = definition;
  defName.value = definition?.name ?? "";
  defDataType.value = definition?.data_type ?? "string";
  defRequire.value = definition?.is_require ?? false;
  defCanEdit.value = definition?.can_edit ?? true;
  defSort.value = definition?.sort ?? definitions.value.length;
  defExtData.value = definition?.ext_data ? JSON.stringify(definition.ext_data, null, 2) : "";
  extDataError.value = "";
  defEditorOpen.value = true;
}

function validateExtData(): Record<string, unknown> | undefined {
  extDataError.value = "";
  if (!defExtData.value.trim()) return undefined;
  try {
    return JSON.parse(defExtData.value) as Record<string, unknown>;
  } catch {
    extDataError.value = "JSON 格式不合法";
    return undefined;
  }
}

async function submitDefinition() {
  if (!activeGroupId.value) return;
  if (!defName.value.trim()) {
    notifyError(new Error("请填写字段名称"));
    return;
  }
  const extData = validateExtData();
  if (extDataError.value) return;
  try {
    const payload = {
      group_id: activeGroupId.value,
      name: defName.value,
      data_type: defDataType.value,
      is_require: defRequire.value,
      can_edit: defCanEdit.value,
      sort: defSort.value,
      ext_data: extData ?? null,
    };
    if (defEditing.value) {
      await updateFieldDefinition(defEditing.value.id, payload);
      notifySuccess("字段定义已更新");
    } else {
      await createFieldDefinition(payload);
      notifySuccess("字段定义已创建");
    }
    defEditorOpen.value = false;
    await loadDefinitions();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "字段定义保存失败"));
  }
}

async function removeDefinition(definition: FieldDefinition) {
  if (!(await confirmAction(`确定删除字段「${definition.name}」？已有填写值将不再展示。`))) return;
  try {
    await deleteFieldDefinition(definition.id);
    notifySuccess("字段定义已删除");
    await loadDefinitions();
  } catch (error) {
    notifyError(error, getErrorMessage(error, "删除失败"));
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="flex max-h-[84vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl" data-testid="field-definition-manager">
      <DialogHeader class="shrink-0 border-b px-6 py-4">
        <DialogTitle>扩展属性定义管理</DialogTitle>
        <DialogDescription>维护员工档案的属性组与字段定义，定义后可在建档与详情中使用。</DialogDescription>
      </DialogHeader>

      <div class="flex min-h-0 flex-1 overflow-hidden">
        <!-- 左：属性组列表 -->
        <div class="flex w-56 shrink-0 flex-col border-r">
          <div class="flex items-center justify-between px-4 py-3">
            <span class="text-muted-foreground text-xs font-medium">属性组</span>
            <Button variant="ghost" size="sm" data-testid="field-group-add" @click="openGroupEditor(null)">新增</Button>
          </div>
          <div class="flex-1 overflow-y-auto px-2 pb-2">
            <button
              v-for="group in groups"
              :key="group.id"
              type="button"
              class="group mb-0.5 flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm hover:bg-accent"
              :class="group.id === activeGroupId ? 'bg-accent font-medium' : ''"
              :data-testid="`field-group-item`"
              :data-group-id="group.id"
              @click="activeGroupId = group.id"
            >
              <span class="truncate">{{ group.name }}</span>
              <span class="flex items-center gap-1 opacity-0 transition group-hover:opacity-100">
                <Button variant="ghost" size="sm" class="h-6 px-1.5" @click.stop="openGroupEditor(group)">编辑</Button>
                <Button variant="ghost" size="sm" class="text-destructive h-6 px-1.5" @click.stop="removeGroup(group)">删</Button>
              </span>
            </button>
          </div>
        </div>

        <!-- 右：组内字段定义 -->
        <div class="flex min-h-0 min-w-0 flex-1 flex-col">
          <div class="flex items-center justify-between px-5 py-3">
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ activeGroup?.name ?? "字段定义" }}</span>
              <Badge v-if="activeGroup" variant="secondary">{{ activeGroup.code }}</Badge>
            </div>
            <Button variant="outline" size="sm" :disabled="!activeGroupId" data-testid="field-definition-add" @click="openDefEditor(null)">
              新增字段
            </Button>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
            <p v-if="!activeGroupId" class="text-muted-foreground py-8 text-center text-sm">请先选择或创建属性组。</p>
            <table v-else class="w-full text-sm" data-testid="field-definition-table">
              <thead>
                <tr class="text-muted-foreground border-b text-left">
                  <th class="py-2 pr-3 font-medium">字段名称</th>
                  <th class="py-2 pr-3 font-medium">类型</th>
                  <th class="py-2 pr-3 font-medium">必填</th>
                  <th class="py-2 pr-3 font-medium">可编辑</th>
                  <th class="py-2 pr-3 font-medium">排序</th>
                  <th class="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="definition in definitions" :key="definition.id" class="border-b" :data-testid="`field-definition-row`">
                  <td class="py-2 pr-3">{{ definition.name }}</td>
                  <td class="py-2 pr-3">
                    <Badge variant="outline">{{ ATTRIBUTE_DATA_TYPE_LABELS[definition.data_type] ?? definition.data_type }}</Badge>
                  </td>
                  <td class="py-2 pr-3">{{ definition.is_require ? "是" : "否" }}</td>
                  <td class="py-2 pr-3">{{ definition.can_edit ? "是" : "否" }}</td>
                  <td class="py-2 pr-3">{{ definition.sort }}</td>
                  <td class="flex gap-1 py-2">
                    <Button variant="ghost" size="sm" @click="openDefEditor(definition)">编辑</Button>
                    <Button variant="ghost" size="sm" class="text-destructive" @click="removeDefinition(definition)">删除</Button>
                  </td>
                </tr>
                <tr v-if="!definitions.length">
                  <td colspan="6" class="text-muted-foreground py-6 text-center">暂无字段定义</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 属性组编辑子弹窗 -->
      <Dialog v-model:open="groupEditorOpen">
        <DialogContent class="sm:max-w-sm" data-testid="field-group-editor">
          <DialogHeader>
            <DialogTitle>{{ groupEditing ? "编辑属性组" : "新增属性组" }}</DialogTitle>
          </DialogHeader>
          <div class="flex flex-col gap-3 py-2">
            <div class="flex flex-col gap-1.5">
              <Label>组编码 <span class="text-destructive">*</span></Label>
              <Input v-model="groupCode" placeholder="如 custom" :disabled="Boolean(groupEditing)" data-testid="field-group-code" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>组名称 <span class="text-destructive">*</span></Label>
              <Input v-model="groupName" placeholder="如 自定义信息" data-testid="field-group-name" />
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>排序</Label>
              <Input v-model.number="groupSort" type="number" />
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <Button variant="outline" @click="groupEditorOpen = false">取消</Button>
            <Button data-testid="field-group-submit" @click="submitGroup">保存</Button>
          </div>
        </DialogContent>
      </Dialog>

      <!-- 字段定义编辑子弹窗 -->
      <Dialog v-model:open="defEditorOpen">
        <DialogContent class="sm:max-w-md" data-testid="field-definition-editor">
          <DialogHeader>
            <DialogTitle>{{ defEditing ? "编辑字段定义" : "新增字段定义" }}</DialogTitle>
          </DialogHeader>
          <div class="flex flex-col gap-3 py-2">
            <div class="flex flex-col gap-1.5">
              <Label>字段名称 <span class="text-destructive">*</span></Label>
              <Input v-model="defName" placeholder="如 紧急联系人电话" data-testid="field-definition-name" />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div class="flex flex-col gap-1.5">
                <Label>数据类型</Label>
                <Select v-model="defDataType" :options="DATA_TYPE_OPTIONS" data-testid="field-definition-type" />
              </div>
              <div class="flex flex-col gap-1.5">
                <Label>排序</Label>
                <Input v-model.number="defSort" type="number" />
              </div>
            </div>
            <div class="flex items-center gap-6">
              <span class="flex items-center gap-2">
                <Switch id="def-require" v-model="defRequire" />
                <Label for="def-require">必填</Label>
              </span>
              <span class="flex items-center gap-2">
                <Switch id="def-can-edit" v-model="defCanEdit" />
                <Label for="def-can-edit">员工可编辑</Label>
              </span>
            </div>
            <div class="flex flex-col gap-1.5">
              <Label>扩展配置（JSON，选填）</Label>
              <Textarea v-model="defExtData" class="font-mono text-xs" rows="4" placeholder='如 {"options":["A","B"]}' data-testid="field-definition-ext" />
              <p v-if="extDataError" class="text-destructive text-xs">{{ extDataError }}</p>
            </div>
          </div>
          <div class="flex justify-end gap-2">
            <Button variant="outline" @click="defEditorOpen = false">取消</Button>
            <Button data-testid="field-definition-submit" @click="submitDefinition">保存</Button>
          </div>
        </DialogContent>
      </Dialog>
    </DialogContent>
  </Dialog>
</template>
