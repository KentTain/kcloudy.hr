<script setup lang="ts">
/**
 * 员工列表行操作（编辑 + 更多：开通账号/办理离职/删除；按状态与权限出项）
 */
import { computed } from "vue";

import type { RowAction } from "@/components";

import { RowActions } from "@/components";

import { isActiveEmployee, type Employee } from "@/hr/types/employee";

const props = defineProps<{
  employee: Employee;
  canWrite: boolean;
  canDelete: boolean;
}>();

const emit = defineEmits<{
  edit: [employee: Employee];
  openAccount: [employee: Employee];
  offboard: [employee: Employee];
  remove: [employee: Employee];
}>();

const actions = computed<RowAction[]>(() => {
  const result: RowAction[] = [];
  const active = isActiveEmployee(props.employee.status);
  if (props.canWrite) {
    result.push({
      key: "edit",
      label: "编辑",
      onClick: () => emit("edit", props.employee),
    });
    if (active && !props.employee.has_account) {
      result.push({
        key: "open-account",
        label: "开通账号",
        onClick: () => emit("openAccount", props.employee),
      });
    }
    if (active) {
      result.push({
        key: "offboard",
        label: "办理离职",
        onClick: () => emit("offboard", props.employee),
      });
    }
  }
  if (props.canDelete && !active) {
    result.push({
      key: "delete",
      label: "删除员工",
      variant: "destructive",
      onClick: () => emit("remove", props.employee),
    });
  }
  return result;
});
</script>

<template>
  <RowActions :actions="actions" />
</template>
