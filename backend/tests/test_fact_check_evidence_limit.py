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


class FactCheckEvidenceLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_and_chain_use_same_ten_core_evidences(self):
        captured = {}

        def fake_build_prompt(claim, evidence_list):
            captured["prompt_count"] = len(evidence_list)
            return "prompt"

        async def fake_generate_evidence_chain(**kwargs):
            captured["chain_count"] = len(kwargs["search_results"])
            captured["top_k"] = kwargs["top_k"]
            return SimpleNamespace(
                verdict="属实",
                confidence=90.0,
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=10,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到10条证据。",
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

        with patch.object(fact_check_router, "search_with_zhipu", AsyncMock(return_value=[_result(i) for i in range(12)])), \
             patch.object(fact_check_router, "build_llm_prompt", side_effect=fake_build_prompt), \
             patch.object(
                 fact_check_router,
                 "call_llm_api",
                 AsyncMock(return_value={"reasoning": "reasoning", "verdict": "属实"}),
             ):
            response = await fact_check_router.fact_check(request)

        self.assertEqual(captured["prompt_count"], 10)
        self.assertEqual(captured["chain_count"], 10)
        self.assertEqual(captured["top_k"], 10)
        self.assertEqual(response.evidence_chain["total_evidence"], 10)

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
                confidence=90.0,
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

        with patch.object(fact_check_router, "search_with_zhipu", AsyncMock(return_value=fresh_results + stale_low_relevance)), \
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

    async def test_model_reasoning_evidence_count_is_normalized_to_core_evidence_count(self):
        async def fake_generate_evidence_chain(**kwargs):
            return SimpleNamespace(
                verdict="属实",
                confidence=90.0,
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=10,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到10条证据。",
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

        with patch.object(fact_check_router, "search_with_zhipu", AsyncMock(return_value=[_result(i) for i in range(12)])), \
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

        self.assertIn("所有10条核心证据完全相互印证", response.reasoning)
        self.assertNotIn("所有12条证据", response.reasoning)

    async def test_generic_all_evidence_phrase_is_normalized_to_core_evidence_count(self):
        async def fake_generate_evidence_chain(**kwargs):
            return SimpleNamespace(
                verdict="属实",
                confidence=90.0,
                supporting_evidence=[],
                opposing_evidence=[],
                neutral_evidence=[],
                key_findings=[],
                total_evidence=10,
                total_search_results=12,
                authoritative_sources=0,
                average_score=80.0,
                reasoning_summary="共检索到10条证据。",
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

        with patch.object(fact_check_router, "search_with_zhipu", AsyncMock(return_value=[_result(i) for i in range(12)])), \
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

        self.assertIn("所有10条核心证据均指向同一结论", response.reasoning)
        self.assertNotIn("所有证据均指向同一结论", response.reasoning)


if __name__ == "__main__":
    unittest.main()
