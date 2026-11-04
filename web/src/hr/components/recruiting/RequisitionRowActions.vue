<script setup lang="ts">
/**
 * 需求列表行操作（详情/发布/关闭；按状态与权限出项）
 */
import { computed } from "vue";

import { RowActions } from "@/components";

import type { RowAction } from "@/components";

import type { Requisition } from "@/hr/types/recruiting";

const props = defineProps<{
  requisition: Requisition;
  canWrite: boolean;
}>();

const emit = defineEmits<{
  detail: [requisition: Requisition];
  publish: [requisition: Requisition];
  close: [requisition: Requisition];
}>();

const actions = computed<RowAction[]>(() => {
  const result: RowAction[] = [
    { key: "detail", label: "详情", onClick: () => emit("detail", props.requisition) },
  ];
  if (props.canWrite && props.requisition.status !== "closed" && props.requisition.status !== "filled") {
    result.push({
      key: "publish",
      label: "发布",
      onClick: () => emit("publish", props.requisition),
    });
    result.push({
      key: "close",
      label: "关闭",
      variant: "destructive",
      onClick: () => emit("close", props.requisition),
    });
  }
  return result;
});
</script>

<template>
  <RowActions :actions="actions" />
</template>
