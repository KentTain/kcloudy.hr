# hr 前端测试指南

本文件为 Claude Code 在 `web/tests/hr/` 测试目录中工作时提供指导。域层规范见 [../../AGENTS.md](../../AGENTS.md)。

## 目录结构

```text
tests/hr/
├── module.test.ts           # 契约测试：模块描述符 + 路由/菜单双向一致（后端菜单源 module.py）+ meta.permissions 断言
├── compile-smoke.test.ts    # 编译冒烟：eager glob 强制编译全树（vue-tsc/build 不可用环境的唯一编译验证面）
├── components/              # 组件测试（表单弹窗/详情抽屉/漏斗条/导入向导等，一组件一文件）
├── pages/                   # 页面测试（与 src/hr/pages/ 一一对应）
├── utils/                   # 工具函数测试（csv 等）
└── e2e/                     # Playwright 金路径：登录 → 花名册 → CRUD → 退出
    ├── fixtures.ts          # 登录/导航 fixtures
    ├── golden-path.spec.ts  # 金路径 spec
    └── playwright.config.ts # Playwright 配置（E2E_BASE_URL）
```

## 运行命令

```bash
# unit（主仓工作区内，经 symlink 呈现）
cd {主仓}/web/vue && pnpm exec vitest run tests/hr

# unit（本仓独立检出）
cd web/tests/hr && pnpm install && pnpm vitest run

# e2e（独立测试床自举环境，前置：bootstrap/bootstrap.sh 拉起前后端）
cd bootstrap/.work/kcloudy.ai-platform/web/vue
E2E_BASE_URL=http://127.0.0.1:15173 pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts
```

## 测试规则

- 契约测试与编译冒烟为两级兜底：前者守住前后端路由/权限码契约，后者守住全树可编译——新增页面/路由后两者必须通过
- 组件/页面测试与源码同构对应（`components/XxxModal.test.ts` ↔ `src/hr/components/xxx/XxxModal.vue`），新增组件随批补测试
- e2e 依赖独立测试床环境（后端 18080/前端 15173，种子账号 `admin/admin123`），端口经 `HR_TESTBED_*` 环境变量覆盖
