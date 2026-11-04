<script setup lang="ts">
/**
 * hr 模块布局壳：仅承载子路由出口。
 * 二级导航不在这里——主侧边栏（AdminLayout + AppNavMain）直接渲染后端下发的
 * hr 菜单树（4 组 16 叶，已按用户权限过滤）；各页面自组左树/页签等局部导航。
 */
</script>

<template>
  <div class="h-full min-h-0">
    <router-view />
  </div>
</template>
