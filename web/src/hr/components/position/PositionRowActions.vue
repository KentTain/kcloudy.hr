<script setup lang="ts">
/**
 * 岗位列表行操作（编辑/在岗员工/停用或启用/删除；删除仅无在岗员工时出项）
 */
import { computed } from "vue";

import { RowActions } from "@/components";

import type { RowAction } from "@/components";

import type { Position } from "@/hr/types/position";

const props = defineProps<{
  position: Position;
  canWrite: boolean;
  canDelete: boolean;
}>();

const emit = defineEmits<{
  edit: [position: Position];
  employees: [position: Position];
  toggleStatus: [position: Position];
  remove: [position: Position];
}>();

const actions = computed<RowAction[]>(() => {
  const result: RowAction[] = [];
  if (props.canWrite) {
    result.push({ key: "edit", label: "编辑", onClick: () => emit("edit", props.position) });
    result.push({
      key: "employees",
      label: "在岗员工",
      onClick: () => emit("employees", props.position),
    });
    result.push({
      key: "toggle-status",
      label: props.position.status === "disabled" ? "启用" : "停用",
      onClick: () => emit("toggleStatus", props.position),
    });
  }
  if (props.canDelete && props.position.active_employee_count === 0) {
    result.push({
      key: "delete",
      label: "删除",
      variant: "destructive",
      onClick: () => emit("remove", props.position),
    });
  }
  return result;
});
</script>

<template>
  <RowActions :actions="actions" />
</template>
