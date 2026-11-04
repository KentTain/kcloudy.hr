"""合同到期扫描任务

每日扫描：① 生效中且截止日已过的合同自动置 expired；
② 开启到期提醒且 30 天内到期、未推送过的合同，向租户 hrAdmin 角色用户推站内信。
分布式锁防多实例重复触发；任务会话无租户上下文，租户过滤经显式条件承载。
"""

from datetime import date, timedelta

from loguru import logger
from sqlalchemy import select

from framework.database.dependencies import get_task_session
from framework.lock.factory import get_lock_provider

_logger = logger.bind(name=__name__)

CONTRACT_EXPIRY_LOCK_KEY = "lock:hr:contract-expiry"
CONTRACT_EXPIRY_LOCK_TTL_SECONDS = 300
REMIND_DAYS_BEFORE = 30
# 通知目标：hr 模块默认角色「人力资源管理员」
NOTIFY_ROLE_CODE = "hrAdmin"


async def run_contract_expiry_task() -> None:
    """合同到期扫描（每日一次，单一任务会话内完成扫描与推送）"""
    from framework.clients.iam_client import get_iam_client
    from framework.configs.settings import get_settings
    from hr.models import EmployeeContract

    try:
        lock_provider = get_lock_provider(get_settings().lock)
    except Exception:
        _logger.exception("合同到期任务获取锁提供者失败")
        return

    async with lock_provider.acquire_context(
        CONTRACT_EXPIRY_LOCK_KEY, ttl=CONTRACT_EXPIRY_LOCK_TTL_SECONDS, timeout=0
    ) as lock:
        if lock is None:
            _logger.info("合同到期任务已被其他实例锁定，跳过本轮")
            return

        today = date.today()
        remind_deadline = today + timedelta(days=REMIND_DAYS_BEFORE)
        expired_count = 0
        notified_count = 0
        skipped_no_recipient = 0
        failed = 0

        client = get_iam_client()
        async with get_task_session() as session:
            # ① 到期自动置 expired
            result = await session.execute(
                select(EmployeeContract).where(
                    EmployeeContract.status == "active",
                    EmployeeContract.end_date.is_not(None),
                    EmployeeContract.end_date < today,
                )
            )
            for contract in result.scalars().all():
                contract.status = "expired"
                expired_count += 1

            # ② 到期提醒（30 天窗口，expiry_notified 防重复推送）
            result = await session.execute(
                select(EmployeeContract).where(
                    EmployeeContract.status == "active",
                    EmployeeContract.expiry_remind.is_(True),
                    EmployeeContract.expiry_notified.is_(False),
                    EmployeeContract.end_date.is_not(None),
                    EmployeeContract.end_date >= today,
                    EmployeeContract.end_date <= remind_deadline,
                )
            )
            for contract in result.scalars().all():
                try:
                    recipients = await client.list_role_user_ids(
                        session, contract.tenant_id, NOTIFY_ROLE_CODE
                    )
                    if not recipients:
                        skipped_no_recipient += 1
                        _logger.warning(
                            f"合同到期提醒无通知目标: contract={contract.contract_no} "
                            f"tenant={contract.tenant_id}（租户无 {NOTIFY_ROLE_CODE} 角色用户）"
                        )
                        contract.expiry_notified = True
                        continue
                    for recipient_id in recipients:
                        await client.create_notification(
                            session,
                            tenant_id=contract.tenant_id,
                            recipient_id=recipient_id,
                            title=f"合同即将到期: {contract.contract_no}",
                            notification_type="hr",
                            content=(
                                f"合同 {contract.contract_no} 将于 {contract.end_date} 到期，"
                                f"请及时处理续签或终止。"
                            ),
                            link="/hr/employees",
                        )
                    contract.expiry_notified = True
                    notified_count += 1
                except Exception as error:  # noqa: BLE001 单合同失败不阻塞整轮
                    failed += 1
                    _logger.error(
                        f"合同到期提醒失败: {contract.contract_no} error={error}"
                    )

        _logger.info(
            "合同到期扫描完成: 到期置 expired={} 提醒推送={} 无通知目标={} 失败={}",
            expired_count,
            notified_count,
            skipped_no_recipient,
            failed,
        )
