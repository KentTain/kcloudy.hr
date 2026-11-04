"""hr 领域事件处理器

消费离职生效事件（employee_offboarded_events）：
iam 停用账号 + 移出组织 + 结果站内信回告操作人。
事件失败不阻塞异动主流程（未 ack 待重试）。
"""

import json
import logging
from typing import Any

from framework.database.dependencies import get_listener_session
from framework.tenant.context import TenantContext

_logger = logging.getLogger(__name__)


class BaseEventHandler:
    """事件处理器基类（体例对齐 iam listeners handlers）"""

    stream: str = ""

    async def handle(self, message: dict[str, Any]) -> None:
        raise NotImplementedError


class OffboardedEventHandler(BaseEventHandler):
    """离职生效事件处理器：iam 账号停用 + 移出组织 + 站内信回告"""

    stream = "employee_offboarded_events"

    async def handle(self, message: dict[str, Any]) -> None:
        try:
            data = json.loads(message.get("data", "{}"))
        except json.JSONDecodeError:
            _logger.warning(f"离职事件消息体不可解析: {message}")
            return

        tenant_id = data.get("tenant_id")
        employee_id = data.get("employee_id")
        if not tenant_id or not employee_id:
            _logger.warning(f"离职事件缺少必要字段: {data}")
            return

        user_id = data.get("user_id")
        offboard_date = data.get("offboard_date") or ""
        operator_id = data.get("operator_id")

        # 未来生效日不在此消费：账号停用随到期扫描任务在生效日触发（阶段 5 交付）
        if offboard_date and offboard_date > _today_iso():
            _logger.info(
                f"离职未到生效日，跳过账号联动: employee_id={employee_id} "
                f"offboard_date={offboard_date}"
            )
            return

        TenantContext.set_tenant_id(tenant_id)
        results: list[str] = []
        errors: list[str] = []

        from framework.clients.iam_client import get_iam_client

        client = get_iam_client()
        async with get_listener_session() as session:
            if user_id:
                try:
                    await client.disable_user(session, user_id)
                    results.append("账号已停用")
                except Exception as error:  # noqa: BLE001 单项失败不阻塞其余联动
                    _logger.error(
                        f"离职停用账号失败: user_id={user_id} error={error}"
                    )
                    errors.append("账号停用失败")

                if data.get("org_id"):
                    try:
                        await client.remove_user_from_org(session, data["org_id"], user_id)
                        results.append("已移出组织")
                    except Exception as error:  # noqa: BLE001
                        _logger.error(
                            f"离职移出组织失败: org_id={data['org_id']} "
                            f"user_id={user_id} error={error}"
                        )
                        errors.append("移出组织失败")

            try:
                notify_to = operator_id or data.get("operator_id")
                if notify_to:
                    summary = "、".join(results) if results else "无可用联动（未开通系统账号）"
                    extra = f"；异常: {'、'.join(errors)}" if errors else ""
                    await client.create_notification(
                        session,
                        tenant_id=tenant_id,
                        recipient_id=notify_to,
                        title=f"离职账号联动完成: {data.get('employee_name')}",
                        notification_type="hr",
                        content=(
                            f"员工 {data.get('employee_name')}（{data.get('employee_no')}）"
                            f"离职生效日 {offboard_date}：{summary}{extra}"
                        ),
                        link=f"/hr/employees?keyword={data.get('employee_no')}",
                    )
                    results.append("站内信已回告")
            except Exception as error:  # noqa: BLE001
                _logger.error(f"离职联动站内信回告失败: {error}")
                errors.append("站内信回告失败")

        _logger.info(
            f"离职事件联动完成: employee_id={employee_id} "
            f"results={results} errors={errors}"
        )


def _today_iso() -> str:
    from datetime import date

    return date.today().isoformat()
