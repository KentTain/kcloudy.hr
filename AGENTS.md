# AGENTS.md

本文件为 Claude Code 在 hr 子仓（kcloudy.hr）中工作时提供指导。

## 仓库定位

HR 业务模块独立子仓，目录体例与主仓（kcloudy.ai-platform）一致：`server/` 后端 + `web/` 前端。通过 git submodule 中性挂载于主仓 `server/python/src/modules/hr`，主仓经三个 git symlink 将内容映射回原路径：

| 主仓路径 | 类型 | 指向（本仓内） |
|----------|------|---------------|
| `server/python/src/hr` | symlink | `modules/hr/server/src/hr` |
| `web/vue/src/hr` | symlink | `../../../server/python/src/modules/hr/web/src/hr` |
| `web/vue/tests/hr` | symlink | `../../../server/python/src/modules/hr/web/tests/hr` |

## 关键纪律

| 纪律 | 说明 |
|------|------|
| 指针同步 | 改本仓必须「先 push 本仓（origin + github 双远端）、再 bump 主仓 gitlink」，禁止只做其一 |
| 依赖管理 | 不自建 pyproject/依赖清单——后端依赖统一主仓 `server/python/pyproject.toml` 依赖组 + `uv.lock`；前端依赖统一主仓 `web/vue/package.json` |
| 开发现场 | 日常开发在主仓挂载点内进行（import/HMR/测试全链零跳转）；本仓同级独立检出用于 testbed 与脱离主仓的验证 |
| 提交信息 | 中文，约定式提交（`类型(范围): 描述`） |

## 分层规范

后端（`server/src/hr/` = Python 包 `hr`，主仓经 symlink 以 `src/hr` 呈现）：

- `controllers/`（路由，不承载复杂逻辑）→ `services/`（业务逻辑）→ `models/`（SQLAlchemy）+ `schemas/`（Pydantic）
- 权限码在 `module.py` 用 PermissionDef 声明（`hr:资源:动作`），控制器 `require_permission` 消费
- 迁移独立 alembic：`migrations/versions/`（版本表挂模块 schema 下）
- 复用 IAM 通用能力（字典/编码规则/站内信/审计），不自建

前端（`web/src/hr/`，主仓经 symlink 以 `web/vue/src/hr` 呈现）：

- `api/`（经 `@/framework/api/client` 封装）→ `pages/`（页面）+ `components/` → `router/`（path 与后端 MenuDef 一致）+ `types/`（与后端 Response Schema 对齐）

## 测试

| 层 | 位置 | 运行 |
|----|------|------|
| 后端 unit/integration | `server/tests/hr/`（conftest 布局自适应：主仓工作区或本仓独立检出均可跑） | `python -m pytest server/tests/hr -q`（主仓 venv；integration 触开发库，用例自带清理） |
| 前端 unit | `web/tests/hr/` | 主仓工作区经 symlink：`cd web/vue && pnpm exec vitest run tests/hr` |
| e2e | `web/tests/hr/e2e/`（批 C 新建） | testbed 自举环境 |
| 独立测试床 | `testbed/`（批 C 新建） | `testbed/bootstrap.sh` 一键自举 |

## 打包注意

主仓 hatch wheel `packages` 清单不含 hr（既有事实，Docker COPY 路径不受影响）。若未来 wheel 清单补入 hr，须同步排除挂载点内 `web/` 与 `server/tests/`（防御性要求）。
