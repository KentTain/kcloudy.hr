<script setup lang="ts">
/**
 * 薪酬项管理页：字典底座（EAV 定义集）列表 + 规则编辑弹窗 + 类别字典管理弹窗。
 * 删除保护：被定薪方案/发薪明细引用的项后端拒绝删除，仅可停用。
 */
import type { ColumnDef } from "@tanstack/vue-table";
import { computed, h, onMounted, ref } from "vue";

import {
  Badge,
  Button,
  DataTable,
  Input,
  Select,
  useDataTable,
} from "@/components";
import AppPage from "@/framework/layouts/components/AppPage.vue";

import { confirmAction, getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";
import { useUserStore } from "@/framework/stores";

import { deleteSalaryItem, getSalaryCategories, listSalaryItems, updateSalaryItem } from "@/hr/api/salary";
import CategoryManageModal from "@/hr/components/salary/CategoryManageModal.vue";
import SalaryItemFormModal from "@/hr/components/salary/SalaryItemFormModal.vue";
import { SALARY_ITEM_RULE_LABELS, type SalaryItem } from "@/hr/types/salary";

const userStore = useUserStore();
const canWrite = computed(() => userStore.hasPermission("hr:salary_item:write"));
const canDelete = computed(() => userStore.hasPermission("hr:salary_item:delete"));

/* ── 类别字典 ── */

const categories = ref<string[]>([]);
const categoryManageOpen = ref(false);

async function loadCategories() {
  try {
    const res = await getSalaryCategories();
    categories.value = res.data?.categories ?? [];
  } catch {
    categories.value = [];
  }
}

/* ── 筛选 ── */

const keyword = ref("");
const categoryFilter = ref("all");

const categorySelectOptions = computed(() => [
  { value: "all", label: "全部类别" },
  ...categories.value.map((c) => ({ value: c, label: c })),
]);

function handleResetFilters() {
  keyword.value = "";
  categoryFilter.value = "all";
  dataTable.refresh(true);
}

/* ── 列表 ── */

function ruleTextOf(item: SalaryItem): string {
  const rules = SALARY_ITEM_RULE_LABELS.filter(({ key }) => item.ext_data?.[key]).map(({ label }) => label);
  return rules.length ? rules.join(" · ") : "--";
}

const columns = computed<ColumnDef<SalaryItem>[]>(() => [
  { accessorKey: "code", header: "编码", size: 140 },
  { accessorKey: "name", header: "名称", size: 160 },
  {
    accessorKey: "category",
    header: "类别",
    size: 100,
    cell: ({ row }) =>
      h(Badge, { variant: "secondary" }, () => row.original.category),
  },
  {
    id: "rules",
    header: "规则标识",
    size: 190,
    cell: ({ row }) => h("span", { class: "text-muted-foreground" }, ruleTextOf(row.original)),
  },
  {
    accessorKey: "can_edit",
    header: "状态",
    size: 90,
    cell: ({ row }) =>
      row.original.can_edit
        ? h(Badge, { variant: "default" }, () => "启用")
        : h(Badge, { variant: "outline" }, () => "已停用"),
  },
  { accessorKey: "sort", header: "排序", size: 70 },
  {
    id: "actions",
    header: "操作",
    size: 160,
    cell: ({ row }) => {
      const item = row.original;
      const buttons = [];
      if (canWrite.value) {
        buttons.push(
          h(
            Button,
            { variant: "ghost", size: "sm", onClick: () => openFormModal(item) },
            () => "编辑",
          ),
        );
        buttons.push(
          h(
            Button,
            {
              variant: "ghost",
              size: "sm",
              onClick: () => toggleEnabled(item),
            },
            () => (item.can_edit ? "停用" : "启用"),
          ),
        );
      }
      if (canDelete.value && item.can_edit) {
        buttons.push(
          h(
            Button,
            { variant: "ghost", size: "sm", onClick: () => removeItem(item) },
            () => "删除",
          ),
        );
      }
      return h("div", { class: "flex items-center gap-1" }, buttons);
    },
  },
] as ColumnDef<SalaryItem>[]);

const dataTable = useDataTable<SalaryItem>({
  columns: columns.value,
  remoteFetchFn: async ({ page, page_size }) => {
    const res = await listSalaryItems({
      page,
      page_size,
      category: categoryFilter.value === "all" ? undefined : categoryFilter.value,
      keyword: keyword.value || undefined,
    });
    return {
      code: res.code,
      data: res.data ?? [],
      msg: res.msg,
      page: res.page || page,
      page_size: res.page_size || page_size,
      total: res.total || 0,
    };
  },
});

/* ── 编辑弹窗 ── */

const formModalOpen = ref(false);
const formItem = ref<SalaryItem | null>(null);

function openFormModal(item: SalaryItem | null = null) {
  formItem.value = item;
  formModalOpen.value = true;
}

function handleSaved() {
  dataTable.refresh();
}

async function handleCategoriesSaved() {
  await loadCategories();
  dataTable.refresh();
}

/* ── 行操作 ── */

async function toggleEnabled(item: SalaryItem) {
  const verb = item.can_edit ? "停用" : "启用";
  if (
    !(await confirmAction(
      item.can_edit
        ? `确定停用薪酬项「${item.name}」？停用后不出现在新建定薪与试算默认带出中。`
        : `确定启用薪酬项「${item.name}」？`,
    ))
  ) {
    return;
  }
  try {
    await updateSalaryItem(item.id, { can_edit: item.can_edit ? false : true });
    notifySuccess(`薪酬项已${verb}`);
    dataTable.refresh();
  } catch (error) {
    notifyError(error, getErrorMessage(error, `薪酬项${verb}失败`));
  }
}

async function removeItem(item: SalaryItem) {
  if (!(await confirmAction(`确定删除薪酬项「${item.name}」？该操作不可恢复。`))) return;
  try {
    await deleteSalaryItem(item.id);
    notifySuccess("薪酬项已删除");
    dataTable.refresh();
  } catch (error) {
    // 被定薪方案/发薪明细引用时后端拒绝删除
    notifyError(error, getErrorMessage(error, "删除失败：该薪酬项已被引用，仅可停用"));
  }
}

onMounted(() => {
  void loadCategories();
});
</script>

<template>
  <AppPage title="薪酬项" description="薪酬结构字典底座：定义项与规则元数据，定薪/试算/明细矩阵全链路消费">
    <template #actions>
      <Button
        v-if="canWrite"
        variant="outline"
        data-testid="open-category-manage"
        @click="categoryManageOpen = true"
      >
        类别字典
      </Button>
      <Button v-if="canWrite" data-testid="open-create-salary-item" @click="openFormModal(null)">
        新增薪酬项
      </Button>
    </template>

    <div class="bg-card ring-foreground/10 flex h-full min-h-0 flex-col overflow-hidden rounded-xl text-sm ring-1 shadow-sm">
      <!-- 筛选栏 -->
      <div class="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-3">
        <Select
          v-model="categoryFilter"
          trigger-class="w-36"
          :options="categorySelectOptions"
          data-testid="salary-item-category-filter"
        />
        <Input
          v-model="keyword"
          class="w-52"
          placeholder="编码/名称"
          data-testid="salary-item-keyword-input"
          @keyup.enter="dataTable.refresh(true)"
        />
        <Button variant="outline" size="sm" data-testid="salary-item-search" @click="dataTable.refresh(true)">搜索</Button>
        <Button variant="ghost" size="sm" data-testid="salary-item-filter-reset" @click="handleResetFilters">重置</Button>
      </div>

      <!-- 表格区 -->
      <div class="flex min-h-0 flex-1 flex-col px-5 pt-4">
        <DataTable :data-table="dataTable" :fixed-layout="true" />
      </div>
    </div>

    <SalaryItemFormModal
      v-model:open="formModalOpen"
      :item="formItem"
      :categories="categories"
      @saved="handleSaved"
    />
    <CategoryManageModal
      v-model:open="categoryManageOpen"
      :categories="categories"
      @saved="handleCategoriesSaved"
    />
  </AppPage>
</template>
