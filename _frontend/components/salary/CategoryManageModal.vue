<script setup lang="ts">
/**
 * 薪酬类别字典管理弹窗：类别清单增删（本地编辑，保存一次性提交租户配置）。
 * 已绑定薪酬项的类别删除由后端拒绝。
 */
import { ref, watch } from "vue";

import { Button, Input } from "@/components";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components";
import { Badge } from "@/components";

import { getErrorMessage, notifyError, notifySuccess } from "@/framework/utils/feedback";

import { updateSalaryCategories } from "@/hr/api/salary";

const open = defineModel<boolean>("open", { required: true });

const props = defineProps<{
  categories: string[];
}>();

const emit = defineEmits<{ saved: [] }>();

const submitting = ref(false);
const editing = ref<string[]>([]);
const newCategory = ref("");

watch(open, (value) => {
  if (!value) return;
  // immediate：以 open=true 初始挂载（如测试或直开场景）也完成回填
  editing.value = [...props.categories];
  newCategory.value = "";
}, { immediate: true });

function addCategory() {
  const value = newCategory.value.trim();
  if (!value) {
    notifyError(new Error("请输入类别编码"));
    return;
  }
  if (editing.value.includes(value)) {
    notifyError(new Error(`类别「${value}」已存在`));
    return;
  }
  editing.value = [...editing.value, value];
  newCategory.value = "";
}

function removeCategory(category: string) {
  editing.value = editing.value.filter((item) => item !== category);
}

async function handleSave() {
  submitting.value = true;
  try {
    await updateSalaryCategories(editing.value);
    notifySuccess("类别字典已保存");
    open.value = false;
    emit("saved");
  } catch (error) {
    notifyError(error, getErrorMessage(error, "类别字典保存失败（已绑定薪酬项的类别不可删除）"));
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <Dialog :open="open" @update:open="open = $event">
    <DialogContent class="sm:max-w-md" data-testid="category-manage-dialog">
      <DialogHeader>
        <DialogTitle>薪酬类别字典</DialogTitle>
        <DialogDescription>类别存储于租户配置；已绑定薪酬项的类别不可删除。</DialogDescription>
      </DialogHeader>
      <div class="flex flex-col gap-4">
        <div class="flex flex-wrap gap-2" data-testid="category-list">
          <Badge
            v-for="category in editing"
            :key="category"
            variant="secondary"
            class="gap-1"
          >
            {{ category }}
            <button
              type="button"
              class="hover:text-foreground"
              :data-testid="`category-remove-${category}`"
              @click="removeCategory(category)"
            >
              ×
            </button>
          </Badge>
          <span v-if="!editing.length" class="text-muted-foreground text-xs">暂无类别</span>
        </div>
        <div class="flex items-center gap-2">
          <Input
            v-model="newCategory"
            placeholder="新类别编码，如 commission"
            data-testid="category-new-input"
            @keyup.enter="addCategory"
          />
          <Button variant="outline" size="sm" data-testid="category-add" @click="addCategory">添加</Button>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" @click="open = false">取消</Button>
        <Button :disabled="submitting" data-testid="category-save" @click="handleSave">
          {{ submitting ? "保存中…" : "保存" }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
