"""hr 子仓独立测试 conftest（薄镜像主仓 server/python/tests/conftest.py 的 hr 消费面）。

不依赖主仓 conftest，两种布局自适应：
- 主仓工作区（子仓挂载于 server/python/src/modules/hr）：向上探测 framework
  兄弟层定位主仓 src 入 sys.path，APP_CONFIG_DIR 指向 server/config
- 子仓独立检出（server/web 体例）：按 server/src 约定定位入 sys.path，
  APP_CONFIG_DIR 由 testbed 注入（批 C）

镜像 fixtures：postgres_engine / redis_client（hr 集成测试消费）+
ctx 复位 autouse（防用户上下文跨用例泄漏）。
"""

import logging
import os
import socket
import sys
from pathlib import Path

import pytest
import pytest_asyncio

HERE = Path(__file__).resolve().parent  # server/tests/hr


def _find_src_root():
    # 主仓工作区：向上探测 framework 兄弟层（src 下 hr 与 framework 等模块同层）
    for cand in HERE.parents:
        if (cand / "framework" / "__init__.py").exists():
            return cand
    # 子仓独立检出：server/tests/hr → server/src（含 hr 包）
    for cand in HERE.parents:
        if (cand / "src" / "hr" / "__init__.py").exists():
            return cand / "src"
    return None


SRC_ROOT = _find_src_root()
if SRC_ROOT and str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

os.environ.setdefault("PYTHON_SERVICE_ENV", "local")
os.environ.setdefault("TZ", "Asia/Shanghai")

if SRC_ROOT is not None and SRC_ROOT.name == "src":
    _main_config_dir = SRC_ROOT.parents[1] / "config"
    if _main_config_dir.exists():
        os.environ.setdefault("APP_CONFIG_DIR", str(_main_config_dir))

_config_dir = os.environ.get("APP_CONFIG_DIR")
if _config_dir and Path(_config_dir).exists():
    from framework.configs import init_settings

    init_settings(Path(_config_dir))

# 日志降噪（对齐主仓 conftest 口径）
for _name in ["sqlalchemy", "sqlalchemy.engine", "alembic"]:
    logging.getLogger(_name).setLevel(logging.WARNING)
    logging.getLogger(_name).propagate = False
logging.basicConfig(level=logging.WARNING, force=True)


@pytest.fixture(autouse=True)
def _reset_app_user_context():
    """每用例复位 framework.common.ctx 用户上下文（对齐主仓 conftest）。"""
    from framework.common import ctx as app_ctx

    app_ctx.clear_context()
    yield
    app_ctx.clear_context()


def _check_postgres_available(settings):
    """同步检测 PostgreSQL 服务是否可用（对齐主仓 conftest）。"""
    try:
        url = settings.sqlalchemy.url
        parts = url.split("@")[1].split("/")[0].split(":")
        host, port = parts[0], int(parts[1]) if len(parts) > 1 else 5432
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def _check_redis_available(settings):
    """同步检测 Redis 服务是否可用（对齐主仓 conftest）。"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((settings.redis.single.host, settings.redis.single.port))
        sock.close()
        return result == 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def integration_settings():
    from framework.configs import get_settings

    return get_settings()


@pytest_asyncio.fixture
async def postgres_engine(integration_settings):
    """PostgreSQL 引擎（function 作用域，每用例独立引擎）。"""
    if not _check_postgres_available(integration_settings):
        pytest.skip("PostgreSQL 服务不可用")

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        integration_settings.sqlalchemy.url,
        echo=integration_settings.sqlalchemy.echo,
        pool_pre_ping=True,
        poolclass=NullPool,
    )

    yield engine

    try:
        await engine.dispose()
    except Exception:
        pass


@pytest_asyncio.fixture
async def redis_client(integration_settings):
    """Redis 客户端（function 作用域，对齐主仓 conftest 连接管理）。"""
    if not _check_redis_available(integration_settings):
        pytest.skip("Redis 服务不可用")

    from framework.cache.redis_util import RedisUtil

    if RedisUtil.is_initialized():
        try:
            await RedisUtil.close()
        except Exception:
            pass

    await RedisUtil.init(integration_settings.redis)

    yield RedisUtil

    try:
        await RedisUtil.close()
    except Exception:
        pass
