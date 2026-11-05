# hr 后端模块开发指南

本文件为 Claude Code 在 `server/src/hr/`（Python 包 `hr`）中工作时提供指导。域层规范见 [../../AGENTS.md](../../AGENTS.md)，前端说明见 [../../../web/src/hr/AGENTS.md](../../../web/src/hr/AGENTS.md)。

## 模块定位

人力资源中心后端，PostgreSQL schema `hr`，声明依赖 `tenant`/`iam`（菜单与权限码经 iam 体系下发，租户上下文来自 tenant 体系）。模块声明入口 `module.py`：权限资源清单 + 一期专属动作（`hr:employee:sensitive`/`hr:payroll:confirm` 等 PermissionDef）、菜单树、路由注册、`get_base()`。

路由按 `admin`（管理端）/`console`（员工自助，登录即可见）/`inner`（内部接口，无认证）三分类，格式 `/{模块}/{类型}/v1/{功能}`。

## 目录职责

| 目录/文件 | 职责 |
|-----------|------|
| `module.py` | 模块声明：PermissionDef 清单、菜单树、`get_routers()` 路由注册、依赖声明 |
| `app.py` | 独立应用工厂（模块可独立部署） |
| `controllers/admin/` | 管理端路由，一域一文件（employee/position/attendance/leave/recruiting 四件套/salary 四件套/perf 三件套等 21 个 controller），`require_permission` 消费权限码，不承载复杂逻辑 |
| `controllers/console/` | 员工自助路由：my_leave（我的假期）/self_service（自助服务）/team（团队） |
| `controllers/inner/` | 内部接口（无认证）：agent_tools（AI Agent 工具面）/employee（跨模块员工查询）/webhook |
| `services/` | 业务逻辑，平铺一域一文件（30 个 service），事务边界与业务校验所在层 |
| `models/` | SQLAlchemy 模型按域合并：employee（员工/岗位/异动/合同/附件/EAV 字段）、attendance、leave、recruiting、salary、perf、approval、enums（枚举） |
| `schemas/` | Pydantic DTO 按域分文件（snake_case 字段与前端 types 对齐） |
| `tasks/` | 定时任务：`setup.py` 注册 APScheduler（合同到期扫描每日 08:30 / 渠道归集每 10 分钟 / 报表快照每日 07:50），任务函数在 `tasks/services/` |
| `listeners/` | 队列消费者：`services/queue/` 下 attendance/payroll/recruiting 三组 consumers，`handlers/event_handler.py` 事件处理，`setup.py` 生命周期管理 |
| `integration/` | 外部集成：招聘渠道 provider（`providers/` base + job51/liepin/zhilian）、`llm_client.py`（AI 面 LLM 调用）、`credentials.py`（凭据）、`http.py`/`errors.py`（HTTP 与错误封装） |
| `common/` | 模块公共定义：`events.py`（事件）、`transfer.py`（移交机制，配套 `*:transfer` 专属权限） |
| `migrations/` | 独立 alembic：`versions/001_initial_schema.py` 起顺延；`seeds/hr_seed.py` 种子数据 |

## 业务域与核心服务

| 业务域 | Service | 要点 |
|--------|---------|------|
| 员工中心 | employee/position/change/contract/attachment/eav_service | EAV 动态字段（field_definition + eav_service）；敏感字段权限 `hr:employee:sensitive`；批量导入 |
| 考勤假期 | attendance/attendance_import/leave/leave_request | 考勤导入（含 AI 导入）；请假冻结/释放额度、逐日考勤回写、审批拦截 |
| 招聘管理 | requisition/candidate/interview/offer/channel | 候选人合并（`hr:candidate:merge`）；渠道归集（provider 模式 + 定时同步 + 队列消费） |
| 薪酬管理 | salary_item/salary_band/salary_package/payroll | 发薪批次确认（`hr:payroll:confirm`）与代发文件导出（`hr:payroll:export`）走队列 |
| 绩效管理 | perf_cycle/perf_review | 周期/目标/评估/评级校准（`hr:perf:calibrate`） |
| 报表分析 | report/report_export/attrition_risk/nl_query | 报表快照定时刷新；自然语言查询与 AI 助手（llm_client）；报表导出 |
| 员工自助 | self_service_service | console 层：我的假期/自助申请/团队 |
| 智能辅助 | ai_assist/agent_tool_service | Agent 工具面经 `controllers/inner/agent_tools_controller.py` 暴露 |
| 平台支撑 | approval_service/tenant_initializer/ontology_provision | 审批请求（`hr:approval:*`）；租户初始化；本体供给 |

## 范式与约定

- **Service 平铺**：一域一文件（`xxx_service.py` 导出 `xxx_service` 单例），功能单一不建子目录——与主仓「功能域分目录」规范的平铺豁免形态
- **聚合与转换**：遵循主仓 `server/AGENTS.md` Service 层规范（聚合方法 `get_<entity>_detail()`、Schema `from_entity()` 纯函数、转换禁查库、禁 N+1）
- **响应信封**：ApiResponse success/paginated/fail 工厂方法（framework.common），列表信封 data 裸数组 + 顶层 total
- **移交机制**：员工/异动/审批单支持移交（`common/transfer.py`），配套 `hr:{资源}:transfer` 专属权限
- **inner 面**：仅供模块间调用，无认证；Agent 工具面是 AI 模块消费 hr 能力的统一入口
- **队列消费**：payroll 导出/渠道归集等异步面经 listeners/services/queue 消费，Redis 队列

## 数据初始化链

| 环节 | 文件 | 说明 |
|------|------|------|
| 租户初始化 | `services/tenant_initializer.py` | 经 framework TenantInitializer 注册表，创建租户时事务内执行 |
| 种子模板 | `services/hr_seed_template.py` | 初始化数据模板定义 |
| 种子数据 | `migrations/seeds/hr_seed.py` | alembic seed，启动期 auto_migrate 链路执行 |

## 测试

单元/集成测试位于 `server/tests/hr/`，运行命令与编写规范见 [../../tests/hr/AGENTS.md](../../tests/hr/AGENTS.md)。
