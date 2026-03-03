"""
证据关联排序算法模块
对搜索结果进行相关性评分和排序
"""

import re
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlparse

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


class EvidenceRanker:
    """证据排序器"""

    def __init__(self):
        """初始化证据排序器"""
        # 定义权威域名（Tier 1: 官方/科研机构）
        self.tier1_domains = {
            # 政府机构
            'gov.cn', 'gkxx.gov.cn', 'people.com.cn', 'xinhuanet.com',
            # 科研机构
            'cnki.net', 'wanfangdata.com.cn', 'cqvip.com',
            'nature.com', 'science.org', 'ieee.org', 'acm.org',
            # 权威媒体
            'thepaper.cn', 'caixin.com', 'caijing.com.cn', 'finance.sina.com.cn',
            # 国际组织
            'who.int', 'un.org', 'worldbank.org'
        }

        # 定义半权威域名（Tier 2: 知名媒体/百科）
        self.tier2_domains = {
            'baike.baidu.com', 'zh.wikipedia.org', 'zhihu.com',
            'sohu.com', 'qq.com', '163.com', 'sina.com.cn',
            'ifeng.com', 'toutiao.com'
        }

        # 垃圾域名列表（Tier 0: 低质量）
        self.spam_domains = {
            'ad.com', 'click.com', 'popup.com', 'spam.com'
        }

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
        if any(word in evidence_title.lower() for word in self._extract_keywords(claim)):
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
        keywords = self._extract_keywords(claim)

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

    def _extract_keywords(self, text: str) -> List[str]:
        """
        提取关键词（2-4字的中文词）

        Args:
            text: 输入文本

        Returns:
            List[str]: 关键词列表
        """
        # 简单实现：提取连续的2-4个汉字作为关键词
        keywords = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)

        # 去重并排序（按长度降序）
        keywords = sorted(set(keywords), key=len, reverse=True)

        return keywords[:20]  # 返回前20个

    def calculate_authority(self, url: str) -> float:
        """
        计算信源权威性评分

        Args:
            url: 证据URL

        Returns:
            float: 权威性评分 (0-100)
        """
        try:
            domain = urlparse(url).netloc.lower()
            # 移除www前缀
            domain = re.sub(r'^www\.', '', domain)
        except:
            return 50.0  # 默认分数

        # Tier 1: 官方/科研机构 (90-100分)
        if any(tier1 in domain for tier1 in self.tier1_domains):
            return 95.0

        # Tier 2: 知名媒体/百科 (70-89分)
        if any(tier2 in domain for tier2 in self.tier2_domains):
            return 80.0

        # Tier 0: 垃圾域名 (0-20分)
        if any(spam in domain for spam in self.spam_domains):
            return 10.0

        # 根据域名类型评分
        if '.edu.' in domain or '.ac.' in domain:  # 教育机构
            return 85.0
        elif '.org.' in domain:  # 非营利组织
            return 75.0
        elif domain.endswith('.com'):  # 商业网站
            return 60.0
        elif domain.endswith('.cn'):
            return 65.0
        else:
            return 50.0  # 默认分数

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
            date = self._parse_date(publish_date)
            if not date:
                return 50.0

            # 计算时间差
            now = datetime.now()
            delta = now - date

            # 根据时间差评分
            if delta.days <= 7:  # 7天内
                return 100.0
            elif delta.days <= 30:  # 30天内
                return 90.0
            elif delta.days <= 90:  # 3个月内
                return 80.0
            elif delta.days <= 365:  # 1年内
                return 70.0
            elif delta.days <= 365 * 3:  # 3年内
                return 60.0
            else:  # 超过3年
                return 50.0 - min(30, (delta.days - 365 * 3) / 365 * 10)

        except Exception as e:
            logger.warning(f"日期解析失败: {publish_date} - {e}")
            return 50.0

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        # 常见日期格式
        date_formats = [
            '%Y-%m-%d',
            '%Y年%m月%d日',
            '%Y/%m/%d',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%d %H:%M:%S',
        ]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str.split('T')[0].split()[0], fmt)
            except:
                continue

        return None

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

        for result in search_results:
            url = result.get('url', '')
            title = result.get('name', '')
            summary = result.get('summary', '')
            publish_date = result.get('datePublished')

            # 1. 计算相关性评分
            relevance_score = self.calculate_relevance(claim, title, summary)

            # 2. 计算权威性评分
            authority_score = self.calculate_authority(url)

            # 3. 计算时效性评分
            freshness_score = self.calculate_freshness(publish_date)

            # 4. 综合评分（加权平均）
            # 权重分配：相关性50%，权威性35%，时效性15%
            overall_score = (
                relevance_score * 0.5 +
                authority_score * 0.35 +
                freshness_score * 0.15
            )

            # 5. 确定信源等级
            tier = self._determine_tier(authority_score)

            # 6. 提取域名
            try:
                domain = urlparse(url).netloc
            except:
                domain = "unknown"

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

    def _determine_tier(self, authority_score: float) -> str:
        """根据权威性评分确定信源等级"""
        if authority_score >= 90:
            return "Tier 1"
        elif authority_score >= 70:
            return "Tier 2"
        else:
            return "Tier 3"

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


# 使用示例
def main():
    """测试证据排序"""
    ranker = EvidenceRanker()

    # 模拟搜索结果
    claim = "中国的高铁技术完全自主"
    search_results = [
        {
            "name": "中国高铁发展历程",
            "url": "https://www.gov.cn/guowuyuan/2023-10-15/content-123456.html",
            "summary": "中国高铁技术经过多年发展，部分核心部件已实现国产化，但仍有一部分依赖进口。",
            "datePublished": "2023-10-15"
        },
        {
            "name": "高铁知识科普",
            "url": "https://baike.baidu.com/item/%E9%AB%98%E9%93%81",
            "summary": "高铁是指设计开行时速250公里以上（含预留）、初期运营时速200公里以上的客运列车。",
            "datePublished": "2022-05-20"
        },
        {
            "name": "中国高铁技术的自主化之路",
            "url": "https://www.thepaper.cn/newsDetail_forward_12345678",
            "summary": "中国高铁技术从引进消化吸收到自主创新的历程，虽然起步晚但发展迅速。",
            "datePublished": "2023-08-10"
        }
    ]

    # 排序
    ranked = ranker.rank_evidences(claim, search_results)

    # 输出结果
    print("证据排序结果:")
    for evidence in ranked:
        print(f"\n排名: {evidence.rank}")
        print(f"标题: {evidence.title}")
        print(f"综合评分: {evidence.overall_score}")
        print(f"相关性: {evidence.relevance_score}")
        print(f"权威性: {evidence.authority_score}")
        print(f"时效性: {evidence.freshness_score}")
        print(f"等级: {evidence.tier}")
        print(f"域名: {evidence.domain}")

    # 生成报告
    report = ranker.generate_ranking_report(ranked)
    print(f"\n排序报告:")
    print(f"总计: {report['total_count']} 个证据")
    print(f"平均分: {report['average_score']}")
    print(f"最高分: {report['highest_score']}")
    print(f"等级分布: {report['tier_distribution']}")


if __name__ == "__main__":
    main()
