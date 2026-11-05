# hr 后端测试指南

本文件为 Claude Code 在 `server/tests/hr/` 测试目录中工作时提供指导。域层规范见 [../../AGENTS.md](../../AGENTS.md)。

## 目录定位

按主仓 `server/python/tests/` 体例组织，conftest 薄镜像主仓 hr 消费面，不依赖主仓 conftest——两种布局自适应：

- **主仓工作区**（子仓挂载于 `server/python/src/modules/hr`）：向上探测 framework 兄弟层定位主仓 `src` 入 `sys.path`，`APP_CONFIG_DIR` 指向主仓 `server/config`
- **子仓独立检出**（server/web 体例）：按 `server/src` 约定定位入 `sys.path`，`APP_CONFIG_DIR` 由 testbed 注入

## 目录结构

```text
tests/hr/
├── conftest.py              # 布局自适应 + 镜像 fixtures（postgres_engine/redis_client）+ ctx 复位 autouse
├── unit/                    # 单元测试面
│   ├── services/            # Service 层单测（mock session，不触真实库），一 service 一 test 文件
│   ├── common/              # 公共工具单测（transfer 移交机制）
│   └── integration/         # 流程级集成单测：真库直跑（hr schema），pytestmark=pytest.mark.integration，
│                            #   事务内断言不 commit（回滚零清理）——假勤审批流/发薪/招聘/绩效/EAV 等跨服务流程
└── integration/             # HTTP 集成测试：登录链/权限码下发/三域 CRUD 冒烟，触开发库，用例自带清理
```

## 运行命令

```bash
# 全部（主仓 venv；主仓工作区或本仓独立检出均可）
python -m pytest server/tests/hr -q

# 仅单元测试（无外部依赖）
python -m pytest server/tests/hr/unit -q

# 流程级集成单测（触开发库，事务回滚零清理）
python -m pytest server/tests/hr/unit/integration -q

# HTTP 集成测试（需运行中的后端；未设 HR_TEST_BASE_URL 时自动跳过）
HR_TEST_BASE_URL=http://127.0.0.1:18080 python -m pytest server/tests/hr/integration -q
```

testbed 独立测试床的自举与集成/e2e 跑法见 [testbed/README.md](../../../testbed/README.md)。

## 测试规则

- 单元测试不访问真实网络/数据库/Redis；Service 单测 mock session 隔离
- 流程级集成单测（`unit/integration/`）虽在 unit 运行面，但直连真实库——命名以 `_flow_integration` 后缀标识，与纯单测区分
- HTTP 集成测试依赖服务可用性检测，不可用时跳过；测试数据用例自带清理（e2e 前缀/独立租户标记），禁止残留
- 修复 bug 先补复现测试再改实现
- 异步代码用 `@pytest.mark.asyncio`
