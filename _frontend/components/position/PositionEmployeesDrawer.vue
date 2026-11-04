<script setup lang="ts">
/**
 * 在岗员工抽屉：岗位摘要 + 在岗员工列表（后端默认排除已离职）+ 查看员工跳转
 */
import { ref, watch } from "vue";

import { Badge, Button } from "@/components";
import { Table } from "@/components";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import { getErrorMessage, notifyError } from "@/framework/utils/feedback";

import { listEmployees } from "@/hr/api/employee";
import {
  EMPLOYEE_STATUS_LABELS,
  EMPLOYEE_STATUS_VARIANTS,
  type Employee,
  type OrgTreeNode,
} from "@/hr/types/employee";
import type { Position } from "@/hr/types/position";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  position: Position | null;
  /** 组织名称解析（org_id → 名称） */
  orgNameOf: (orgId: string | null) => string;
}>();

const emit = defineEmits<{ viewEmployee: [employeeId: string] }>();

const loading = ref(false);
const employees = ref<Employee[]>([]);
const orgTree = ref<OrgTreeNode[]>([]);

const columns = [
  { key: "employee_no", title: "工号", width: "110px" },
  { key: "name", title: "姓名", width: "120px" },
  { key: "status", title: "状态", width: "90px" },
  { key: "job_level", title: "职级", width: "80px" },
  { key: "org", title: "组织", width: "140px" },
  { key: "hire_date", title: "入职日期", width: "110px" },
  { key: "actions", title: "操作", width: "90px", align: "right" as const },
];

watch(open, async (value) => {
  if (!value) return;
  employees.value = [];
  if (!props.position) return;
  loading.value = true;
  try {
    const res = await listEmployees({ page: 1, page_size: 50, position_id: props.position.id });
    employees.value = res.data ?? [];
  } catch (error) {
    notifyError(error, getErrorMessage(error, "在岗员工加载失败"));
  } finally {
    loading.value = false;
  }
});

function handleViewEmployee(employee: Employee) {
  open.value = false;
  emit("viewEmployee", employee.id);
}
</script>

<template>
  <Sheet :open="open" @update:open="open = $event">
    <SheetContent side="right" class="flex w-full flex-col gap-0 sm:max-w-2xl" data-testid="position-employees-drawer">
      <SheetHeader class="shrink-0 border-b px-5 py-4">
        <SheetTitle data-testid="position-employees-title">
          在岗员工 · {{ position?.name ?? "--" }}
        </SheetTitle>
        <SheetDescription class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span>编码：{{ position?.code ?? "--" }}</span>
          <span>组织：{{ position ? orgNameOf(position.org_id) : "--" }}</span>
          <span>职级：{{ position?.job_level || "--" }}</span>
          <span>编制：{{ position?.headcount ?? "不限" }}</span>
          <span>在岗：{{ position?.active_employee_count ?? 0 }} 人</span>
        </SheetDescription>
      </SheetHeader>
      <div class="min-h-0 flex-1 overflow-auto px-5 py-4">
        <Table
          :columns="columns"
          :data="employees"
          :loading="loading"
          empty-text="该岗位暂无在岗员工"
          data-testid="position-employees-table"
        >
          <template #status="{ row }">
            <Badge :variant="EMPLOYEE_STATUS_VARIANTS[row.status as Employee['status']]">
              {{ EMPLOYEE_STATUS_LABELS[row.status as Employee['status']] ?? row.status }}
            </Badge>
          </template>
          <template #org="{ row }">
            {{ orgNameOf((row as Employee).org_id) }}
          </template>
          <template #actions="{ row }">
            <Button
              variant="link"
              size="sm"
              class="h-auto p-0"
              :data-testid="`view-employee-${(row as Employee).id}`"
              @click="handleViewEmployee(row as Employee)"
            >
              查看员工
            </Button>
          </template>
        </Table>
      </div>
    </SheetContent>
  </Sheet>
</template>
