# AGENTS.md

本文件为 Claude Code 在 hr 子仓后端目录工作时提供指导。

## 目录定位

`server/` 为 hr 模块后端（Python 技术栈）：源码 `src/hr/`（Python 包 `hr`），测试 `tests/hr/`。主仓经 symlink 以 `server/python/src/hr` 挂载，随主仓应用动态加载，不自建 venv 与依赖清单。

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI |
| ORM / 迁移 | SQLAlchemy 2.0（`Mapped`/`mapped_column`）、Alembic（模块独立迁移） |
| 配置 / 校验 | Pydantic 2.x、YAML 配置（经主仓 framework） |
| 定时任务 | APScheduler（AsyncIOScheduler） |
| 数据服务 | PostgreSQL（模块级 schema `hr` 隔离）、Redis（队列消费） |
| 测试 | pytest、pytest-asyncio |
| 依赖管理 | 主仓 `server/python/pyproject.toml` 依赖组 + `uv.lock`（本仓无 pyproject） |

## 分层架构

`controllers/`（路由，不承载复杂逻辑）→ `services/`（业务逻辑：事务边界/业务校验/跨模型协作）→ `models/`（SQLAlchemy）+ `schemas/`（Pydantic DTO）。

| 规则 | 说明 |
|------|------|
| 权限机制 | 权限码在 `src/hr/module.py` 用 PermissionDef 声明（`hr:{资源}:{动作}`），控制器 `require_permission` 消费 |
| 路由分类 | `admin`（管理端）/`console`（员工自助）/`inner`（内部接口，无认证）三分类，格式 `/{模块}/{类型}/v1/{功能}` |
| 迁移独立 | `src/hr/migrations/` 独立 alembic，版本表挂模块 schema `hr` 下 |
| 依赖边界 | 只可依赖 framework 与 tenant/iam 能力，复用 IAM 通用能力（字典/编码规则/站内信/审计），禁止自建 |
| 模型声明 | `create_module_base("hr")` 创建模块级 Base；按需复用 framework mixins（TenantMixin/AuditMixin/OwnerMixin 等） |

## 模块导航

| 目录 | 说明 | 详细文档 |
|------|------|----------|
| src/hr/ | hr 模块源码（业务域/范式/集成/任务与监听） | [src/hr/AGENTS.md](src/hr/AGENTS.md) |
| tests/hr/ | 后端 unit/integration 测试（conftest 布局自适应） | [tests/hr/AGENTS.md](tests/hr/AGENTS.md) |

## 核心命令

hr 无独立 manage.py——启动/迁移/seed 均经主仓入口（hr 随主仓应用加载，启动期 auto_migrate 建表 + seed + 菜单/权限码同步）：

```bash
# 启动后端（主仓工作区内）
cd {主仓}/server/python && uv run python manage.py runserver

# 后端测试（主仓 venv；主仓工作区或本仓独立检出均可）
python -m pytest server/tests/hr -q

# 仅单元测试（无外部依赖）
python -m pytest server/tests/hr/unit -q
```

## 开发约束

- ORM 字段用 `Mapped[...]` / `mapped_column(...)`；模型按功能域合并文件，不按单表拆分
- 迁移文件名与 revision id 用 `{序号}_{snake描述}` 格式（`001_initial_schema` 起顺延）；revision id 总长 ≤32 字符（`alembic_version.version_num` 为 varchar(32)，超长迁移事务回滚）
- `TreeNodeMixin` 的 `parent_id` 禁止加外键约束（顶级节点为虚拟值 `"root"`，库中无该记录）
- `OwnerMixin` 声明即纳入行级数据权限自动过滤；新表接入规范见主仓 `src/framework/AGENTS.md`
- 新增 Python 依赖按模块分组进主仓 `pyproject.toml`：hr 专属依赖进 `[dependency-groups]` 同名组（组名=`hr`），禁止堆公共段（Docker 镜像按模块闭包装装，堆公共段回涨体积）
- 异步测试用 `@pytest.mark.asyncio`；编写规范见 [tests/hr/AGENTS.md](tests/hr/AGENTS.md)
