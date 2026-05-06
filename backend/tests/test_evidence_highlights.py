import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.evidence_chain_generator import EvidenceChainGenerator
from services.evidence_ranker import RankedEvidence


class EvidenceHighlightExtractionTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
