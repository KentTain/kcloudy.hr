# HR 前端开发指南

本文件为 Claude Code 在 `src/hr/` 人力资源模块前端中工作时提供指导。后端说明见子仓 `server/src/hr/AGENTS.md`，前端测试见 `web/tests/hr/AGENTS.md`。

## 模块定位

人力资源中心前端：员工中心（员工/岗位/异动）、考勤假期、招聘管理（需求/候选人/面试/渠道）、薪酬管理（薪酬项/薪带/定薪/发薪）、报表分析、员工自助（console 层）。路由前缀 `/hr`，权限码 `hr:{resource}:{action}` 随菜单下发；员工自助/我的假期为 console 层页面（登录即可见，无权限码）。页面随设计方案阶段 7 分批交付（§7 7.1-7.12）。

## 目录职责

| 目录 | 职责 |
|------|------|
| index.ts | ModuleDescriptor（name/hr，getRoutes） |
| router/index.ts | 菜单级路由（叶子 path 与后端 module.py 菜单树对齐，契约测试双向校验） |
| pages/ | HrModuleLayout 布局壳（仅 router-view，二级导航走主侧边栏）+ 各页；未实现叶子挂 HrPlaceholderPage 占位 |
| api/ | 按子域分文件（约定见 api/shared.ts 头注释）；请求走 apiClient + ApiResponse 信封 |
| types/index.ts | 手写 interface 对齐后端 Pydantic Response（snake_case），随页面批次增量补充 |
| stores/ | 按域 `*.store.ts`（setup store 风格，`defineStore(name, () => {...})`），页面需要时再建，无模块级根 store |
| components/ | 模块专用组件（组织树筛选/漏斗阶段条/薪酬方案编辑器/明细矩阵等，随批次落地） |

## 范式与约定

- **菜单与权限**：菜单树由后端 `module.py get_module_definition()` 下发（按权限过滤），前端不做静态菜单定义；可见性/可操作性控制走路由 `meta.permissions`（全局守卫 403）+ 指令 `v-permission` + 编程式 `useUserStore().hasPermission(code)`。
- **api 取数**：`apiClient` 拦截器已解包 axios 层，直接拿 HTTP body（ApiResponse 信封）；列表信封 data 裸数组 + 顶层 total，用 `toPage()`（@/hr/api/shared）适配 DataTable。
- **列表页范式**：遵循 ui-list-page/ui-data-table skills（模板布局/高度链以技能为准）；高度链卡片必须用 ui Card，见 `web/vue/src/AGENTS.md`「组件导入规范」。
- **路由路径**：旧路径不删，一律 redirect（存量书签零 404）。

## 测试

- 契约测试 `tests/hr/module.test.ts`：模块描述符 + 路由/菜单双向一致（后端菜单源 `server/python/src/hr/module.py`）+ meta.permissions 断言。
- 编译冒烟 `tests/hr/compile-smoke.test.ts`：eager glob 强制编译全树（本环境 vue-tsc/build 不可用，vitest 为唯一编译验证面）。
- 目录结构与运行命令见 `web/tests/hr/AGENTS.md`；运行：`npx vitest run tests/hr`（cwd=web/vue）。
