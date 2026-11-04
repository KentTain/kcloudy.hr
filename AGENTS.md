# AGENTS.md

本文件为 Claude Code 在 hr 子仓（kcloudy.hr）中工作时提供指导。

## 仓库定位

HR 业务模块独立子仓，承载 hr 前后端源码与测试。通过 git submodule 挂载于主仓（kcloudy.ai-platform）：

| 挂载点 | 内容 | 主仓消费方式 |
|--------|------|-------------|
| `server/python/src/hr` | 本仓根（Python 包根） | gitlink（submodule），import 路径 `src.hr` 零改动 |
| `web/vue/src/hr` | `_frontend/` | git symlink `../../../server/python/src/hr/_frontend` |

## 关键纪律

| 纪律 | 说明 |
|------|------|
| 指针同步 | 改本仓必须「先 push 本仓（origin + github 双远端）、再 bump 主仓 gitlink」，禁止只做其一 |
| 依赖管理 | 不自建 pyproject/依赖清单——后端依赖统一主仓 `server/python/pyproject.toml` 依赖组 + `uv.lock`；前端依赖统一主仓 `web/vue/package.json` |
| 开发现场 | 日常开发在主仓挂载点内进行（import/HMR/测试全链零跳转）；本仓同级独立检出用于 testbed 与脱离主仓的验证 |
| 提交信息 | 中文，约定式提交（`类型(范围): 描述`） |

## 分层规范

后端（本仓根 = Python 包 `hr`）：

- `controllers/`（路由，不承载复杂逻辑）→ `services/`（业务逻辑）→ `models/`（SQLAlchemy）+ `schemas/`（Pydantic）
- 权限码在 `module.py` 用 PermissionDef 声明（`hr:资源:动作`），控制器 `require_permission` 消费
- 迁移独立 alembic：`migrations/versions/`（版本表挂模块 schema 下）
- 复用 IAM 通用能力（字典/编码规则/站内信/审计），不自建

前端（`_frontend/`）：

- `api/`（经 `@/framework/api/client` 封装）→ `pages/`（页面）+ `components/` → `router/`（path 与后端 MenuDef 一致）+ `types/`（与后端 Response Schema 对齐）

## 测试

| 层 | 位置 | 运行 |
|----|------|------|
| 后端 unit/integration | `tests/backend/`（conftest 布局自适应：主仓工作区或本仓独立检出均可跑） | `python -m pytest tests/backend -q`（主仓 venv；integration 触开发库，用例自带清理） |
| 前端 unit | `_frontend/tests/` | 主仓工作区经 symlink：`cd web/vue && pnpm test:unit -- src/hr/tests` |
| e2e | `_frontend/tests/e2e/`（批 C 新建） | testbed 自举环境 |
| 独立测试床 | `testbed/`（批 C 新建） | `testbed/bootstrap.sh` 一键自举 |

## 打包注意

主仓 hatch wheel `packages` 清单不含 hr（既有事实，Docker COPY 路径不受影响）。若未来 wheel 清单补入 hr，须同步排除 `_frontend/` 与 `tests/`（防御性要求）。
