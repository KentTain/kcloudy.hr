# HR 子仓独立测试床（bootstrap/）

面向子仓-only 检出（本仓与主仓同级独立 clone）的独立测试闭环：隔离基础设施栈 + 一键自举 + 集成/e2e 测试。设计依据见主仓 `docs/designs/HR前后端子模块化与单容器部署的设计与实施计划.md` §4/§6。

> **职责说明**：本目录是**测试自举**，与部署无关——生产发布走 CI/CD 流水线（见根 README「发布方式」）。

## 目录

| 文件 | 说明 |
|------|------|
| `docker-compose.infra.yml` | 隔离基础设施栈：PostgreSQL（pgvector 自定义镜像，pg17+jieba+age）/ Redis / MinIO（自动建 `ai-platform` bucket）。全部数据落 tmpfs，每轮 up 即全新状态；端口取高位 15432/16379/19000 不与开发环境冲突，可经 `HR_TESTBED_{PG,REDIS,MINIO}_PORT` 覆盖 |
| `bootstrap.sh` | 一键自举：基础设施栈 → 浅克隆主仓 + 子仓内容按当前 rev 锁版本覆盖装配 → 后端 venv（`uv sync --frozen`）+ uvicorn（auto_migrate 建表 + seed + 菜单/权限码同步）→ 前端依赖 + vite dev |
| `.work/` | 自举产物（主仓浅克隆、服务日志、pid、env），已 gitignore，`--down` 时整体清除 |

## 快速开始

```bash
bootstrap/bootstrap.sh          # 全量自举并拉起前后端服务
bootstrap/bootstrap.sh --down   # 停止并清理全部自举产物
```

自举完成后（默认端口）：

- 后端 API：`http://127.0.0.1:18080`（日志 `bootstrap/.work/backend.log`）
- 前端 dev：`http://127.0.0.1:15173`（日志 `bootstrap/.work/frontend.log`）
- 种子账号：`admin` / `admin123`（console 登录字段为 `account`）

端口均可经 `HR_TESTBED_BACKEND_PORT` / `HR_TESTBED_FRONTEND_PORT` / `HR_TESTBED_PG_PORT` 覆盖（bootstrap 与 compose 同读同一组变量）。

## 跑测试

```bash
# 集成测试（登录链 + 各域 CRUD 抽样 + 权限码下发校验；未设 HR_TEST_BASE_URL 时自动跳过）
HR_TEST_BASE_URL=http://127.0.0.1:18080 python -m pytest server/tests/hr/integration -q

# e2e（Playwright 金路径：登录 → 花名册 → CRUD → 退出）
cd .work/kcloudy.ai-platform/web/vue
E2E_BASE_URL=http://127.0.0.1:15173 pnpm exec playwright test --config tests/hr/e2e/playwright.config.ts
```

单测（不依赖测试床）：

```bash
python -m pytest server/tests/hr/unit -q                 # 后端
cd web/tests/hr && pnpm install && pnpm vitest run       # 前端
```

## 装配模型要点

- 主仓以 `--depth 1` 浅克隆到 `bootstrap/.work/`，submodule 挂载点 `server/python/src/modules/hr` 随后被子仓内容**按当前 rev 覆盖装配**（rsync `--delete`，排除 `.git`/`bootstrap/`）——被测代码版本由子仓 HEAD 锁定，与主仓 gitlink 记录值解耦，便于「子仓任意提交即时可测」。
- 后端迁移与 seed 由启动期 `SQLALCHEMY_AUTO_MIGRATE=true` 完成（建表 + 各模块 seed + 菜单/权限码同步），bootstrap 不单独跑迁移命令。
- 基础设施栈与本机开发栈完全隔离（独立网络 + 高位端口 + tmpfs），但 bootstrap 亦可在仅有开发库（无 docker）环境变通使用：手工建临时库后按 `bootstrap/.work/testbed.env` 的键值注入后端环境变量即可（详见设计文档 §6.2）。

## 注意

- 主仓克隆走 SSH（`git@gitee.com:kenttian/kcloudy.ai-platform.git`），需先配好本机 SSH key。
- `.work/` 已存在时重复执行 bootstrap **不会**重新 pull 主仓（浅克隆停留在首次时点）；主仓有新提交需先 `bootstrap/bootstrap.sh --down` 清理后重跑（或手工 `git -C bootstrap/.work/kcloudy.ai-platform pull`）。
- 本环境无 docker 时 `bootstrap.sh` 不可全量运行（C5 子仓-only 演练挂账真机），但 compose/env/流程已静态验证。
