"""登录链集成测试：seed 账号可登录、错密拒绝、未鉴权拦截。"""

import httpx

ADMIN_ACCOUNT = "admin"
ADMIN_PASSWORD = "admin123"


def _login(c: httpx.Client, account: str, password: str) -> httpx.Response:
    return c.post(
        "/iam/console/v1/auth/login",
        json={"account": account, "password": password},
    )


def test_login_success(client: httpx.Client):
    resp = _login(client, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["access_token"]
    assert data["token_type"] == "Bearer"


def test_login_wrong_password(client: httpx.Client):
    resp = _login(client, ADMIN_ACCOUNT, "wrong-password")
    assert resp.status_code == 401


def test_admin_endpoints_require_auth(client: httpx.Client):
    resp = client.get("/hr/admin/v1/employees")
    assert resp.status_code == 401
