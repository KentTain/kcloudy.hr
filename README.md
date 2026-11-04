# kcloudy.hr

HR 业务模块独立子仓（AI Platform 的首个业务模块 submodule 试点），目录体例与主仓一致（`server/` 后端 + `web/` 前端），承载 hr 前后端源码与测试。

## 远端

| 远端 | 地址 | 用途 |
|------|------|------|
| origin（主） | git@gitee.com:kenttian/kcloudy.hr.git | 主仓 `.gitmodules` 登记口径 |
| github（镜像） | git@github.com:KentTain/kcloudy.hr.git | 镜像同步，每次提交后双推 |

```bash
git push origin main && git push github main
```

## 目录结构

```text
kcloudy.hr/
├── server/                  # 后端（与主仓体例一致）
│   ├── src/hr/              # Python 包根（controllers/services/models/schemas/
│   │                        #   tasks/listeners/common/integration/migrations）
│   └── tests/hr/            # 后端 unit/integration 测试（conftest 布局自适应）
├── web/                     # 前端（与主仓体例一致）
│   ├── src/hr/              # 前端源码（index.ts api/ pages/ router/ types/ components/ utils/）
│   └── tests/hr/            # 前端 unit 测试 + e2e（批 C）
├── testbed/                 # 独立测试自举（批 C：bootstrap.sh + compose 隔离栈）
├── AGENTS.md                # 开发导航（分层规范/纪律/测试）
├── README.md
└── pytest.ini               # 子仓独立检出时的 pytest 配置
```

## 主仓集成形态

主仓以 submodule 中性挂载本仓于 `server/python/src/modules/hr`，并经三个 git symlink 映射回原路径（import/构建/测试工具链零改动）：

- 后端：`server/python/src/hr -> modules/hr/server/src/hr`（`import hr` 路径不变）
- 前端源码：`web/vue/src/hr -> ../../../server/python/src/modules/hr/web/src/hr`
- 前端测试：`web/vue/tests/hr -> ../../../server/python/src/modules/hr/web/tests/hr`

**开发现场纪律**：日常开发在主仓挂载点内进行；本仓同级独立检出仅用于 testbed 与脱离主仓的验证。修改本仓后必须先双远端推送、再在主仓 bump gitlink。

## 环境要求

| 环境 | 要求 |
|------|------|
| Windows | Developer Mode 开启 + `git config --global core.symlinks true`（clone 时生效；否则三个 symlink 均降级为文本文件，前后端本地开发均不可用） |
| 依赖 | 后端依赖由主仓 `server/python` venv（uv.lock）提供；前端依赖由主仓 `web/vue/node_modules`（pnpm）提供——本仓不自建依赖清单 |

## 测试命令

```bash
# 后端（主仓 venv；主仓工作区内运行或本仓独立检出均可）
python -m pytest server/tests/hr -q

# 前端 unit（主仓工作区内，经 symlink 呈现）
cd web/vue && pnpm exec vitest run tests/hr

# 独立测试床（子仓-only 检出，批 C 交付）
testbed/bootstrap.sh
```

## CI/CD 发布流水线

`.github/workflows/release.yml`（GitHub Actions，合并至 `main` 触发）：

1. **build-push**（自动）：拉主仓（Gitee token）→ 子仓内容 tar 装配至主仓挂载点（等价 bootstrap.sh rsync 语义，被测代码由子仓 HEAD 锁定）→ `docker build --target production-hr-web` → push 双 tag `vYYYYMMDD.<run_number>` + `latest` 至阿里云 registry。
2. **deploy-master**（需人工审批）：GitHub Environment `production` 保护规则闸门——批准后于 master 本地执行 publish 编排同步、`.env.node-hr` VERSION bump、`pull` + `up -d hr-api`，健康检查双检（8090 uvicorn / 8091 内嵌 nginx）。

前置配置见 workflow 文件头注释（一次性）：GitHub Environments `production` + Required reviewers、Secrets（`GITEE_TOKEN` / `ALIYUN_REGISTRY_USER` / `ALIYUN_REGISTRY_PASS`）、master 安装 self-hosted runner（需 docker 权限）。回滚：master `deploy/.env.node-hr` 的 `VERSION` 改回旧 tag 后 `up -d hr-api`。
