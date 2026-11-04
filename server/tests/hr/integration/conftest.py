"""hr HTTP 集成测试 conftest（批 C3）。

面向运行态 uvicorn（testbed 自举或本机拉起），纯 httpx 不 import hr 包，
不依赖主仓 conftest。未设 HR_TEST_BASE_URL 时整目录跳过。

约定：
- 服务由 testbed/bootstrap.sh 或手工拉起（SQLALCHEMY_AUTO_MIGRATE=true
  已完成建表 + seed + 菜单/权限码同步）
- 种子账号 admin/admin123（iam seed；console 登录字段为 account）
- 落库即真实数据：目标库为一次性临时库（testbed tmpfs / 测试前重建），
  用例使用唯一后缀编码避免冲突，不做用例内清理（员工删除须经异动办理，
  冒烟口径断言其 409 守卫）
"""

import os
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("HR_TEST_BASE_URL", "").rstrip("/")
ADMIN_ACCOUNT = os.environ.get("HR_TEST_ADMIN_ACCOUNT", "admin")
ADMIN_PASSWORD = os.environ.get("HR_TEST_ADMIN_PASSWORD", "admin123")

if not BASE_URL:
    pytest.skip("HR_TEST_BASE_URL 未设置，跳过 HTTP 集成测试", allow_module_level=True)


def unique_code(prefix: str) -> str:
    return f"it_{prefix}_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as c:
        yield c


def _login(c: httpx.Client, account: str, password: str) -> httpx.Response:
    return c.post(
        "/iam/console/v1/auth/login",
        json={"account": account, "password": password},
    )


@pytest.fixture(scope="session")
def admin_headers(client: httpx.Client) -> dict[str, str]:
    resp = _login(client, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    assert resp.status_code == 200, f"种子管理员登录失败: {resp.text}"
    token = resp.json()["data"]["access_token"]
    # 种子管理员挂在默认租户（UUID 零值），admin 域接口需显式租户头
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-Id": "00000000-0000-0000-0000-000000000000",
    }
