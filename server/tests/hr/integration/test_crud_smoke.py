"""各业务域 CRUD 抽样冒烟（首轮从窄：花名册/岗位/薪酬项三域，用例内自清理）。"""

from datetime import date
import uuid

import httpx

API = "/hr/admin/v1"


def unique_code(prefix: str) -> str:
    return f"it_{prefix}_{uuid.uuid4().hex[:8]}"


def test_employee_crud(client: httpx.Client, admin_headers):
    code = unique_code("emp")
    # 创建
    resp = client.post(
        f"{API}/employees",
        headers=admin_headers,
        json={"name": f"集成测试员工-{code}", "hire_date": str(date.today())},
    )
    assert resp.status_code == 200, resp.text
    employee_id = resp.json()["data"]["id"]

    # 列表可见
    resp = client.get(
        f"{API}/employees", headers=admin_headers, params={"keyword": code}
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1

    # 详情
    resp = client.get(f"{API}/employees/{employee_id}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == employee_id

    # 更新
    resp = client.put(
        f"{API}/employees/{employee_id}",
        headers=admin_headers,
        json={"name": f"集成测试员工改名-{code}"},
    )
    assert resp.status_code == 200, resp.text

    # 删除守卫：在职员工不可删（离职态须经异动办理），验证业务规则生效；
    # 记录留临时库随库销毁（testbed tmpfs / 临时库重建）
    resp = client.delete(f"{API}/employees/{employee_id}", headers=admin_headers)
    assert resp.status_code == 409, resp.text


def test_position_crud(client: httpx.Client, admin_headers):
    code = unique_code("pos")
    resp = client.post(
        f"{API}/positions",
        headers=admin_headers,
        json={"code": code, "name": f"集成测试岗位-{code}"},
    )
    assert resp.status_code == 200, resp.text
    position_id = resp.json()["data"]["id"]

    try:
        resp = client.get(f"{API}/positions", headers=admin_headers)
        assert resp.status_code == 200

        resp = client.get(f"{API}/positions/{position_id}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["data"]["code"] == code
    finally:
        resp = client.delete(f"{API}/positions/{position_id}", headers=admin_headers)
        assert resp.status_code == 200


def test_salary_item_crud(client: httpx.Client, admin_headers):
    code = unique_code("si")
    resp = client.post(
        f"{API}/salary-items",
        headers=admin_headers,
        json={"code": code, "name": f"集成测试薪酬项-{code}", "category": "subsidy"},
    )
    assert resp.status_code == 200, resp.text
    item_id = resp.json()["data"]["id"]

    try:
        resp = client.get(f"{API}/salary-items", headers=admin_headers)
        assert resp.status_code == 200

        resp = client.put(
            f"{API}/salary-items/{item_id}",
            headers=admin_headers,
            json={"name": f"集成测试薪酬项改名-{code}"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        resp = client.delete(f"{API}/salary-items/{item_id}", headers=admin_headers)
        assert resp.status_code == 200
