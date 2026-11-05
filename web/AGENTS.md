# AGENTS.md

本文件为 Claude Code 在 hr 子仓前端目录工作时提供指导。

## 目录定位

`web/` 为 hr 模块前端：源码 `src/hr/`（Vue 业务模块，主仓经 symlink 以 `web/vue/src/hr` 挂载），测试 `tests/hr/`（主仓经 symlink 以 `web/vue/tests/hr` 挂载）。依赖统一由主仓 `web/vue/node_modules`（pnpm）提供，本仓无 package.json。

## 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | Vue 3.5 + TypeScript |
| 构建 | Vite（经主仓 web/vue 工程） |
| 路由 / 状态 | Vue Router 4、Pinia 3（setup store 风格） |
| UI 组件 | shadcn-vue（reka-ui 原语）+ Tailwind CSS v4，经主仓 `@/components` 统一入口 |
| 请求 | axios，经 `@/framework/api/client`（apiClient）封装 |
| 测试 | Vitest + @vue/test-utils、Playwright（e2e） |

## 模块导航

| 目录 | 说明 | 详细文档 |
|------|------|----------|
| src/hr/ | hr 前端源码（页面/组件/API/路由/类型） | [src/hr/AGENTS.md](src/hr/AGENTS.md) |
| tests/hr/ | 前端 unit 测试 + e2e | [tests/hr/AGENTS.md](tests/hr/AGENTS.md) |

## 依赖边界

- 业务模块（src/hr）可依赖 framework 与跨模块共享组件（`@/components`），反向禁止
- hr 不定义静态菜单：菜单树由后端 `module.py get_module_definition()` 下发（按权限过滤）
- 模块经 `index.ts` ModuleDescriptor（name=`hr`，getRoutes）注册进主仓模块系统

## 核心命令

```bash
# 前端 unit（主仓工作区内，经 symlink 呈现）
cd {主仓}/web/vue && pnpm exec vitest run tests/hr

# 本仓独立检出（web/tests/hr 自带 package.json）
cd web/tests/hr && pnpm install && pnpm vitest run

# e2e（testbed 自举环境）
cd {testbed}/.work/kcloudy.ai-platform/web/vue
E2E_BASE_URL=http://127.0.0.1:15173 pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts
```

## 开发约束

- 页面范式遵循 ui-list-page/ui-data-table 等技能（主仓 `.claude/skills/ui-*/`），模板布局/高度链以技能为准；高度链卡片必须用 ui Card
- TypeScript 手写 interface 对齐后端 Pydantic Response（snake_case），随页面批次增量补充
- 旧路由路径不删，一律 redirect（存量书签零 404）

详细模块职责与取数范式见 [src/hr/AGENTS.md](src/hr/AGENTS.md)；测试结构见 [tests/hr/AGENTS.md](tests/hr/AGENTS.md)。
