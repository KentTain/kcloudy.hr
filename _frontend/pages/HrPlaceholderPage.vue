<script setup lang="ts">
/**
 * HR 占位页：阶段 7 分批落地期间的叶子页面统一占位，
 * 实现某页时在 router/index.ts 将对应叶子 component 换为实际页面。
 */
import { computed } from "vue";

import { useRoute } from "vue-router";

import AppPage from "@/framework/layouts/components/AppPage.vue";

const route = useRoute();
const title = computed(() => String(route.meta.title ?? "HR"));
</script>

<template>
  <AppPage :title="title" variant="list" description="页面建设中，随阶段 7 各批次交付。">
    <div class="text-muted-foreground flex flex-1 items-center justify-center text-sm">
      敬请期待
    </div>
  </AppPage>
</template>
