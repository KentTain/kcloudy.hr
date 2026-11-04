<script setup lang="ts">
/**
 * HR 组织导航树（数据源 iam 组织接口，与 iam 组织管理页同源；
 * hr 侧仅用于筛选，组织维护在 iam）。扁平化递归渲染，支持折叠与选中高亮。
 */
import { computed, ref, watch } from "vue";

import { ChevronDown, ChevronRight } from "lucide-vue-next";

import type { OrgTreeNode } from "@/hr/types/employee";

interface FlatNode {
  org: OrgTreeNode;
  depth: number;
}

const props = defineProps<{
  organizations: OrgTreeNode[];
  selectedId?: string | null;
}>();

const emit = defineEmits<{ select: [org: OrgTreeNode] }>();

const expanded = ref<Set<string>>(new Set());
const collapsed = ref<Set<string>>(new Set());

// 首次数据到达全展开
watch(
  () => props.organizations,
  (tree) => {
    const ids: string[] = [];
    const walk = (nodes: OrgTreeNode[]) => {
      for (const node of nodes) {
        ids.push(node.id);
        if (node.children?.length) walk(node.children);
      }
    };
    walk(tree);
    expanded.value = new Set(ids);
  },
  { immediate: true },
);

const flatNodes = computed<FlatNode[]>(() => {
  const result: FlatNode[] = [];
  const walk = (nodes: OrgTreeNode[], depth: number) => {
    for (const org of nodes) {
      result.push({ org, depth });
      if (org.children?.length && !collapsed.value.has(org.id)) walk(org.children, depth + 1);
    }
  };
  walk(props.organizations, 0);
  return result;
});

function toggleCollapse(node: FlatNode, event: Event) {
  event.stopPropagation();
  const next = new Set(collapsed.value);
  if (next.has(node.org.id)) {
    next.delete(node.org.id);
  } else {
    next.add(node.org.id);
  }
  collapsed.value = next;
}

function hasChildren(node: FlatNode): boolean {
  return Boolean(node.org.children?.length);
}
</script>

<template>
  <div class="py-1" data-testid="org-nav-tree">
    <button
      v-for="node in flatNodes"
      :key="node.org.id"
      type="button"
      class="hover:bg-accent flex w-full items-center gap-1 py-1.5 pr-2 text-left text-sm"
      :class="{ 'bg-accent font-medium': selectedId === node.org.id }"
      :style="{ paddingLeft: `${8 + node.depth * 16}px` }"
      :data-testid="'org-tree-node'"
      :data-org-id="node.org.id"
      @click="emit('select', node.org)"
    >
      <span
        v-if="hasChildren(node)"
        class="text-muted-foreground hover:text-foreground inline-flex h-4 w-4 shrink-0 items-center justify-center"
        @click="toggleCollapse(node, $event)"
      >
        <ChevronDown v-if="!collapsed.has(node.org.id)" class="h-3.5 w-3.5" />
        <ChevronRight v-else class="h-3.5 w-3.5" />
      </span>
      <span v-else class="inline-block h-4 w-4 shrink-0" />
      <span class="min-w-0 flex-1 truncate">{{ node.org.name }}</span>
      <span v-if="node.org.total_member_count != null" class="text-muted-foreground text-xs">
        {{ node.org.total_member_count }}
      </span>
    </button>
  </div>
</template>
