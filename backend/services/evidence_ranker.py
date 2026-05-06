"""
证据关联排序算法模块
对搜索结果进行相关性评分和排序
"""

import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime

from utils.text import parse_date, extract_keywords
from utils.url import get_authority_score, get_domain_tier, extract_domain

logger = logging.getLogger(__name__)


@dataclass
class RankedEvidence:
    """排序后的证据"""
    url: str
    title: str
    summary: str
    relevance_score: float  # 相关性评分 (0-100)
    authority_score: float  # 权威性评分 (0-100)
    freshness_score: float  # 时效性评分 (0-100)
    overall_score: float  # 综合评分 (0-100)
    rank: int  # 排名
    tier: str  # 信源等级 (Tier 1/2/3)
    publish_date: Optional[str]
    domain: str
    stance: str = "neutral"  # 证据立场: support/oppose/neutral


class EvidenceRanker:
    """证据排序器"""

    def calculate_relevance(
        self,
        claim: str,
        evidence_title: str,
        evidence_summary: str
    ) -> float:
        """
        计算证据与声明之间的相关性

        Args:
            claim: 待核查的声明
            evidence_title: 证据标题
            evidence_summary: 证据摘要

        Returns:
            float: 相关性评分 (0-100)
        """
        # 合并标题和摘要进行匹配
        evidence_text = f"{evidence_title} {evidence_summary}".lower()
        claim_lower = claim.lower()

        # 1. 关键词匹配评分 (40%)
        keyword_score = self._keyword_match_score(claim_lower, evidence_text)

        # 2. 语义相似度评分 (30%)
        semantic_score = self._semantic_similarity_score(claim_lower, evidence_text)

        # 3. 位置权重评分 (20%)
        # 标题匹配更重要
        position_score = 0
        if any(word in evidence_title.lower() for word in extract_keywords(claim)):
            position_score = 100

        # 4. 长度适配度评分 (10%)
        # 太短或太长的摘要都不好
        length_score = self._length_appropriateness_score(len(evidence_summary))

        # 加权平均
        relevance_score = (
            keyword_score * 0.4 +
            semantic_score * 0.3 +
            position_score * 0.2 +
            length_score * 0.1
        )

        return round(min(100, relevance_score), 2)

    def _keyword_match_score(self, claim: str, evidence: str) -> float:
        """关键词匹配评分"""
        # 提取声明中的关键词（2-4字的中文词）
        keywords = extract_keywords(claim)

        if not keywords:
            return 0.0

        # 计算匹配率
        matched_count = sum(1 for kw in keywords if kw in evidence)
        match_rate = matched_count / len(keywords)

        # 考虑关键词权重（长词权重更高）
        weighted_score = 0
        total_weight = 0

        for kw in keywords:
            weight = len(kw)  # 长度作为权重
            total_weight += weight
            if kw in evidence:
                weighted_score += weight

        if total_weight == 0:
            return 0.0

        return (weighted_score / total_weight) * 100

    def _semantic_similarity_score(self, claim: str, evidence: str) -> float:
        """
        语义相似度评分（简化版）

        Note: 完整实现可以使用词向量模型（如sentence-transformers）
        这里使用基于n-gram的简化算法
        """
        # 提取n-gram（2-gram和3-gram）
        def get_ngrams(text: str, n: int) -> set:
            words = re.findall(r'[\u4e00-\u9fa5]+', text)
            ngrams = set()
            for i in range(len(words) - n + 1):
                ngram = ''.join(words[i:i+n])
                if len(ngram) >= n * 2:
                    ngrams.add(ngram)
            return ngrams

        claim_2grams = get_ngrams(claim, 2)
        claim_3grams = get_ngrams(claim, 3)

        evidence_2grams = get_ngrams(evidence, 2)
        evidence_3grams = get_ngrams(evidence, 3)

        # 计算Jaccard相似度
        def jaccard_similarity(set1: set, set2: set) -> float:
            if not set1 or not set2:
                return 0.0
            intersection = set1 & set2
            union = set1 | set2
            return len(intersection) / len(union) if union else 0.0

        sim_2gram = jaccard_similarity(claim_2grams, evidence_2grams)
        sim_3gram = jaccard_similarity(claim_3grams, evidence_3grams)

        # 加权平均（3-gram权重更高）
        similarity = (sim_2gram * 0.4 + sim_3gram * 0.6) * 100

        return similarity

    def _length_appropriateness_score(self, length: int) -> float:
        """长度适配度评分"""
        # 理想长度：50-500字
        if 50 <= length <= 500:
            return 100.0
        elif length < 50:
            return max(0, (length / 50) * 60)  # 最长给60分
        else:  # > 500
            return max(40, 100 - (length - 500) / 50)  # 逐渐降低，最低40分

    def calculate_freshness(self, publish_date: Optional[str]) -> float:
        """
        计算时效性评分

        Args:
            publish_date: 发布日期

        Returns:
            float: 时效性评分 (0-100)
        """
        if not publish_date:
            return 50.0  # 无日期信息，默认分数

        try:
            # 尝试解析日期
            date = parse_date(publish_date)
            if not date:
                return 50.0

            # 计算时间差
            now = datetime.now()
            delta = now - date

            # 根据时间差评分（事实核查需要最新信息，旧内容大幅降分）
            if delta.days <= 3:    # 3天内
                return 100.0
            elif delta.days <= 7:  # 1周内
                return 95.0
            elif delta.days <= 30:  # 1月内
                return 85.0
            elif delta.days <= 90:  # 3个月内
                return 70.0
            elif delta.days <= 365:  # 1年内
                return 50.0
            elif delta.days <= 365 * 2:  # 2年内
                return 30.0
            else:  # 超过2年
                return max(10.0, 30.0 - (delta.days - 365 * 2) / 365 * 10)

        except Exception as e:
            logger.warning(f"日期解析失败: {publish_date} - {e}")
            return 50.0

    def rank_evidences(
        self,
        claim: str,
        search_results: List[Dict[str, str]]
    ) -> List[RankedEvidence]:
        """
        对搜索结果进行排序

        Args:
            claim: 待核查的声明
            search_results: 搜索结果列表

        Returns:
            List[RankedEvidence]: 排序后的证据列表
        """
        logger.info(f"开始对 {len(search_results)} 个证据进行排序")

        ranked_evidences = []

        for i, result in enumerate(search_results):
            url = result.get('url', '')
            title = result.get('title', '') or result.get('name', '')  # 兼容两种键名
            summary = result.get('summary', '')
            publish_date = result.get('date_published') or result.get('datePublished')  # 兼容两种键名

            # 详细日志：显示读取到的标题
            logger.info(f"证据 [{i+1}] 标题读取: '{title[:80] if title else '(空)'}' (URL: {url[:60]})")
            if not title:
                logger.warning(f"⚠️ 证据 [{i+1}] 标题为空！原始数据: {list(result.keys())}")

            # 1. 计算相关性评分
            relevance_score = self.calculate_relevance(claim, title, summary)

            # 2. 计算权威性评分
            authority_score = get_authority_score(url)

            # 3. 计算时效性评分
            freshness_score = self.calculate_freshness(publish_date)

            # 4. 综合评分（加权平均）
            # 事实核查场景：时效性和相关性同等重要
            # 权重分配：相关性40%，时效性35%，权威性25%
            overall_score = (
                relevance_score * 0.4 +
                freshness_score * 0.35 +
                authority_score * 0.25
            )

            # 5. 确定信源等级
            tier = get_domain_tier(url)

            # 6. 提取域名
            domain = extract_domain(url) or "unknown"

            ranked_evidences.append(RankedEvidence(
                url=url,
                title=title,
                summary=summary,
                relevance_score=relevance_score,
                authority_score=authority_score,
                freshness_score=freshness_score,
                overall_score=round(overall_score, 2),
                rank=0,  # 稍后设置
                tier=tier,
                publish_date=publish_date,
                domain=domain
            ))

        # 按综合评分降序排序
        ranked_evidences.sort(key=lambda x: x.overall_score, reverse=True)

        # 设置排名
        for i, evidence in enumerate(ranked_evidences, 1):
            evidence.rank = i

        logger.info(f"证据排序完成，最高分: {ranked_evidences[0].overall_score if ranked_evidences else 0}")

        return ranked_evidences

    def filter_top_evidences(
        self,
        ranked_evidences: List[RankedEvidence],
        top_n: int = 5,
        min_score: float = 30.0
    ) -> List[RankedEvidence]:
        """
        过滤出Top N的证据

        Args:
            ranked_evidences: 排序后的证据列表
            top_n: 返回数量
            min_score: 最低分数阈值

        Returns:
            List[RankedEvidence]: 过滤后的证据列表
        """
        # 过滤低分证据
        filtered = [e for e in ranked_evidences if e.overall_score >= min_score]

        # 返回Top N
        return filtered[:top_n]

    def generate_ranking_report(
        self,
        ranked_evidences: List[RankedEvidence]
    ) -> Dict:
        """
        生成排序报告

        Args:
            ranked_evidences: 排序后的证据列表

        Returns:
            Dict: 排序报告
        """
        if not ranked_evidences:
            return {
                "total_count": 0,
                "average_score": 0,
                "tier_distribution": {},
                "top_evidence": None
            }

        # 统计信源等级分布
        tier_distribution = {}
        for evidence in ranked_evidences:
            tier = evidence.tier
            tier_distribution[tier] = tier_distribution.get(tier, 0) + 1

        # 计算平均分
        avg_score = sum(e.overall_score for e in ranked_evidences) / len(ranked_evidences)

        return {
            "total_count": len(ranked_evidences),
            "average_score": round(avg_score, 2),
            "highest_score": ranked_evidences[0].overall_score,
            "lowest_score": ranked_evidences[-1].overall_score,
            "tier_distribution": tier_distribution,
            "top_evidence": {
                "rank": ranked_evidences[0].rank,
                "title": ranked_evidences[0].title,
                "url": ranked_evidences[0].url,
                "score": ranked_evidences[0].overall_score,
                "tier": ranked_evidences[0].tier
            }
        }


