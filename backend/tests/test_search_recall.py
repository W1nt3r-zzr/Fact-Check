import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import SearchResult
from services import search as search_module


def _result(idx: int, prefix: str = "zhipu") -> SearchResult:
    return SearchResult(
        name=f"{prefix}-title-{idx}",
        url=f"https://example.com/{prefix}/{idx}",
        summary=f"{prefix} summary {idx} 上海迪士尼临时闭园",
        date_published="2026-04-28",
        source=prefix,
    )


class SearchRecallTests(unittest.IsolatedAsyncioTestCase):
    def test_log_query_diagnostics_reports_raw_dedup_and_filtered_counts(self):
        with patch.object(search_module.logger, "info") as mocked_info:
            search_module._log_query_diagnostics(
                source="bocha",
                query='上海迪士尼临时闭园',
                recency_filter="month",
                estimated_total=128,
                raw_count=18,
                dedup_count=7,
                filtered_count=5,
                cumulative_count=22,
            )

        mocked_info.assert_called_once()
        message = mocked_info.call_args[0][0]
        self.assertIn("source=bocha", message)
        self.assertIn("query=上海迪士尼临时闭园", message)
        self.assertIn("recency=month", message)
        self.assertIn("estimated_total=128", message)
        self.assertIn("raw=18", message)
        self.assertIn("dedup=7", message)
        self.assertIn("filtered=5", message)
        self.assertIn("cumulative=22", message)

    async def test_low_recall_from_zhipu_triggers_tavily_supplement(self):
        zhipu_batches = [[_result(1), _result(2)]]
        tavily_batches = [
            [_result(101, "tavily"), _result(102, "tavily")],
            [],
        ]

        with patch.object(search_module, "_build_search_plan", return_value=[search_module.SearchPlanItem("上海迪士尼临时闭园")]), \
             patch.object(search_module, "_do_search", AsyncMock(side_effect=zhipu_batches)), \
             patch.object(search_module, "_do_tavily_search", AsyncMock(side_effect=tavily_batches)), \
             patch.object(search_module, "_filter_irrelevant_results", side_effect=lambda claim, results, min_relevance=0.2: results):
            results = await search_module.search_with_zhipu("今天上海迪士尼临时闭园了吗", object())

        self.assertEqual(len(results), 4)
        self.assertTrue(any(item.source == "tavily" for item in results))

    async def test_search_plan_does_not_stop_after_first_sufficient_batch(self):
        plan = [
            search_module.SearchPlanItem("query-1"),
            search_module.SearchPlanItem("query-2"),
        ]
        zhipu_batches = [
            [_result(i) for i in range(1, 13)],
            [_result(i) for i in range(13, 17)],
        ]

        with patch.object(search_module, "_build_search_plan", return_value=plan), \
             patch.object(search_module, "_do_search", AsyncMock(side_effect=zhipu_batches)) as mocked_search, \
             patch.object(search_module, "_do_tavily_search", AsyncMock(return_value=[])), \
             patch.object(search_module, "_filter_irrelevant_results", side_effect=lambda claim, results, min_relevance=0.2: results):
            results = await search_module.search_with_zhipu("测试召回不要过早停止", object())

        self.assertEqual(mocked_search.await_count, 2)
        self.assertEqual(len(results), 16)

    async def test_search_plan_merges_filtered_batch_not_raw_batch(self):
        plan = [search_module.SearchPlanItem("敦煌鸣沙山顶矿泉水只卖2元")]
        stale = SearchResult(
            name="历史报道：敦煌鸣沙山矿泉水2元",
            url="https://example.com/stale",
            summary="敦煌鸣沙山顶矿泉水只卖2元 游客拍摄",
            date_published="2024-08-01",
            source="example",
        )
        fresh = SearchResult(
            name="最新核查：敦煌鸣沙山顶矿泉水2元",
            url="https://example.com/fresh",
            summary="敦煌鸣沙山顶矿泉水只卖2元 景区回应",
            date_published="2026-04-28",
            source="example",
        )

        with patch.object(search_module, "_do_search", AsyncMock(return_value=search_module.SearchFetchResult([stale, fresh]))), \
             patch.object(search_module, "_filter_irrelevant_results", return_value=[fresh]):
            run = await search_module._run_search_plan(plan)

        self.assertEqual([item.name for item in run.items], [fresh.name])


if __name__ == "__main__":
    unittest.main()
