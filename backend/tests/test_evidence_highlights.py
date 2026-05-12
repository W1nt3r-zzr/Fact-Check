import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.evidence_chain_generator import EvidenceChainGenerator, EvidenceChainItem
from services.link_validator import LinkValidationResult
from services.evidence_ranker import RankedEvidence


class EvidenceHighlightExtractionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.generator = EvidenceChainGenerator()

    def _build_evidence(self, summary: str, stance: str = "support") -> RankedEvidence:
        return RankedEvidence(
            url="https://example.com/evidence",
            title="测试证据",
            summary=summary,
            relevance_score=95,
            authority_score=70,
            freshness_score=80,
            overall_score=88,
            rank=1,
            tier="Tier 2",
            publish_date=None,
            domain="example.com",
            stance=stance,
        )

    def _build_chain_item(self, evidence: RankedEvidence) -> EvidenceChainItem:
        return EvidenceChainItem(
            rank=evidence.rank,
            url=evidence.url,
            title=evidence.title,
            domain=evidence.domain,
            tier=evidence.tier,
            overall_score=evidence.overall_score,
            relevance_score=evidence.relevance_score,
            authority_score=evidence.authority_score,
            freshness_score=evidence.freshness_score,
            summary=evidence.summary,
            key_quote=evidence.summary[:150],
            highlights=[],
            stance=evidence.stance,
            analysis="",
            publish_date=evidence.publish_date,
            tags=[],
        )

    def test_deduplicate_removes_same_domain_column_reposts(self):
        first = self._build_evidence("鸣沙山山顶矿泉水售价为2元一瓶，景区运营方回应称该价格长期执行。")
        first.url = "https://news.hsw.cn/system/2026/0506/1823456.shtml"
        first.title = "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-要闻_华商网新闻"
        first.domain = "news.hsw.cn"

        repost = self._build_evidence("鸣沙山山顶矿泉水售价为2元一瓶，景区运营方回应称该价格长期执行。")
        repost.url = "https://news.hsw.cn/system/2026/0506/1823456_2.shtml"
        repost.title = "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-社会新闻_华商网新闻"
        repost.domain = "news.hsw.cn"
        repost.rank = 2

        deduped = self.generator._deduplicate_evidences([first, repost])

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].url, first.url)

    def test_normalize_title_strips_nested_news_suffixes(self):
        first = self.generator._normalize_text_for_dedup(
            "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-要闻_华商网新闻"
        )
        second = self.generator._normalize_text_for_dedup(
            "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-社会新闻_华商网新闻"
        )

        self.assertEqual(first, second)
        self.assertEqual(first, "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应")

    def test_final_chain_item_dedup_removes_same_domain_reposts(self):
        first = self._build_evidence("鸣沙山山顶矿泉水1瓶只需要2块钱，景区运营方回应称该价格长期执行。")
        first.title = "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-要闻_华商网新闻"
        first.domain = "news.hsw.cn"
        repost = self._build_evidence("鸣沙山山顶矿泉水1瓶只需要2块钱，景区运营方回应称该价格长期执行。")
        repost.title = "敦煌鸣沙山顶矿泉水只卖2元获游客点赞 景区回应-社会新闻_华商网新闻"
        repost.url = "https://news.hsw.cn/repost"
        repost.domain = "news.hsw.cn"

        items = [self._build_chain_item(first), self._build_chain_item(repost)]

        deduped = self.generator._deduplicate_chain_items(items)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].title, first.title)

    async def test_link_validation_marks_inaccessible_evidence_without_dropping_it(self):
        generator = EvidenceChainGenerator()
        results = [
            {
                "title": "一名中国公民在巴塞罗那不幸遇害身亡_新闻频道_央视网",
                "url": "https://news.cctv.com/example.shtml",
                "summary": "据中国驻巴塞罗那总领馆消息，当地时间5月2日，一名中国公民在巴塞罗那不幸遇害身亡。",
                "date_published": "2026-05-05",
            },
            {
                "title": "国际丨41岁中国女子巴塞罗那遭一男子刺伤身亡 凶手被捕 - 新京报",
                "url": "https://www.bjnews.com.cn/detail/example.html",
                "summary": "报道显示，一名中国女子在巴塞罗那遭男子刺伤后不幸身亡，嫌疑人已被警方控制。",
                "date_published": "2026-05-06",
            },
        ]
        generator.link_validator = SimpleNamespace(
            validate_multiple_links=AsyncMock(return_value=[
                LinkValidationResult(
                    url="https://news.cctv.com/example.shtml",
                    is_accessible=False,
                    status_code=403,
                    response_time_ms=12,
                    error_message="HTTP 403",
                    content_type=None,
                    content_length=None,
                    final_url=None,
                    timestamp="2026-05-07T00:00:00",
                ),
                LinkValidationResult(
                    url="https://www.bjnews.com.cn/detail/example.html",
                    is_accessible=True,
                    status_code=200,
                    response_time_ms=10,
                    error_message=None,
                    content_type="text/html",
                    content_length=1000,
                    final_url=None,
                    timestamp="2026-05-07T00:00:00",
                ),
            ])
        )

        chain = await generator.generate_evidence_chain(
            claim="中国女子巴塞罗那街头遇害",
            search_results=results,
            enable_link_validation=True,
            top_k=2,
        )

        items = chain.supporting_evidence + chain.opposing_evidence + chain.neutral_evidence
        self.assertEqual(chain.total_evidence, 2)
        self.assertEqual(len(items), 2)
        self.assertIn("不可访问", [item["validation"]["link_status"] for item in items])

    def test_extract_highlights_marks_port_information_with_indices(self):
        claim = "前端插件通过 http://127.0.0.1:8000 连接后端服务"
        summary = (
            "第一句只是背景。"
            "浏览器插件会请求 http://127.0.0.1:8000/api/v1/check，默认连接本地 127.0.0.1:8000 端口。"
            "最后一句是补充信息。"
        )
        evidence = self._build_evidence(summary)

        highlights = self.generator._extract_highlights(evidence, claim)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].text,
            "浏览器插件会请求 http://127.0.0.1:8000/api/v1/check，默认连接本地 127.0.0.1:8000 端口。"
        )
        self.assertIn("http://127.0.0.1:8000", highlights[0].text)
        self.assertIn("127.0.0.1:8000", highlights[0].text)

        for highlight in highlights:
            self.assertEqual(
                summary[highlight.start_index:highlight.end_index],
                highlight.text,
            )
            self.assertEqual(highlight.highlight_type, "support")

    def test_extract_highlights_prefers_negative_assertion_sentence(self):
        claim = "网传该品牌牛奶含有三聚氰胺"
        summary = (
            "品牌方今天回应了相关讨论。"
            "市场监管部门通报称，抽检结果显示该品牌牛奶未检出三聚氰胺，不存在食品安全问题。"
            "消费者可以继续关注后续公告。"
        )

        highlights = self.generator._extract_highlights(self._build_evidence(summary, "oppose"), claim)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].text,
            "市场监管部门通报称，抽检结果显示该品牌牛奶未检出三聚氰胺，不存在食品安全问题。"
        )
        self.assertEqual(highlights[0].highlight_type, "oppose")

    def test_extract_highlights_prefers_numeric_fact_sentence(self):
        claim = "上海今天新增3例确诊病例"
        summary = (
            "发布会介绍了总体防控安排。"
            "市卫健委通报，上海今日新增3例新冠肺炎确诊病例、12例无症状感染者，相关人员已闭环转运。"
            "后续将继续开展流调。"
        )

        highlights = self.generator._extract_highlights(self._build_evidence(summary), claim)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].text,
            "市卫健委通报，上海今日新增3例新冠肺炎确诊病例、12例无症状感染者，相关人员已闭环转运。"
        )

    def test_extract_highlights_prefers_fact_relation_over_topic_sentence(self):
        claim = "网传该药会导致肝损伤"
        summary = (
            "社交平台上关于该药、导致、肝损伤等说法持续传播，引发大量讨论。"
            "医院临床研究显示，现有证据不足以证明该药会导致肝损伤。"
            "专家建议患者不要自行停药。"
        )

        highlights = self.generator._extract_highlights(self._build_evidence(summary, "oppose"), claim)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].text,
            "医院临床研究显示，现有证据不足以证明该药会导致肝损伤。"
        )

    def test_extract_highlights_rejects_rumor_restatement_sentence(self):
        claim = "网传北京房价暴跌30%"
        summary = (
            "“北京房价暴跌30%”的说法今天在多个平台传播。"
            "国家统计局数据显示，北京新建商品住宅销售价格环比下降0.3%，不存在暴跌30%的情况。"
            "业内人士提醒应区分个案与整体市场。"
        )

        highlights = self.generator._extract_highlights(self._build_evidence(summary, "oppose"), claim)

        self.assertEqual(len(highlights), 1)
        self.assertEqual(
            highlights[0].text,
            "国家统计局数据显示，北京新建商品住宅销售价格环比下降0.3%，不存在暴跌30%的情况。"
        )

    def test_extract_highlights_returns_multiple_distinct_fact_sentences(self):
        claim = "白冰偷逃税款911.18万元并被罚1891.24万元"
        summary = (
            "税务部门公告显示，白冰通过转换收入性质等方式少缴税款911.18万元。"
            "处理结果显示，相关部门依法追缴税款、加收滞纳金并处罚款合计1891.24万元。"
            "该事件随后引发公众关注。"
        )

        highlights = self.generator._extract_highlights(self._build_evidence(summary), claim)

        self.assertEqual(len(highlights), 2)
        self.assertEqual(
            [h.text for h in highlights],
            [
                "税务部门公告显示，白冰通过转换收入性质等方式少缴税款911.18万元。",
                "处理结果显示，相关部门依法追缴税款、加收滞纳金并处罚款合计1891.24万元。",
            ],
        )
        self.assertLessEqual(highlights[0].end_index, highlights[1].start_index)

    def test_extract_brief_summary_skips_section_heading_and_stuck_bullets(self):
        full_summary = (
            "核心事实提取：\n"
            "    - 案件主体：美食探店类短视频博主“白冰”，拥有超4000万粉丝。"
            "- 违法行为：在2021年至2024年间，通过设立空壳“个体户”、转换收入性质、虚报等方式偷逃税款。"
            "- 处理结果：相关部门依法追缴税款、加收滞纳金并处罚款。"
        )

        brief = self.generator._extract_brief_summary(full_summary)

        self.assertNotIn("核心事实提取", brief)
        self.assertNotIn("。-", brief)
        self.assertTrue(brief.startswith("案件主体："))
        self.assertIn("违法行为：", brief)

    def test_extract_brief_summary_removes_prompt_labels_and_stops_before_analysis(self):
        full_summary = (
            "【开头段落】\n"
            "说法“网红白冰偷税超900万被查”完全属实。"
            "根据国家税务总局2026年4月28日公布的信息并经多家权威媒体证实，美食探店博主白冰在2021年至2024年期间，"
            "通过转换收入性质、虚假申报等手段，共计少缴税款911.18万元，已被税务部门依法查处并处以1891.24万元的追缴及罚款。"
            "【展开分析】\n"
            "核心事实提取：1. 案件主体：美食探店类短视频博主白冰。2. 违法行为：转换收入性质。"
        )

        brief = self.generator._extract_brief_summary(full_summary)

        self.assertNotIn("【开头段落】", brief)
        self.assertNotIn("【展开分析】", brief)
        self.assertNotIn("核心事实提取", brief)
        self.assertTrue(brief.startswith("说法“网红白冰偷税超900万被查”完全属实。"))
        self.assertTrue(brief.endswith("罚款。"))

    def test_extract_brief_summary_does_not_split_decimal_percentages(self):
        full_summary = (
            "关于“夫妻囤芯片收益320亿”的说法，经核查，此表述存在关键性误导。"
            "身份确认：说法中的“夫妻”为A股上市公司德明利的创始人李虎夫妇，李虎持股35.97%。"
            "财富性质澄清：暴涨的“320亿”特指纸面身家，并非已实现的现金收益。"
        )

        brief = self.generator._extract_brief_summary(full_summary)

        self.assertIn("35.97%", brief)
        self.assertNotIn("35.", brief.replace("35.97%", ""))
        self.assertIn("财富性质澄清：", brief)

    def test_normalize_ai_summary_format_breaks_structural_labels_into_new_lines(self):
        raw = (
            "关键误导点：暴涨的是纸面身家而非现金收益。"
            "身份确认：说法中的夫妻为德明利创始人夫妇。"
            "财富性质澄清：320亿对应持股市值。"
        )

        normalized = self.generator._normalize_ai_summary_format(raw)

        self.assertIn("关键误导点：", normalized)
        self.assertIn("\n身份确认：", normalized)
        self.assertIn("\n财富性质澄清：", normalized)


if __name__ == "__main__":
    unittest.main()
