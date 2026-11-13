"""
HR 模块独立应用工厂

提供 HR 模块的独立 FastAPI 应用，支持 standalone 单独部署。
"""

import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from loguru import logger

from framework.common.time import ChinaTimeZone
from framework.database.core.engine import setup_engine
from framework.tenant.middleware import TenantMiddleware
from framework.tenant.tenant_protocols import register_tenant_provider

try:
    from framework.configs import get_settings

    settings = get_settings()
except ImportError:  # pragma: no cover
    settings = None

_logger = logger.bind(name=__name__)

APP_NAME = "HR API"
start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    _logger.info(
        f"\nHR 应用开始启动... ({datetime.now(tz=ChinaTimeZone).strftime('%Y-%m-%d %H:%M:%S')})"
    )

    # 初始化数据库引擎
    sqlalchemy_config = settings.sqlalchemy
    setup_engine(
        database_url=sqlalchemy_config.url,
        echo=sqlalchemy_config.echo,
        pool_size=sqlalchemy_config.pool.size,
        max_overflow=sqlalchemy_config.pool.max_overflow,
    )

    # 注册 TenantProvider
    try:
        from tenant.services.tenant import tenant_provider_impl

        register_tenant_provider(tenant_provider_impl)
    except ImportError:
        _logger.warning("TenantProvider 不可用，跳过注册")

    yield

    _logger.info("HR 应用关闭")


def create_app() -> FastAPI:
    """创建 HR 模块独立 FastAPI 应用实例"""
    app = FastAPI(
        title=APP_NAME,
        description="AI 助手平台 HR 人力资源 API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        # OpenAPI servers：相对 /api 前缀（单容器内嵌 nginx 剥除后转发 uvicorn），
        # 接口库 URL 导入时经 urljoin(schema_url) 解析为导入域名 + /api
        servers=[{"url": "/api", "description": "hr 单容器 /api 前缀"}],
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    # 注册租户中间件
    extra_skip_paths = settings.tenant.skip_tenant_setting_path
    app.add_middleware(
        TenantMiddleware, extra_skip_paths=extra_skip_paths if extra_skip_paths else None
    )

    # 注册认证中间件（standalone 部署时校验 JWT）
    from iam.middlewares.iam_auth_middleware import IAMAuthMiddleware

    app.add_middleware(IAMAuthMiddleware)

    # 注册 HR 路由
    from hr.module import HrModule

    for router, prefix, tags in HrModule().get_routers():
        app.include_router(router, prefix=prefix, tags=tags)

    # 健康检查端点
    @app.get("/health", tags=["Health"])
    async def health():
        return {
            "status": "ok",
            "app": APP_NAME,
            "uptime": time.time() - start_time,
        }

    return app


# 模块级应用实例（用于 uvicorn 直接启动）
app = create_app()
