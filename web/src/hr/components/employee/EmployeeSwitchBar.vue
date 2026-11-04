<script setup lang="ts">
/**
 * 详情抽屉底部员工切换条（上一员工 / i·n / 下一员工）
 */
import { computed } from "vue";

import { Button } from "@/components";
import type { Employee } from "@/hr/types/employee";

const props = defineProps<{
  employees: Employee[];
  currentId: string | null;
}>();

const emit = defineEmits<{ switch: [employee: Employee] }>();

const currentIndex = computed(() => props.employees.findIndex((employee) => employee.id === props.currentId));
const total = computed(() => props.employees.length);
const hasPrev = computed(() => currentIndex.value > 0);
const hasNext = computed(() => currentIndex.value >= 0 && currentIndex.value < total.value - 1);

function switchTo(offset: number) {
  const target = props.employees[currentIndex.value + offset];
  if (target) emit("switch", target);
}
</script>

<template>
  <div
    v-if="total > 0"
    class="flex shrink-0 items-center justify-between border-t px-6 py-2.5"
    data-testid="employee-switch-bar"
  >
    <Button variant="ghost" size="sm" :disabled="!hasPrev" data-testid="employee-switch-prev" @click="switchTo(-1)">
      ← 上一员工
    </Button>
    <span class="text-muted-foreground text-xs" data-testid="employee-switch-index">
      {{ currentIndex + 1 }} / {{ total }}
    </span>
    <Button variant="ghost" size="sm" :disabled="!hasNext" data-testid="employee-switch-next" @click="switchTo(1)">
      下一员工 →
    </Button>
  </div>
</template>
