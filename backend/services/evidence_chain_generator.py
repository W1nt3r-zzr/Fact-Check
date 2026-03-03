"""
证据链生成模块
为前端提供结构化的证据链数据，支持可视化展示
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

from services.evidence_ranker import EvidenceRanker, RankedEvidence
from services.link_validator import LinkValidator, LinkValidationResult

logger = logging.getLogger(__name__)


@dataclass
class EvidenceHighlight:
    """证据高亮信息"""
    text: str  # 高亮文本
    start_index: int  # 在原文中的起始位置
    end_index: int  # 在原文中的结束位置
    highlight_type: str  # 高亮类型：support/opposing/neutral
    confidence: float  # 置信度 0-1


@dataclass
class EvidenceChainItem:
    """证据链中的一个证据项"""
    rank: int  # 排名
    url: str  # 来源URL
    title: str  # 标题
    domain: str  # 域名
    tier: str  # 信源等级 (Tier 1/2/3)

    # 评分
    overall_score: float  # 综合评分 (0-100)
    relevance_score: float  # 相关性评分
    authority_score: float  # 权威性评分
    freshness_score: float  # 时效性评分

    # 内容
    summary: str  # 摘要
    key_quote: str  # 关键引用
    highlights: List[EvidenceHighlight]  # 高亮信息

    # 验证
    link_status: Optional[str]  # 链接状态
    publish_date: Optional[str]  # 发布日期

    # 标签
    tags: List[str]  # 标签（如"官方"、"媒体"、"学术"等）


@dataclass
class EvidenceChain:
    """完整的证据链"""
    claim: str  # 待核查的说法
    verdict: str  # 核查结论
    confidence: float  # 整体置信度 (0-100)

    # 证据链
    supporting_evidence: List[EvidenceChainItem]  # 支持性证据
    opposing_evidence: List[EvidenceChainItem]  # 反对性证据
    neutral_evidence: List[EvidenceChainItem]  # 中性证据

    # 分析
    reasoning_summary: str  # 推理过程摘要
    key_findings: List[str]  # 关键发现
    uncertainty_note: str  # 不确定性说明

    # 统计
    total_evidence: int  # 总证据数
    authoritative_sources: int  # 权威来源数
    average_score: float  # 平均评分

    # 元数据
    generated_at: str  # 生成时间
    processing_time_ms: float  # 处理时间


class EvidenceChainGenerator:
    """证据链生成器"""

    def __init__(self):
        """初始化证据链生成器"""
        self.ranker = EvidenceRanker()
        self.link_validator = LinkValidator(timeout=5.0)

    async def generate_evidence_chain(
        self,
        claim: str,
        search_results: List[Dict[str, str]],
        enable_link_validation: bool = False,
        top_k: int = 5
    ) -> EvidenceChain:
        """
        生成证据链

        Args:
            claim: 待核查的说法
            search_results: 搜索结果列表
            enable_link_validation: 是否验证链接活性
            top_k: 返回Top K个证据

        Returns:
            EvidenceChain: 结构化的证据链
        """
        start_time = datetime.now()

        logger.info(f"开始生成证据链: {claim}")
        logger.info(f"搜索结果数量: {len(search_results)}, 链接验证: {enable_link_validation}")

        # 步骤1: 证据排序
        ranked_evidences = self.ranker.rank_evidences(claim, search_results)

        # 步骤2: 链接验证（可选）
        link_validations = {}
        if enable_link_validation and ranked_evidences:
            urls = [e.url for e in ranked_evidences[:top_k]]
            try:
                validation_results = await self.link_validator.validate_multiple_links(
                    urls, concurrent_limit=3
                )
                link_validations = {r.url: r for r in validation_results}
            except Exception as e:
                logger.error(f"链接验证失败: {e}")

        # 步骤3: 提取Top K证据
        top_evidences = ranked_evidences[:top_k]

        # 步骤4: 分类证据（支持/反对/中性）
        supporting, opposing, neutral = self._categorize_evidences(top_evidences)

        # 步骤5: 构建证据链项
        chain_items = []
        for evidence in top_evidences:
            highlights = self._extract_highlights(evidence, claim)

            # 获取链接状态
            link_status = None
            if evidence.url in link_validations:
                validation = link_validations[evidence.url]
                link_status = "可访问" if validation.is_accessible else "不可访问"

            item = EvidenceChainItem(
                rank=evidence.rank,
                url=evidence.url,
                title=evidence.title,
                domain=evidence.domain,
                tier=evidence.tier,
                overall_score=evidence.overall_score,
                relevance_score=evidence.relevance_score,
                authority_score=evidence.authority_score,
                freshness_score=evidence.freshness_score,
                summary=evidence.summary[:200],  # 限制摘要长度
                key_quote=self._extract_key_quote(evidence.summary),
                highlights=highlights,
                link_status=link_status,
                publish_date=evidence.date_published,
                tags=self._generate_tags(evidence)
            )
            chain_items.append(item)

        # 步骤6: 计算统计信息
        authoritative_count = sum(1 for e in chain_items if e.tier == "Tier 1")
        avg_score = sum(e.overall_score for e in chain_items) / len(chain_items) if chain_items else 0

        # 步骤7: 生成推理摘要
        reasoning_summary = self._generate_reasoning_summary(claim, chain_items)

        # 步骤8: 提取关键发现
        key_findings = self._extract_key_findings(chain_items)

        # 步骤9: 确定结论和置信度
        verdict, confidence = self._determine_verdict(chain_items)

        # 步骤10: 不确定性说明
        uncertainty_note = self._generate_uncertainty_note(chain_items)

        processing_time = (datetime.now() - start_time).total_seconds() * 1000

        # 构建证据链
        evidence_chain = EvidenceChain(
            claim=claim,
            verdict=verdict,
            confidence=confidence,
            supporting_evidence=[self._evidence_to_dict(e) for e in supporting],
            opposing_evidence=[self._evidence_to_dict(e) for e in opposing],
            neutral_evidence=[self._evidence_to_dict(e) for e in neutral],
            reasoning_summary=reasoning_summary,
            key_findings=key_findings,
            uncertainty_note=uncertainty_note,
            total_evidence=len(chain_items),
            authoritative_sources=authoritative_count,
            average_score=round(avg_score, 2),
            generated_at=datetime.now().isoformat(),
            processing_time_ms=round(processing_time, 2)
        )

        logger.info(f"证据链生成完成: {len(chain_items)} 个证据, 耗时: {processing_time:.0}ms")

        return evidence_chain

    def _categorize_evidences(
        self,
        evidences: List[RankedEvidence]
    ) -> tuple[List[RankedEvidence], List[RankedEvidence], List[RankedEvidence]]:
        """
        分类证据为支持/反对/中性

        Args:
            evidences: 排序后的证据列表

        Returns:
            tuple: (supporting, opposing, neutral)
        """
        supporting = []
        opposing = []
        neutral = []

        for evidence in evidences:
            # 简单的分类逻辑（可以后续优化）
            if evidence.overall_score >= 70:
                supporting.append(evidence)
            elif evidence.overall_score >= 40:
                neutral.append(evidence)
            else:
                opposing.append(evidence)

        return supporting, opposing, neutral

    def _extract_highlights(
        self,
        evidence: RankedEvidence,
        claim: str
    ) -> List[EvidenceHighlight]:
        """
        从证据摘要中提取高亮信息

        Args:
            evidence: 证据对象
            claim: 待核查的说法

        Returns:
            List[EvidenceHighlight]: 高亮信息列表
        """
        highlights = []
        summary = evidence.summary

        # 提取claim中的关键词并在summary中查找
        claim_keywords = self._extract_keywords_from_claim(claim)

        for keyword in claim_keywords:
            if keyword in summary:
                # 找到关键词在summary中的位置
                start_idx = summary.find(keyword)
                if start_idx != -1:
                    end_idx = start_idx + len(keyword)

                    # 确定高亮类型
                    if evidence.overall_score >= 70:
                        highlight_type = "support"
                    elif evidence.overall_score <= 40:
                        highlight_type = "oppose"
                    else:
                        highlight_type = "neutral"

                    highlight = EvidenceHighlight(
                        text=keyword,
                        start_index=start_idx,
                        end_index=end_idx,
                        highlight_type=highlight_type,
                        confidence=evidence.overall_score / 100
                    )
                    highlights.append(highlight)

        return highlights

    def _extract_keywords_from_claim(self, claim: str) -> List[str]:
        """从说法中提取关键词"""
        import jieba
        words = jieba.cut(claim)
        # 过滤停用词和短词
        keywords = [w for w in words if len(w) >= 2]
        return list(set(keywords))[:10]  # 返回前10个关键词

    def _extract_key_quote(self, summary: str) -> str:
        """从摘要中提取关键引用"""
        # 简单实现：返回摘要的前150个字符
        return summary[:150] if summary else "无"

    def _generate_tags(self, evidence: RankedEvidence) -> List[str]:
        """生成证据标签"""
        tags = []

        # 根据信源等级添加标签
        if evidence.tier == "Tier 1":
            tags.append("官方")
            tags.append("权威")
        elif evidence.tier == "Tier 2":
            tags.append("媒体")
        else:
            tags.append("网络")

        # 根据评分添加标签
        if evidence.overall_score >= 80:
            tags.append("高质量")
        elif evidence.overall_score >= 60:
            tags.append("中等质量")

        # 根据时效性添加标签
        if evidence.freshness_score >= 80:
            tags.append("最新")
        elif evidence.freshness_score >= 60:
            tags.append("近期")

        return tags

    def _evidence_to_dict(self, evidence: EvidenceChainItem) -> Dict[str, Any]:
        """将证据项转换为字典（用于JSON序列化）"""
        return {
            "rank": evidence.rank,
            "url": evidence.url,
            "title": evidence.title,
            "domain": evidence.domain,
            "tier": evidence.tier,
            "scores": {
                "overall": evidence.overall_score,
                "relevance": evidence.relevance_score,
                "authority": evidence.authority_score,
                "freshness": evidence.freshness_score
            },
            "content": {
                "summary": evidence.summary,
                "key_quote": evidence.key_quote
            },
            "highlights": [
                {
                    "text": h.text,
                    "type": h.highlight_type,
                    "confidence": h.confidence
                }
                for h in evidence.highlights
            ],
            "validation": {
                "link_status": evidence.link_status,
                "publish_date": evidence.publish_date
            },
            "tags": evidence.tags
        }

    def _generate_reasoning_summary(self, claim: str, evidences: List[EvidenceChainItem]) -> str:
        """生成推理过程摘要"""
        if not evidences:
            return f"未找到关于「{claim}」的有效证据。"

        # 统计信息
        authoritative_count = sum(1 for e in evidences if e.tier == "Tier 1")
        avg_score = sum(e.overall_score for e in evidences) / len(evidences)

        summary = f"基于{len(evidences)}条证据进行分析，"

        # 根据平均评分判断
        if avg_score >= 70:
            summary += f"证据整体支持该说法（平均评分{avg_score:.1f}分）。"
        elif avg_score >= 40:
            summary += f"证据存在矛盾，需要谨慎判断（平均评分{avg_score:.1f}分）。"
        else:
            summary += f"证据整体不支持该说法（平均评分{avg_score:.1f}分）。"

        # 权威来源
        if authoritative_count > 0:
            summary += f"其中包含{authoritative_count}个权威来源。"

        return summary

    def _extract_key_findings(self, evidences: List[EvidenceChainItem]) -> List[str]:
        """提取关键发现"""
        findings = []

        # 提取评分最高的证据作为关键发现
        if evidences:
            best_evidence = max(evidences, key=lambda x: x.overall_score)
            findings.append(f"最有力的证据来自{best_evidence.domain}（评分{best_evidence.overall_score:.1f}分）")

        # 提取Tier 1来源
        tier1_count = sum(1 for e in evidences if e.tier == "Tier 1")
        if tier1_count > 0:
            findings.append(f"包含{tier1_count}个官方/权威信源")

        # 提取时效性信息
        recent_count = sum(1 for e in evidences if e.publish_date and "2026" in e.publish_date)
        if recent_count > 0:
            findings.append(f"{recent_count}条证据来自2026年最新信息")

        return findings[:3]  # 返回前3个关键发现

    def _determine_verdict(self, evidences: List[EvidenceChainItem]) -> tuple[str, float]:
        """确定核查结论和置信度"""
        if not evidences:
            return "信息不足，无法判断", 0.0

        # 计算加权平均分
        avg_score = sum(e.overall_score for e in evidences) / len(evidences)

        # 根据平均分确定结论
        if avg_score >= 70:
            verdict = "属实"
        elif avg_score <= 40:
            verdict = "不实"
        else:
            verdict = "部分属实，存在争议"

        # 置信度基于证据数量和质量
        confidence = min(100, avg_score * 0.9)  # 最高90%，留10%缓冲

        # 如果有Tier 1来源，提高置信度
        if any(e.tier == "Tier 1" for e in evidences):
            confidence = min(100, confidence + 10)

        return verdict, round(confidence, 2)

    def _generate_uncertainty_note(self, evidences: List[EvidenceChainItem]) -> str:
        """生成不确定性说明"""
        notes = []

        # 检查证据数量
        if len(evidences) < 3:
            notes.append("证据数量较少，结论可能不够可靠。")

        # 检查权威来源
        if not any(e.tier == "Tier 1" for e in evidences):
            notes.append("缺乏官方或权威来源的证实。")

        # 检查评分分布
        scores = [e.overall_score for e in evidences]
        if max(scores) - min(scores) > 50:
            notes.append("证据评分差异较大，存在明显矛盾。")

        # 检查时效性
        old_evidence_count = sum(1 for e in evidences if e.freshness_score < 60)
        if old_evidence_count > len(evidences) / 2:
            notes.append("大部分证据时效性较差。")

        return "；".join(notes) if notes else "证据较为一致，可信度较高。"
