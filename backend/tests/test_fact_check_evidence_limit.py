import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import FactCheckRequest, SearchResult
from routers import fact_check as fact_check_router


def _result(idx: int) -> SearchResult:
    return SearchResult(
        name=f"title-{idx}",
        url=f"https://example.com/{idx}",
        summary=f"summary {idx}",
        date_published="2026-05-01",
        source="example",
    )


def _dunhuang_result(name: str, summary: str, date_published: str) -> SearchResult:
    return SearchResult(
        name=name,
        url=f"https://example.com/{name}",
        summary=summary,
        date_published=date_published,
        source="example",
    )


def _hsw_result(name: str, path: str) -> SearchResult:
    return SearchResult(
        name=name,
        url=f"https://news.hsw.cn/{path}",
        summary=(
            "在敦煌鸣沙山月牙泉景区,爬上山顶是对人们体力的不小考验。"
            "在鸣沙山山顶新开设的一个“敦煌水局”给游客带来了惊喜:矿泉水1瓶只需要2块钱。"
        ),
        date_published="2026-05-06",
        source="华商网新闻",
    )


class FactCheckEvidenceLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_iterator_accepts_regular_sync_stream(self):
        chunks = [SimpleNamespace(value="a"), SimpleNamespace(value="b")]

        collected = []
        async for chunk in fact_check_router._iterate_llm_stream(iter(chunks)):
            collected.append(chunk.value)

        self.assertEqual(collected, ["a", "b"])

    async def test_resolve_maybe_awaitable_accepts_regular_stream_object(self):
        stream = iter([SimpleNamespace(value="chunk")])

        resolved = await fact_check_router._resolve_maybe_awaitable(stream)

        self.assertIs(resolved, stream)

    async def test_core_evidence_selection_deduplicates_same_article_in_news_columns(self):
        results = [
            _hsw_result(
                "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-要闻_华商网新闻",
                "system/2026/0506/1823456.shtml",
            ),
            _hsw_result(
                "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-社会新闻_华商网新闻",
                "system/2026/0506/1823456_2.shtml",
            ),
            _dunhuang_result(
                "敦煌文旅回应鸣沙山山顶矿泉水2元",
                "敦煌文旅方面回应称，山顶敦煌水局矿泉水售价为2元。",
                "2026-05-06",
            ),
        ]

        selected = fact_check_router._select_core_evidence("敦煌鸣沙山顶矿泉水只卖2元", results)

        self.assertEqual(
            [item.name for item in selected],
            [
                "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-要闻_华商网新闻",
                "敦煌文旅回应鸣沙山山顶矿泉水2元",
            ],
        )

    async def test_reasoning_and_chain_use_all_core_evidences_up_to_safety_cap(self):
        captured = {}

        def fake_build_prompt(claim, evidence_list):
            captured["prompt_count"] = len(evidence_list)
            return "prompt"

        async def fake_generate_evidence_chain(**kwargs):
            captured["chain_count"] = len(kwargs["search_results"])
            captured["top_k"] = kwargs["top_k"]
            return SimpleNamespace(
                verdict="属实",
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=12,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到12条证据。",
                ai_summary=None,
            )

        fact_check_router.init_dependencies(
            llm_client=object(),
            link_validator=None,
            consistency_scorer=None,
            evidence_chain_generator=SimpleNamespace(
                generate_evidence_chain=AsyncMock(side_effect=fake_generate_evidence_chain)
            ),
        )

        request = FactCheckRequest(claim="使用表情包被索赔1万元", enable_evidence_chain=True)

        with patch.object(fact_check_router, "search_evidence", AsyncMock(return_value=[_result(i) for i in range(12)])), \
             patch.object(fact_check_router, "build_llm_prompt", side_effect=fake_build_prompt), \
             patch.object(
                 fact_check_router,
                 "call_llm_api",
                 AsyncMock(return_value={"reasoning": "reasoning", "verdict": "属实"}),
             ):
            response = await fact_check_router.fact_check(request)

        self.assertEqual(captured["prompt_count"], 12)
        self.assertEqual(captured["chain_count"], 12)
        self.assertEqual(captured["top_k"], 12)
        self.assertEqual(response.evidence_chain["total_evidence"], 12)

    async def test_core_evidence_selection_keeps_safety_cap_for_large_candidate_sets(self):
        selected = fact_check_router._select_core_evidence(
            "使用表情包被索赔1万元",
            [_result(i) for i in range(35)],
        )

        self.assertEqual(len(selected), fact_check_router.CORE_EVIDENCE_LIMIT)
        self.assertEqual(fact_check_router.CORE_EVIDENCE_LIMIT, 30)

    async def test_core_evidence_selection_drops_stale_low_relevance_before_prompt_and_chain(self):
        captured = {}

        fresh_results = [
            _dunhuang_result(
                f"fresh-{idx}",
                f"敦煌鸣沙山顶矿泉水只卖2元，景区回应称属实。第{idx}条",
                "2026-05-01",
            )
            for idx in range(7)
        ]
        stale_low_relevance = [
            _dunhuang_result(
                "鸣沙山简介_鸣沙山月牙泉门票_敦煌鸣沙山游记",
                "想去 0 去过 0 景点地址: 甘肃敦煌市南郊七公里的鸣沙山北麓。",
                "2018-07-28",
            ),
            _dunhuang_result(
                "鸣沙山简介_鸣沙山月牙泉门票_敦煌鸣沙山游记-duplicate",
                "想去 0 去过 0 景点地址: 甘肃敦煌市南郊七公里的鸣沙山北麓。",
                "2018-07-28",
            ),
            _dunhuang_result(
                "敦煌 鸣沙山月牙泉攻略,看这一篇就够了_知乎",
                "鸣沙山月牙泉游玩攻略，介绍路线、门票和注意事项。",
                "2020-06-01",
            ),
        ]

        def fake_build_prompt(claim, evidence_list):
            captured["prompt_titles"] = [item.name for item in evidence_list]
            return "prompt"

        async def fake_generate_evidence_chain(**kwargs):
            captured["chain_titles"] = [item["title"] for item in kwargs["search_results"]]
            return SimpleNamespace(
                verdict="属实",
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=len(kwargs["search_results"]),
                total_search_results=10,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到7条证据。",
                ai_summary=None,
            )

        fact_check_router.init_dependencies(
            llm_client=object(),
            link_validator=None,
            consistency_scorer=None,
            evidence_chain_generator=SimpleNamespace(
                generate_evidence_chain=AsyncMock(side_effect=fake_generate_evidence_chain)
            ),
        )

        request = FactCheckRequest(claim="敦煌鸣沙山顶矿泉水只卖2元", enable_evidence_chain=True)

        with patch.object(fact_check_router, "search_evidence", AsyncMock(return_value=fresh_results + stale_low_relevance)), \
             patch.object(fact_check_router, "build_llm_prompt", side_effect=fake_build_prompt), \
             patch.object(
                 fact_check_router,
                 "call_llm_api",
                 AsyncMock(return_value={"reasoning": "reasoning", "verdict": "属实"}),
             ):
            response = await fact_check_router.fact_check(request)

        self.assertEqual(captured["prompt_titles"], [f"fresh-{idx}" for idx in range(7)])
        self.assertEqual(captured["chain_titles"], [f"fresh-{idx}" for idx in range(7)])
        self.assertEqual(response.evidence_chain["total_evidence"], 7)

    async def test_core_evidence_selection_drops_stale_history_for_exposure_event(self):
        fresh_results = [
            SearchResult(
                name=f"央视曝光电动车“续航神器”调查-{idx}",
                url=f"https://news.example.com/fresh-{idx}",
                summary=f"央视曝光电动车“续航神器”存在虚标续航、改装安全隐患，市场监管部门介入调查。第{idx}条",
                date_published="2026-05-06",
                source="新闻媒体",
            )
            for idx in range(9)
        ]
        stale_history = SearchResult(
            name="历史报道：央视曾曝光电动车续航改装乱象",
            url="https://history.example.com/ev-range-device",
            summary="2024年央视报道过电动车续航改装装置乱象，与近期“续航神器”曝光话题相似。",
            date_published="2024-03-12",
            source="历史资料",
        )

        selected = fact_check_router._select_core_evidence(
            "央视曝光电动车“续航神器”",
            fresh_results + [stale_history],
        )

        self.assertEqual(len(selected), 9)
        self.assertEqual([item.name for item in selected], [item.name for item in fresh_results])
        self.assertNotIn(stale_history.name, [item.name for item in selected])

    async def test_core_evidence_selection_prefers_authoritative_same_fact_over_early_reposts(self):
        reposts = [
            SearchResult(
                name=f"一中国女子西班牙街头被刺身亡 门户转载-{idx}",
                url=f"https://portal.example.com/repost-{idx}",
                summary="当地时间5月2日，西班牙巴塞罗那一处社区发生持刀伤人事件，一名中国女子在街头被刺身亡。",
                date_published="2026-05-06",
                source="门户网站",
            )
            for idx in range(10)
        ]
        speculative = SearchResult(
            name="中国女子在西班牙被刺身亡 现场惨烈疑割喉",
            url="https://tabloid.example.com/speculative",
            summary="网友称一名16岁的中国女孩在巴塞罗那被割喉，现场惨烈疑割喉。",
            date_published="2026-05-07",
            source="聚合资讯",
        )
        cctv = SearchResult(
            name="一名中国公民在巴塞罗那不幸遇害身亡_新闻频道_央视网",
            url="https://news.cctv.com/2026/05/05/example.shtml",
            summary="据中国驻巴塞罗那总领馆消息，当地时间5月2日，一名中国公民在巴塞罗那不幸遇害身亡。",
            date_published="2026-05-05",
            source="央视网新闻频道",
        )
        consulate = SearchResult(
            name="中国驻巴塞罗那总领馆关于领区一名中国公民不幸遇害案件的情况通报",
            url="https://barcelona.china-consulate.gov.cn/example",
            summary="当地时间5月2日，一名中国公民在巴塞罗那不幸遇害身亡。总领馆要求警方全力彻查此案。",
            date_published="2026-05-05",
            source="中国驻巴塞罗那总领馆",
        )

        selected = fact_check_router._select_core_evidence(
            "中国女子巴塞罗那街头遇害",
            reposts + [speculative, cctv, consulate],
        )

        selected_titles = [item.name for item in selected]
        self.assertIn(cctv.name, selected_titles)
        self.assertIn(consulate.name, selected_titles)
        self.assertNotIn(speculative.name, selected_titles)
        self.assertEqual(len(selected), 12)

    async def test_model_reasoning_evidence_count_is_normalized_to_core_evidence_count(self):
        async def fake_generate_evidence_chain(**kwargs):
            return SimpleNamespace(
                verdict="属实",
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=12,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到12条证据。",
                ai_summary=None,
            )

        fact_check_router.init_dependencies(
            llm_client=object(),
            link_validator=None,
            consistency_scorer=None,
            evidence_chain_generator=SimpleNamespace(
                generate_evidence_chain=AsyncMock(side_effect=fake_generate_evidence_chain)
            ),
        )

        request = FactCheckRequest(claim="使用表情包被索赔1万元", enable_evidence_chain=True)

        with patch.object(fact_check_router, "search_evidence", AsyncMock(return_value=[_result(i) for i in range(12)])), \
             patch.object(fact_check_router, "build_llm_prompt", return_value="prompt"), \
             patch.object(
                 fact_check_router,
                 "call_llm_api",
                 AsyncMock(return_value={
                     "reasoning": "### 3. 证据关系分析\n所有12条证据完全相互印证。",
                     "verdict": "属实",
                 }),
             ):
            response = await fact_check_router.fact_check(request)

        self.assertIn("所有12条核心证据完全相互印证", response.reasoning)
        self.assertNotIn("所有12条证据", response.reasoning)

    async def test_generic_all_evidence_phrase_is_normalized_to_core_evidence_count(self):
        async def fake_generate_evidence_chain(**kwargs):
            return SimpleNamespace(
                verdict="属实",
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=12,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到12条证据。",
                ai_summary=None,
            )

        fact_check_router.init_dependencies(
            llm_client=object(),
            link_validator=None,
            consistency_scorer=None,
            evidence_chain_generator=SimpleNamespace(
                generate_evidence_chain=AsyncMock(side_effect=fake_generate_evidence_chain)
            ),
        )

        request = FactCheckRequest(claim="使用表情包被索赔1万元", enable_evidence_chain=True)

        with patch.object(fact_check_router, "search_evidence", AsyncMock(return_value=[_result(i) for i in range(12)])), \
             patch.object(fact_check_router, "build_llm_prompt", return_value="prompt"), \
             patch.object(
                 fact_check_router,
                 "call_llm_api",
                 AsyncMock(return_value={
                     "reasoning": "### 3. 证据关系分析\n所有证据均指向同一结论。",
                     "verdict": "属实",
                 }),
             ):
            response = await fact_check_router.fact_check(request)

        self.assertIn("所有12条核心证据均指向同一结论", response.reasoning)
        self.assertNotIn("所有证据均指向同一结论", response.reasoning)


if __name__ == "__main__":
    unittest.main()
