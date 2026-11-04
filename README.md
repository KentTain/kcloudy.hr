# kcloudy.hr

HR 业务模块独立子仓（AI Platform 的首个业务模块 submodule 试点），承载 hr 前后端源码与测试。

## 远端

| 远端 | 地址 | 用途 |
|------|------|------|
| origin（主） | https://gitee.com/kenttian/kcloudy.hr.git | 主仓 `.gitmodules` 登记口径 |
| github（镜像） | https://github.com/KentTain/kcloudy.hr.git | 镜像同步，每次提交后双推 |

```bash
git push origin main && git push github main
```

## 目录结构

```text
kcloudy.hr/
├── __init__.py …           # Python 包根（主仓挂载点 server/python/src/hr）
├── controllers/ services/ models/ schemas/ tasks/ listeners/
├── common/ integration/ migrations/
├── _frontend/              # 前端源码（主仓经 symlink 以 web/vue/src/hr 呈现）
│   ├── index.ts api/ pages/ router/ types/ components/ utils/
│   └── tests/              # 前端 unit 测试 + e2e（批 C）
├── tests/backend/          # 后端 unit/integration 测试（conftest 布局自适应）
├── testbed/                # 独立测试自举（批 C：bootstrap.sh + compose 隔离栈）
├── AGENTS.md               # 开发导航（分层规范/纪律/测试）
└── pytest.ini              # 子仓独立检出时的 pytest 配置
```

## 主仓集成形态

- 后端：本仓根 = 主仓 `server/python/src/hr`（submodule 挂载，import 路径 `src.hr` 零改动）。
- 前端：`_frontend/` 经主仓 git symlink `web/vue/src/hr -> ../../../server/python/src/hr/_frontend` 挂入，vite dev / vitest / vue-tsc 零改动。

**开发现场纪律**：日常开发在主仓挂载点内进行；本仓同级独立检出仅用于 testbed 与脱离主仓的验证。修改本仓后必须先双远端推送、再在主仓 bump gitlink。

## 环境要求

| 环境 | 要求 |
|------|------|
| Windows | Developer Mode 开启 + `git config --global core.symlinks true`（clone 时生效；否则 `web/vue/src/hr` symlink 降级为文本文件，前端本地开发不可用） |
| 依赖 | 后端依赖由主仓 `server/python` venv（uv.lock）提供；前端依赖由主仓 `web/vue/node_modules`（pnpm）提供——本仓不自建依赖清单 |

## 测试命令

```bash
# 后端（主仓 venv；主仓工作区内运行或本仓独立检出均可）
python -m pytest tests/backend -q

# 前端 unit（主仓工作区内）
cd web/vue && pnpm test:unit -- src/hr/tests

# 独立测试床（子仓-only 检出，批 C 交付）
testbed/bootstrap.sh
```
