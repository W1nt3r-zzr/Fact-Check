import asyncio
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import SearchResult
from services.search import _build_search_plan, _detect_search_preference, _do_search, _filter_irrelevant_results


class SearchRulesTests(unittest.TestCase):
    def test_general_claim_does_not_force_exact_match_or_year_filter(self):
        claim = "小米汽车 SU7 销量突破 10 万台"

        plan = _build_search_plan(claim)

        self.assertGreaterEqual(len(plan), 2)
        self.assertEqual(plan[0].query, "小米汽车 SU7 销量突破 10 万台")
        self.assertIsNone(plan[0].recency_filter)
        self.assertTrue(any(item.query == '"小米汽车 SU7 销量突破 10 万台"' for item in plan))
        self.assertFalse(any(item.recency_filter == "year" for item in plan))

    def test_recent_claim_uses_month_filter_instead_of_global_year_filter(self):
        claim = "今天上海迪士尼临时闭园了吗"

        plan = _build_search_plan(claim)

        self.assertEqual(plan[0].query, "上海迪士尼临时闭园")
        self.assertIsNone(plan[0].recency_filter)
        self.assertTrue(any(item.recency_filter == "month" for item in plan))
        self.assertTrue(any("最新消息" in item.query for item in plan))

    def test_event_claim_without_time_word_defaults_to_freshness_preference(self):
        claim = "雅迪爱玛等电动车品牌被约谈"

        self.assertEqual(_detect_search_preference(claim), "freshness")

        plan = _build_search_plan(claim)

        self.assertTrue(any(item.recency_filter == "month" for item in plan))
        self.assertTrue(any("最新消息" in item.query for item in plan))

    def test_price_claim_without_time_word_defaults_to_freshness_preference(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"

        self.assertEqual(_detect_search_preference(claim), "freshness")

        plan = _build_search_plan(claim)

        self.assertTrue(any(item.recency_filter == "month" for item in plan))
        self.assertTrue(any("最新消息" in item.query for item in plan))

    def test_health_claim_defaults_to_authority_preference(self):
        self.assertEqual(_detect_search_preference("热柠檬水能杀癌细胞"), "authority")

    def test_do_search_maps_month_recency_to_bocha_freshness(self):
        captured = {}

        def build_response():
            request = httpx.Request("POST", "https://api.bocha.cn/v1/web-search")
            return httpx.Response(
                200,
                request=request,
                json={"data": {"webPages": {"value": [], "totalEstimatedMatches": 42}}},
            )

        async def fake_post(*args, **kwargs):
            captured["json"] = kwargs["json"]
            return build_response()

        with patch("services.search.httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            results = asyncio.run(_do_search("上海迪士尼临时闭园", None, "month"))

        self.assertEqual(results.items, [])
        self.assertEqual(results.estimated_total, 42)
        self.assertEqual(captured["json"]["freshness"], "oneMonth")

    def test_do_search_uses_no_limit_for_non_recent_queries(self):
        captured = {}

        def build_response():
            request = httpx.Request("POST", "https://api.bocha.cn/v1/web-search")
            return httpx.Response(
                200,
                request=request,
                json={"data": {"webPages": {"value": [], "totalEstimatedMatches": 7}}},
            )

        async def fake_post(*args, **kwargs):
            captured["json"] = kwargs["json"]
            return build_response()

        with patch("services.search.httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            results = asyncio.run(_do_search("小米汽车 SU7 销量突破 10 万台", None, None))

        self.assertEqual(results.items, [])
        self.assertEqual(results.estimated_total, 7)
        self.assertEqual(captured["json"]["freshness"], "noLimit")

    def test_do_search_treats_null_bocha_dates_as_empty_strings(self):
        def build_response():
            request = httpx.Request("POST", "https://api.bocha.cn/v1/web-search")
            return httpx.Response(
                200,
                request=request,
                json={
                    "data": {
                        "webPages": {
                            "value": [
                                {
                                    "name": "8岁伊朗男孩回到中国学校",
                                    "url": "https://example.com/news",
                                    "summary": "8岁伊朗男孩回到中国学校继续上课。",
                                    "siteName": "测试媒体",
                                    "datePublished": None,
                                    "dateLastCrawled": None,
                                }
                            ],
                            "totalEstimatedMatches": 1,
                        }
                    }
                },
            )

        with patch("services.search.httpx.AsyncClient.post", new=AsyncMock(return_value=build_response())):
            results = asyncio.run(_do_search("8岁伊朗男孩回到中国学校", None, None))

        self.assertEqual(len(results.items), 1)
        self.assertEqual(results.items[0].date_published, "")
        self.assertEqual(results.items[0].name, "8岁伊朗男孩回到中国学校")

    def test_recent_claim_prefers_fresher_results_when_relevance_is_similar(self):
        claim = "今天上海迪士尼临时闭园了吗"
        older = SearchResult(
            name="older",
            url="https://example.com/older",
            summary="上海迪士尼临时闭园 官方回应",
            date_published="2026-03-01",
            source="example",
        )
        newer = SearchResult(
            name="newer",
            url="https://example.com/newer",
            summary="上海迪士尼临时闭园 官方回应",
            date_published="2026-04-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [older, newer])

        self.assertEqual(filtered[0].name, "newer")

    def test_recent_claim_drops_stale_news_beyond_time_window(self):
        claim = "今天上海迪士尼临时闭园了吗"
        stale = SearchResult(
            name="stale",
            url="https://example.com/stale",
            summary="上海迪士尼临时闭园 官方回应",
            date_published="2025-12-01",
            source="example",
        )
        fresh = SearchResult(
            name="fresh",
            url="https://example.com/fresh",
            summary="上海迪士尼临时闭园 官方回应",
            date_published="2026-04-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [stale, fresh], min_relevance=0.2)

        self.assertEqual([item.name for item in filtered], ["fresh"])

    def test_event_claim_drops_stale_news_even_without_time_word(self):
        claim = "雅迪爱玛等电动车品牌被约谈"
        stale = SearchResult(
            name="stale",
            url="https://example.com/stale",
            summary="雅迪爱玛等电动车品牌被约谈 监管回应",
            date_published="2024-10-01",
            source="example",
        )
        fresh = SearchResult(
            name="fresh",
            url="https://example.com/fresh",
            summary="雅迪爱玛等电动车品牌被约谈 监管回应",
            date_published="2026-04-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [stale, fresh], min_relevance=0.2)

        self.assertEqual([item.name for item in filtered], ["fresh"])

    def test_price_claim_drops_stale_historical_results(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"
        stale = SearchResult(
            name="stale",
            url="https://example.com/stale",
            summary="敦煌鸣沙山顶矿泉水只卖2元 游客拍摄",
            date_published="2024-08-01",
            source="example",
        )
        fresh = SearchResult(
            name="fresh",
            url="https://example.com/fresh",
            summary="敦煌鸣沙山顶矿泉水只卖2元 景区回应",
            date_published="2026-04-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [stale, fresh], min_relevance=0.2)

        self.assertEqual([item.name for item in filtered], ["fresh"])

    def test_price_claim_requires_price_product_and_location_coverage(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"
        missing_product = SearchResult(
            name="fresh missing product",
            url="https://example.com/missing-product",
            summary="敦煌鸣沙山月牙泉景区门票110元，游客量较高。",
            date_published="2026-04-28",
            source="example",
        )
        missing_location = SearchResult(
            name="fresh missing location",
            url="https://example.com/missing-location",
            summary="多个景区矿泉水只卖2元，游客称价格实惠。",
            date_published="2026-04-28",
            source="example",
        )
        missing_price = SearchResult(
            name="fresh missing price",
            url="https://example.com/missing-price",
            summary="敦煌鸣沙山顶有矿泉水售卖，方便游客补水。",
            date_published="2026-04-28",
            source="example",
        )
        relevant = SearchResult(
            name="fresh relevant",
            url="https://example.com/relevant",
            summary="敦煌鸣沙山顶矿泉水只卖2元，景区回应称属实。",
            date_published="2026-04-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [missing_product, missing_location, missing_price, relevant],
            min_relevance=0.2,
        )

        self.assertEqual([item.name for item in filtered], ["fresh relevant"])

    def test_price_claim_does_not_backfill_with_historical_results_to_reach_target_count(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"
        fresh_date = (date.today() - timedelta(days=7)).isoformat()
        historical_date = (date.today() - timedelta(days=70)).isoformat()
        fresh_results = [
            SearchResult(
                name=f"fresh-{idx}",
                url=f"https://example.com/fresh-{idx}",
                summary=f"敦煌鸣沙山顶矿泉水只卖2元，景区回应称属实。第{idx}条",
                date_published=fresh_date,
                source="example",
            )
            for idx in range(7)
        ]
        historical_results = [
            SearchResult(
                name=f"historical-{idx}",
                url=f"https://example.com/historical-{idx}",
                summary=f"敦煌鸣沙山顶矿泉水只卖2元，历史游客记录。第{idx}条",
                date_published=historical_date,
                source="example",
            )
            for idx in range(3)
        ]

        filtered = _filter_irrelevant_results(
            claim,
            fresh_results + historical_results,
            min_relevance=0.2,
        )

        self.assertEqual([item.name for item in filtered], [f"fresh-{idx}" for idx in range(7)])


if __name__ == "__main__":
    unittest.main()
