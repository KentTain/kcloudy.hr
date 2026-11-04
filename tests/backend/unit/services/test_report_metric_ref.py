"""报表 metric_ref 口径同源单元测试：ontology 命中读目录定义 / 缺席与异常回退内置。

替身打在 framework 客户端边界（hr 唯一依赖面）。
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from hr.services.report_service import report_service

pytestmark = pytest.mark.asyncio

_CLIENT_PATH = "framework.clients.ontology_client.get_ontology_client"


def _mock_session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


async def test_metric_ref_reads_ontology_definition():
    entity = {"displayName": "目录离职率", "description": "治理目录口径说明"}
    with patch(_CLIENT_PATH) as client_factory:
        client_factory.return_value.entity_get_by_fqn = AsyncMock(return_value=entity)
        ref = await report_service._metric_ref(_mock_session(), "attrition_rate")

    assert ref.source == "ontology"
    assert ref.metric == "attrition_rate"
    assert ref.display_name == "目录离职率"
    assert ref.description == "治理目录口径说明"


async def test_metric_ref_falls_back_when_metric_missing():
    with patch(_CLIENT_PATH) as client_factory:
        client_factory.return_value.entity_get_by_fqn = AsyncMock(return_value=None)
        ref = await report_service._metric_ref(_mock_session(), "headcount_gap")

    assert ref.source == "builtin"
    assert ref.display_name == "编制缺口"


async def test_metric_ref_falls_back_on_query_error():
    with patch(_CLIENT_PATH) as client_factory:
        client_factory.return_value.entity_get_by_fqn = AsyncMock(
            side_effect=RuntimeError("ontology 不可用")
        )
        ref = await report_service._metric_ref(
            _mock_session(), "perf_rating_distribution"
        )

    assert ref.source == "builtin"
    assert ref.display_name == "绩效评级分布"
