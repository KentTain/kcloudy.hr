"""权限码下发校验：启动期 iam 权限码同步后，hr:* 全量可查（21 资源 × 3 动作
+ 15 专属动作点 = 78 条，此处下限断言防同步缺失）。"""

import httpx

SPECIAL_CODES = [
    "hr:employee:sensitive",
    "hr:employee:import",
    "hr:candidate:merge",
    "hr:payroll:confirm",
    "hr:payroll:export",
    "hr:channel:sync",
    "hr:attendance:import",
    "hr:leave:approve",
    "hr:approval:read",
    "hr:approval:approve",
    "hr:perf:calibrate",
    "hr:report:export",
    "hr:leave:transfer",
    "hr:employee_change:transfer",
    "hr:approval:transfer",
]


def test_hr_permission_codes_provisioned(client: httpx.Client, admin_headers):
    resp = client.get("/iam/admin/v1/permissions", headers=admin_headers)
    assert resp.status_code == 200
    permissions = resp.json()["data"]
    codes = {p["code"] for p in permissions}

    hr_codes = {c for c in codes if c.startswith("hr:")}
    assert len(hr_codes) >= 78, f"hr 权限码下发不足: {len(hr_codes)} < 78"
    for code in SPECIAL_CODES:
        assert code in hr_codes, f"专属权限码缺失: {code}"
