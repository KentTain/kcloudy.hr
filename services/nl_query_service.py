"""NL 问数服务（报表自然语言问数，白名单指标）

流程：自然语言问题 → 指标映射（关键词规则优先，歧义/未命中时 llm_chat 输出
JSON {domain, metric, params}）→ 白名单校验（越界拒绝不猜指标）→ 调
report_service 取数（仅聚合口径，不做自由 SQL 不返回明细行）→ llm_chat 生成
自然语言回答。LLM 失败降级为结构化数据 + 固定模板文案（不编造数字）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from framework.common.exceptions import BadRequestError

from hr.integration.llm_client import llm_chat

_logger = logger.bind(name=__name__)


@dataclass
class MetricDef:
    """白名单指标定义（口径说明与取数通道）"""

    domain: str
    metric: str
    name: str
    keywords: tuple[str, ...]
    metric_ref: str


@dataclass
class ResolvedMetric:
    """一次问数的解析结果"""

    definition: MetricDef
    params: dict = field(default_factory=dict)
    source: str = "keyword"  # keyword / llm

    @property
    def label(self) -> str:
        return self.definition.name


# ── 白名单指标（与 ontology 治理目录同源口径，metric_ref 供回答附注）──

_METRICS: dict[tuple[str, str], MetricDef] = {
    (d, m): MetricDef(domain=d, metric=m, name=name, keywords=kw, metric_ref=ref)
    for d, m, name, kw, ref in [
        (
            "personnel",
            "headcount",
            "在编人数",
            ("在编", "在职", "多少人", "人数", "headcount"),
            "在编 = status ∈ {probation, regular}，含组织子树口径",
        ),
        (
            "personnel",
            "turnover_rate",
            "离职率",
            ("离职率", "流失率", "离职人数", "走了多少", "turnover"),
            "离职率 = 当月离职人数 / 当月平均在编（月初+月末均值），百分数",
        ),
        (
            "personnel",
            "headcount_trend",
            "在编趋势",
            ("趋势", "增长", "规模变化"),
            "在编趋势由员工主档生命周期（hire_date/offboard_date）按月月末回算",
        ),
        (
            "recruiting",
            "funnel",
            "招聘漏斗",
            ("漏斗", "招聘进展", "招聘情况", "投递", "funnel"),
            "漏斗按投递申请计，十阶段口径与候选人页统计卡同源",
        ),
        (
            "compensation",
            "comp_dist",
            "薪酬分布",
            ("薪酬分布", "薪资分布", "薪酬水平", "薪资水平", "工资分布"),
            "薪酬分布 = 当期生效定薪按员工月度总额聚合，仅 min/mid/max 脱敏口径",
        ),
        (
            "performance",
            "perf_summary",
            "绩效分布",
            ("绩效", "评级", "考核", "performance"),
            "绩效分布 = closed 周期评级分布（calibrated_rating 优先回退 rating）",
        ),
    ]
}

_MAX_MONTHS = 12


class NlQueryService:
    """NL 问数：白名单指标映射 + 聚合取数 + 自然语言回答"""

    # ── 对外主流程 ──

    async def ask(
        self,
        session: AsyncSession,
        question: str,
        *,
        can_salary: bool = True,
    ) -> dict:
        """问数主流程；白名单外抛 BadRequestError（400 提示不支持）。"""
        question = (question or "").strip()
        if not question:
            raise BadRequestError("问题不能为空")

        resolved = await self.resolve_metric(question)
        if resolved is None:
            raise BadRequestError(
                "该问题不在支持的指标范围内（仅支持在编/离职率/招聘漏斗/薪酬分布/绩效分布等聚合指标）"
            )

        params = {**resolved.params}
        if resolved.definition.domain == "compensation" and not can_salary:
            return self._degraded_answer(
                resolved,
                skipped_reason="薪酬分布查询需要薪酬查看权限（hr:salary_package:read），已跳过该指标",
            )

        try:
            data = await self._fetch(session, resolved)
        except Exception as exc:  # noqa: BLE001 — 取数失败走降级文案
            _logger.warning(f"NL 问数取数失败 metric={resolved.label}: {exc}")
            raise BadRequestError("指标取数失败，请稍后重试") from exc

        narrative = await self._narrate(question, resolved, data)
        return {
            "metric": resolved.label,
            "domain": resolved.definition.domain,
            "metric_ref": resolved.definition.metric_ref,
            "source": resolved.source,
            "data": data,
            "answer": narrative,
        }

    # ── 指标映射 ──

    async def resolve_metric(self, question: str) -> ResolvedMetric | None:
        """关键词规则优先；未命中走 llm_chat JSON 映射（失败/越界返回 None）。"""
        for definition in _METRICS.values():
            if any(kw in question for kw in definition.keywords):
                return ResolvedMetric(
                    definition=definition,
                    params=self._extract_params(question, definition),
                    source="keyword",
                )
        # 关键词未命中：LLM 结构化输出 {domain, metric} 映射，仍受白名单约束
        mapped = await self._llm_resolve(question)
        if mapped is None:
            return None
        definition = _METRICS.get((mapped.get("domain"), mapped.get("metric")))
        if definition is None:
            return None
        return ResolvedMetric(
            definition=definition,
            params=self._extract_params(question, definition),
            source="llm",
        )

    async def _llm_resolve(self, question: str) -> dict | None:
        """llm_chat 输出 JSON {domain, metric}；解析失败返回 None（不猜指标）。"""
        try:
            tenant_id = self._tenant_id()
        except Exception:  # noqa: BLE001 — 无租户上下文不映射
            return None
        candidates = "\n".join(
            f"- {d.domain}/{d.metric}：{d.name}" for d in _METRICS.values()
        )
        try:
            content = await llm_chat(
                tenant_id,
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 HR 报表指标映射器。将用户问题映射到唯一指标，"
                            '仅输出 JSON {"domain": "...", "metric": "..."}。'
                            "只能从候选清单中选择，无法匹配时输出 {}。\n"
                            f"候选清单：\n{candidates}"
                        ),
                    },
                    {"role": "user", "content": question},
                ],
            )
            payload = json.loads(content.strip())
        except Exception as exc:  # noqa: BLE001 — LLM 不可用/解析失败不映射
            _logger.warning(f"NL 问数 LLM 指标映射失败: {exc}")
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _extract_params(question: str, definition: MetricDef) -> dict:
        """问题中抽取时间范围月数（近 N 月 / 最近 N 个月）；缺省 6。"""
        params: dict = {}
        if definition.domain == "personnel":
            months = _extract_months(question)
            if months:
                params["months"] = months
        return params

    # ── 取数（仅聚合口径）──

    async def _fetch(
        self, session: AsyncSession, resolved: ResolvedMetric
    ) -> dict:
        from hr.services.report_service import report_service

        d, m = resolved.definition.domain, resolved.definition.metric
        if d == "personnel" and m == "headcount":
            response = await report_service.get_overview(session, months=1)
            return {
                "cards": response.cards.model_dump(),
                "org_distribution": [
                    item.model_dump() for item in response.org_distribution[:10]
                ],
            }
        if d == "personnel" and m == "turnover_rate":
            response = await report_service.get_turnover(
                session, months=resolved.params.get("months", 6)
            )
            return {"points": [point.model_dump() for point in response.points]}
        if d == "personnel" and m == "headcount_trend":
            response = await report_service.get_overview(
                session, months=resolved.params.get("months", 6)
            )
            return {
                "trend": [point.model_dump() for point in response.headcount_trend]
            }
        if d == "recruiting" and m == "funnel":
            today = date.today()
            response = await report_service.get_recruiting(
                session,
                date_from=today.replace(day=1),
                date_to=today,
            )
            return {"funnel": [item.model_dump() for item in response.funnel]}
        if d == "compensation" and m == "comp_dist":
            response = await report_service.get_comp_distribution(session)
            return {
                "by_level": [item.model_dump() for item in response.by_level],
                "by_org": [item.model_dump() for item in response.by_org],
            }
        if d == "performance" and m == "perf_summary":
            response = await report_service.get_performance(session)
            return {"cycles": [cycle.model_dump() for cycle in response.cycles]}
        raise BadRequestError("该问题不在支持的指标范围内")

    # ── 回答生成 ──

    async def _narrate(
        self, question: str, resolved: ResolvedMetric, data: dict
    ) -> str:
        """llm_chat 生成自然语言回答；失败降级固定模板文案。"""
        try:
            tenant_id = self._tenant_id()
        except Exception:  # noqa: BLE001 — 无租户上下文走降级
            return self._template_answer(resolved, data)
        try:
            content = await llm_chat(
                tenant_id,
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 HR 报表问数助手。根据给定指标数据用 150 字以内中文"
                            "回答用户问题。只允许引用数据中的数字，不得编造或推算"
                            "数据中没有的数值。末尾附一句口径说明。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"问题：{question}\n指标：{resolved.label}\n"
                            f"口径：{resolved.definition.metric_ref}\n"
                            f"数据：{json.dumps(data, ensure_ascii=False, default=str)}"
                        ),
                    },
                ],
            )
            return content.strip()
        except Exception as exc:  # noqa: BLE001 — LLM 失败降级模板
            _logger.warning(f"NL 问数回答生成失败降级模板: {exc}")
            return self._template_answer(resolved, data)

    @staticmethod
    def _template_answer(resolved: ResolvedMetric, data: dict) -> str:
        """固定模板文案（不编造数字，仅给出口径与数据提示）。"""
        return (
            f"已命中指标「{resolved.label}」：{resolved.definition.metric_ref}。"
            "结构化数据见 data 字段；智能回答生成暂不可用，请直接查看数据明细。"
        )

    def _degraded_answer(self, resolved: ResolvedMetric, *, skipped_reason: str) -> dict:
        """无权限/跳过场景的结构化回答（不调用 LLM）。"""
        return {
            "metric": resolved.label,
            "domain": resolved.definition.domain,
            "metric_ref": resolved.definition.metric_ref,
            "source": "keyword",
            "data": None,
            "answer": skipped_reason,
        }

    @staticmethod
    def _tenant_id() -> str:
        from framework.common.ctx import get_tenant_id

        tenant_id = get_tenant_id()
        if not tenant_id:
            raise BadRequestError("缺少租户上下文")
        return tenant_id


def _extract_months(question: str) -> int | None:
    """从问题中抽取「近/最近 N 月/个月」时间范围；上限 12。"""
    import re

    match = re.search(r"(?:近|最近)\s*(\d{1,2})\s*(?:个)?月", question)
    if not match:
        return None
    months = int(match.group(1))
    return max(1, min(months, _MAX_MONTHS))


nl_query_service = NlQueryService()
