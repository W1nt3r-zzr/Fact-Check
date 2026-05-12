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
from services.search import _build_search_plan, _detect_search_preference, _do_search, _filter_irrelevant_results, _run_search_plan, SearchFetchResult


class SearchRulesTests(unittest.TestCase):
    def test_general_public_claim_defaults_to_freshness_without_year_filter(self):
        claim = "小米汽车 SU7 销量突破 10 万台"

        self.assertEqual(_detect_search_preference(claim), "freshness")

        plan = _build_search_plan(claim)

        self.assertGreaterEqual(len(plan), 2)
        self.assertEqual(plan[0].query, "小米汽车 SU7 销量突破 10 万台")
        self.assertIsNone(plan[0].recency_filter)
        self.assertTrue(any(item.query == '"小米汽车 SU7 销量突破 10 万台"' for item in plan))
        self.assertTrue(any(item.recency_filter == "month" for item in plan))
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

    def test_disclosure_case_claim_expands_to_context_and_case_synonym_queries(self):
        claim = "警方解密湾仔双尸案"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("重案解密" in query and "湾仔双尸案" in query for query in queries))
        self.assertTrue(any("湾仔双尸案" in query and "披露" in query for query in queries))
        self.assertTrue(any("湾仔豪宅双尸案" in query for query in queries))

    def test_case_progress_claim_expands_to_background_and_latest_queries(self):
        claim = "重庆姐弟坠亡案有最新进展"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("重庆姐弟坠亡案" in query and "最新进展" in query for query in queries))
        self.assertTrue(any("重庆姐弟坠亡案" in query and "案情回顾" in query for query in queries))

    def test_rumor_response_claim_expands_to_rumor_origin_queries(self):
        claim = "官方回应某品牌创始人跑路传闻"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("某品牌创始人跑路传闻" in query and "官方回应" in query for query in queries))
        self.assertTrue(any("某品牌创始人跑路传闻" in query and "网传" in query for query in queries))

    def test_old_news_resurface_claim_expands_to_debunk_and_original_queries(self):
        claim = "网传北京地铁事故为旧闻新传"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("北京地铁事故" in query and "旧闻新传" in query for query in queries))
        self.assertTrue(any("北京地铁事故" in query and "原始报道" in query for query in queries))

    def test_bizarre_video_claim_expands_to_origin_and_cross_language_queries(self):
        claim = "三亚游泳耳朵里爬出螃蟹"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertIn("耳朵 螃蟹 游泳 原视频", queries)
        self.assertIn("螃蟹 耳朵 浮潜", queries)
        self.assertIn("crab ear snorkeling", queries)
        self.assertIn("crab crawls out of ear", queries)
        self.assertTrue(any(query == "三亚 游泳 耳朵 螃蟹" for query in queries))

    def test_price_claim_without_time_word_defaults_to_freshness_preference(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"

        self.assertEqual(_detect_search_preference(claim), "freshness")

        plan = _build_search_plan(claim)

        self.assertTrue(any(item.recency_filter == "month" for item in plan))
        self.assertTrue(any("最新消息" in item.query for item in plan))

    def test_legal_finality_claim_expands_to_resolution_synonym_queries(self):
        claim = "黄子佼藏未成年性影像终审"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("最高法院" in query and "黄子佼" in query for query in queries))
        self.assertTrue(any("驳回" in query and "上诉" in query for query in queries))
        self.assertTrue(any("定谳" in query or "定讞" in query for query in queries))
        self.assertTrue(any(item.recency_filter == "month" and "最高法院" in item.query for item in plan))

    def test_legal_charge_claim_expands_to_prosecution_synonym_queries(self):
        claim = "某艺人因持有未成年性影像被起诉"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("检方" in query and "起诉" in query for query in queries))
        self.assertTrue(any("公诉" in query or "法院" in query for query in queries))
        self.assertTrue(any(item.recency_filter == "month" and "起诉" in item.query for item in plan))

    def test_legal_sentencing_claim_expands_to_judgment_synonym_queries(self):
        claim = "黄子佼未成年性影像案二审改判缓刑"

        plan = _build_search_plan(claim)
        queries = [item.query for item in plan]

        self.assertTrue(any("高院" in query or "高等法院" in query for query in queries))
        self.assertTrue(any("判决" in query or "宣判" in query for query in queries))
        self.assertTrue(any(item.recency_filter == "month" and "缓刑" in item.query for item in plan))

    def test_health_claim_defaults_to_authority_preference(self):
        self.assertEqual(_detect_search_preference("热柠檬水能杀癌细胞"), "authority")

    def test_legal_explanation_claim_defaults_to_authority_preference(self):
        self.assertEqual(_detect_search_preference("个人信息保护法如何规定个人敏感信息"), "authority")

    def test_common_knowledge_claim_keeps_relevance_preference(self):
        claim = "水在0度会结冰吗"

        self.assertEqual(_detect_search_preference(claim), "relevance")

        plan = _build_search_plan(claim)

        self.assertFalse(any(item.recency_filter == "month" for item in plan))

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

    def test_do_search_does_not_treat_crawl_time_as_publish_date(self):
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
                                    "name": "历史页面被重新抓取",
                                    "url": "https://example.com/old-page",
                                    "summary": "敦煌鸣沙山顶矿泉水只卖2元，历史游客记录。",
                                    "siteName": "测试媒体",
                                    "datePublished": None,
                                    "dateLastCrawled": date.today().isoformat(),
                                }
                            ],
                            "totalEstimatedMatches": 1,
                        }
                    }
                },
            )

        with patch("services.search.httpx.AsyncClient.post", new=AsyncMock(return_value=build_response())):
            results = asyncio.run(_do_search("敦煌鸣沙山顶矿泉水只卖2元", None, None))

        self.assertEqual(len(results.items), 1)
        self.assertEqual(results.items[0].date_published, "")

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

        self.assertEqual([item.url for item in filtered], ["https://example.com/fresh"])

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

        self.assertEqual([item.url for item in filtered], ["https://example.com/fresh"])

    def test_event_claim_drops_undated_history_even_if_core_terms_match(self):
        claim = "中国女子巴塞罗那街头遇害"
        undated_history = SearchResult(
            name="历史回顾：中国女子在巴塞罗那街头遇害案件",
            url="https://example.com/history",
            summary="中国女子巴塞罗那街头遇害，历史案件回顾与海外安全提醒。",
            date_published="",
            source="example",
        )
        fresh = SearchResult(
            name="中国女子巴塞罗那街头遇害 中国驻巴塞罗那总领馆回应",
            url="https://example.com/fresh",
            summary="中国女子巴塞罗那街头遇害，嫌疑人已被逮捕，总领馆介入事件。",
            date_published=(date.today() - timedelta(days=3)).isoformat(),
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [undated_history, fresh], min_relevance=0.2)

        self.assertEqual([item.url for item in filtered], ["https://example.com/fresh"])

    def test_disclosure_case_claim_keeps_high_relevance_historical_background(self):
        claim = "警方解密湾仔双尸案"
        fresh_disclosure = SearchResult(
            name="香港重案解密 湾仔双尸案首次披露",
            url="https://example.com/fresh-disclosure",
            summary="新书香港重案解密披露湾仔双尸案细节，警方人员讲述侦查过程。",
            date_published=(date.today() - timedelta(days=2)).isoformat(),
            source="example",
        )
        original_background = SearchResult(
            name="湾仔豪宅双尸案案情回顾",
            url="https://example.com/original-background",
            summary="2014年湾仔豪宅双尸案，两名女子遇害，警方拘捕涉案人员。",
            date_published="2014-11-02",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [fresh_disclosure, original_background],
            min_relevance=0.2,
        )

        self.assertEqual(
            [item.url for item in filtered],
            ["https://example.com/fresh-disclosure", "https://example.com/original-background"],
        )

    def test_case_progress_claim_keeps_high_relevance_case_background(self):
        claim = "重庆姐弟坠亡案有最新进展"
        fresh_progress = SearchResult(
            name="重庆姐弟坠亡案有最新进展 最高法院核准",
            url="https://example.com/fresh-progress",
            summary="重庆姐弟坠亡案有最新进展，法院发布案件执行信息。",
            date_published=(date.today() - timedelta(days=2)).isoformat(),
            source="example",
        )
        old_background = SearchResult(
            name="重庆姐弟坠亡案案情回顾",
            url="https://example.com/old-background",
            summary="2021年重庆姐弟坠亡案一审宣判，案情显示两名儿童坠亡。",
            date_published="2021-12-28",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [fresh_progress, old_background],
            min_relevance=0.2,
        )

        self.assertEqual(
            [item.url for item in filtered],
            ["https://example.com/fresh-progress", "https://example.com/old-background"],
        )

    def test_rumor_response_claim_keeps_original_rumor_context(self):
        claim = "官方回应某品牌创始人跑路传闻"
        fresh_response = SearchResult(
            name="官方回应某品牌创始人跑路传闻",
            url="https://example.com/fresh-response",
            summary="官方回应某品牌创始人跑路传闻，称相关网传信息不实。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )
        original_rumor = SearchResult(
            name="网传某品牌创始人跑路",
            url="https://example.com/original-rumor",
            summary="此前网传某品牌创始人跑路，引发用户讨论。",
            date_published="2025-10-01",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [fresh_response, original_rumor],
            min_relevance=0.2,
        )

        self.assertEqual(
            [item.url for item in filtered],
            ["https://example.com/fresh-response", "https://example.com/original-rumor"],
        )

    def test_old_news_resurface_claim_keeps_original_old_report(self):
        claim = "网传北京地铁事故为旧闻新传"
        fresh_debunk = SearchResult(
            name="网传北京地铁事故为旧闻新传 官方辟谣",
            url="https://example.com/fresh-debunk",
            summary="网传北京地铁事故为旧闻新传，官方称近期未发生相关事故。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )
        original_report = SearchResult(
            name="北京地铁事故原始报道",
            url="https://example.com/original-report",
            summary="2019年北京地铁事故原始报道，现场曾有乘客受伤。",
            date_published="2019-01-01",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [fresh_debunk, original_report],
            min_relevance=0.2,
        )

        self.assertEqual(
            [item.url for item in filtered],
            ["https://example.com/fresh-debunk", "https://example.com/original-report"],
        )

    def test_bizarre_video_claim_keeps_old_original_video_context(self):
        claim = "三亚游泳耳朵里爬出螃蟹"
        fresh_repost = SearchResult(
            name="三亚游泳耳朵里爬出了螃蟹 全网调侃厚礼蟹",
            url="https://example.com/fresh-repost",
            summary="三亚亚龙湾一名游客游泳时，一只活螃蟹从其耳道自行爬出。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )
        original_video = SearchResult(
            name="Crab crawls out of snorkeler's ear in San Juan Puerto Rico",
            url="https://example.com/original-video",
            summary="A tiny crab crawled out of a snorkeler's ear after swimming near San Juan, Puerto Rico in 2022.",
            date_published="2022-09-08",
            source="example",
        )

        filtered = _filter_irrelevant_results(
            claim,
            [fresh_repost, original_video],
            min_relevance=0.2,
        )

        self.assertEqual(
            [item.url for item in filtered],
            ["https://example.com/fresh-repost", "https://example.com/original-video"],
        )

    def test_month_expansion_query_does_not_drop_relevant_event_results_missing_month_words(self):
        claim = "中国女子巴塞罗那街头遇害"
        plan = _build_search_plan(claim)
        month_query = next(item for item in plan if item.recency_filter == "month")
        relevant = SearchResult(
            name="中国女子巴塞罗那街头遇害 嫌疑人被捕",
            url="https://example.com/barcelona-case",
            summary="中国女子在巴塞罗那街头遇害，嫌疑人已被当地警方逮捕，中国驻巴塞罗那总领馆介入。",
            date_published=(date.today() - timedelta(days=2)).isoformat(),
            source="example",
        )

        async def fake_do_search(query, _unused_client=None, recency_filter=None):
            if query == month_query.query:
                return SearchFetchResult(items=[relevant], estimated_total=1)
            return SearchFetchResult(items=[], estimated_total=0)

        with patch("services.search._do_search", new=AsyncMock(side_effect=fake_do_search)):
            run = asyncio.run(_run_search_plan(plan))

        self.assertEqual([item.url for item in run.items], ["https://example.com/barcelona-case"])

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

    def test_price_claim_drops_undated_results_even_if_core_terms_match(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"
        undated = SearchResult(
            name="undated",
            url="https://example.com/undated",
            summary="敦煌鸣沙山顶矿泉水只卖2元，历史游客记录。",
            date_published="",
            source="example",
        )
        fresh = SearchResult(
            name="fresh",
            url="https://example.com/fresh",
            summary="敦煌鸣沙山顶矿泉水只卖2元，景区回应称属实。",
            date_published=(date.today() - timedelta(days=7)).isoformat(),
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [undated, fresh], min_relevance=0.2)

        self.assertEqual([item.name for item in filtered], ["fresh"])

    def test_time_sensitive_claim_drops_historical_year_mentions_even_with_recent_metadata(self):
        claim = "敦煌鸣沙山顶矿泉水只卖2元"
        historical = SearchResult(
            name="2018年敦煌鸣沙山顶矿泉水只卖2元历史报道",
            url="https://example.com/history",
            summary="2018年游客记录显示，敦煌鸣沙山顶矿泉水只卖2元。",
            date_published=(date.today() - timedelta(days=3)).isoformat(),
            source="example",
        )
        fresh = SearchResult(
            name="敦煌鸣沙山顶矿泉水只卖2元 景区回应",
            url="https://example.com/fresh",
            summary="敦煌鸣沙山顶矿泉水只卖2元，景区回应称该价格近期仍在执行。",
            date_published=(date.today() - timedelta(days=3)).isoformat(),
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [historical, fresh], min_relevance=0.2)

        self.assertEqual([item.url for item in filtered], ["https://example.com/fresh"])

    def test_legal_finality_claim_keeps_recent_background_when_core_terms_match(self):
        claim = "黄子佼藏未成年性影像终审"
        background = SearchResult(
            name="黄子佼持有未成年性影像案最新报道",
            url="https://example.com/background",
            summary="黄子佼因下载并持有2259部未成年性影像被起诉，此前与多名被害人和解。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )
        finality = SearchResult(
            name="黄子佼持有未成年性影像案终审定谳",
            url="https://example.com/finality",
            summary="最高法院驳回检方上诉，黄子佼缓刑定谳，全案终审确定。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [background, finality], min_relevance=0.2)

        self.assertEqual([item.url for item in filtered], ["https://example.com/finality", "https://example.com/background"])

    def test_legal_finality_claim_still_drops_stale_background_history(self):
        claim = "黄子佼藏未成年性影像终审"
        stale_background = SearchResult(
            name="黄子佼持有未成年性影像二审改判",
            url="https://example.com/stale-background",
            summary="黄子佼因下载并持有2259部未成年性影像被起诉，二审改判有期徒刑1年6个月、缓刑4年，可上诉第三审。",
            date_published=(date.today() - timedelta(days=90)).isoformat(),
            source="example",
        )
        finality = SearchResult(
            name="黄子佼持有未成年性影像案终审定谳",
            url="https://example.com/finality",
            summary="最高法院驳回检方上诉，黄子佼缓刑定谳，全案终审确定。",
            date_published=(date.today() - timedelta(days=1)).isoformat(),
            source="example",
        )

        filtered = _filter_irrelevant_results(claim, [stale_background, finality], min_relevance=0.2)

        self.assertEqual([item.url for item in filtered], ["https://example.com/finality"])


if __name__ == "__main__":
    unittest.main()
