"""
一致性打分算法模块
解决"AI引用的链接与实际页面内容不符"的问题
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyScore:
    """一致性评分结果"""
    overall_score: float  # 总体一致性评分 (0-100)
    semantic_similarity: float  # 语义相似度 (0-100)
    factual_consistency: float  # 事实一致性 (0-100)
    completeness_score: float  # 完整性评分 (0-100)

    ai_summary: str  # AI生成的摘要
    source_content: str  # 源网页内容
    key_differences: List[str]  # 关键差异列表
    missing_info: List[str]  # 缺失信息列表
    contradictory_info: List[str]  # 矛盾信息列表

    timestamp: str
    confidence: float  # 评分置信度 (0-1)


class ConsistencyScorer:
    """一致性评分器"""

    def __init__(self):
        """初始化一致性评分器"""
        self.stopwords = self._load_chinese_stopwords()

    def _load_chinese_stopwords(self) -> set:
        """加载中文停用词"""
        stopwords = {
            "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
            "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "里",
            "为", "与", "或", "及", "等", "对", "将", "把", "被", "从",
            "以", "于", "而", "之", "其", "它", "此", "中", "内", "外"
        }
        return stopwords

    def _preprocess_text(self, text: str) -> str:
        """
        文本预处理

        Args:
            text: 原始文本

        Returns:
            str: 预处理后的文本
        """
        # 去除HTML标签
        text = re.sub(r'<[^>]+>', '', text)

        # 去除多余空白
        text = re.sub(r'\s+', ' ', text)

        # 去除特殊字符（保留中文、英文、数字）
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9。，！？、；：""''（）《》]', ' ', text)

        return text.strip()

    def _extract_keywords(self, text: str, top_n: int = 20) -> List[str]:
        """
        提取关键词（基于词频）

        Args:
            text: 输入文本
            top_n: 返回前N个关键词

        Returns:
            List[str]: 关键词列表
        """
        # 简单的中文分词（基于正则）
        words = re.findall(r'[\u4e00-\u9fa5]{2,}', text)

        # 过滤停用词
        words = [w for w in words if w not in self.stopwords and len(w) >= 2]

        # 统计词频
        word_freq = {}
        for word in words:
            word_freq[word] = word_freq.get(word, 0) + 1

        # 按词频排序
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)

        # 返回前N个
        return [word for word, freq in sorted_words[:top_n]]

    def _calculate_jaccard_similarity(self, text1: str, text2: str) -> float:
        """
        计算Jaccard相似度（基于关键词集合）

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            float: 相似度 (0-1)
        """
        keywords1 = set(self._extract_keywords(text1, top_n=50))
        keywords2 = set(self._extract_keywords(text2, top_n=50))

        if not keywords1 or not keywords2:
            return 0.0

        intersection = keywords1 & keywords2
        union = keywords1 | keywords2

        return len(intersection) / len(union) if union else 0.0

    def _calculate_overlap_ratio(self, text1: str, text2: str) -> Tuple[float, float]:
        """
        计算文本重叠比例

        Args:
            text1: 文本1
            text2: 文本2

        Returns:
            Tuple[float, float]: (text1在text2中的覆盖比例, text2在text1中的覆盖比例)
        """
        words1 = set(self._extract_keywords(text1, top_n=100))
        words2 = set(self._extract_keywords(text2, top_n=100))

        if not words1 or not words2:
            return 0.0, 0.0

        overlap1_2 = len(words1 & words2) / len(words1) if words1 else 0.0
        overlap2_1 = len(words1 & words2) / len(words2) if words2 else 0.0

        return overlap1_2, overlap2_1

    def _detect_factual_consistency(
        self,
        ai_summary: str,
        source_content: str
    ) -> Tuple[float, List[str]]:
        """
        检测事实一致性

        Args:
            ai_summary: AI生成的摘要
            source_content: 源内容

        Returns:
            Tuple[float, List[str]]: (一致性分数, 差异列表)
        """
        # 提取关键实体和数字
        def extract_entities(text: str) -> Dict[str, List[str]]:
            # 提取数字
            numbers = re.findall(r'\d+\.?\d*[万亿千百%]?', text)
            # 提取日期
            dates = re.findall(r'\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}', text)
            # 提取专有名词（大写字母开头的词组）
            proper_nouns = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:公司|大学|研究院|机构|部门)', text)

            return {
                "numbers": numbers,
                "dates": dates,
                "proper_nouns": proper_nouns
            }

        entities_ai = extract_entities(ai_summary)
        entities_source = extract_entities(source_content)

        # 检查数字一致性
        number_diffs = []
        for num in entities_ai["numbers"]:
            if num not in entities_source["numbers"]:
                number_diffs.append(f"数字不一致: AI提到「{num}」，源内容未找到")

        # 检查日期一致性
        date_diffs = []
        for date in entities_ai["dates"]:
            if date not in entities_source["dates"]:
                date_diffs.append(f"日期不一致: AI提到「{date}」，源内容未找到")

        # 计算一致性分数
        total_entities = (
            len(entities_ai["numbers"]) +
            len(entities_ai["dates"]) +
            len(entities_ai["proper_nouns"])
        )

        if total_entities == 0:
            return 100.0, []  # 如果没有实体，认为完全一致

        matched_entities = (
            len([n for n in entities_ai["numbers"] if n in entities_source["numbers"]]) +
            len([d for d in entities_ai["dates"] if d in entities_source["dates"]]) +
            len([p for p in entities_ai["proper_nouns"] if p in entities_source["proper_nouns"]])
        )

        consistency_score = (matched_entities / total_entities) * 100

        differences = number_diffs + date_diffs

        return consistency_score, differences

    def _detect_completeness(
        self,
        ai_summary: str,
        source_content: str
    ) -> Tuple[float, List[str]]:
        """
        检测完整性（AI是否遗漏重要信息）

        Args:
            ai_summary: AI生成的摘要
            source_content: 源内容

        Returns:
            Tuple[float, List[str]]: (完整性分数, 缺失信息列表)
        """
        # 提取源内容的关键信息
        source_keywords = self._extract_keywords(source_content, top_n=30)
        ai_keywords = self._extract_keywords(ai_summary, top_n=30)

        # 找出AI遗漏的关键信息
        missing_keywords = []
        for keyword in source_keywords[:10]:  # 检查前10个最重要的关键词
            if keyword not in ai_keywords and keyword not in ai_summary:
                missing_keywords.append(f"遗漏关键信息: 「{keyword}」")

        # 计算完整性分数
        if len(source_keywords) == 0:
            completeness_score = 100.0
        else:
            coverage = len([kw for kw in source_keywords if kw in ai_summary]) / len(source_keywords)
            completeness_score = coverage * 100

        return completeness_score, missing_keywords

    def _detect_contradictions(
        self,
        ai_summary: str,
        source_content: str
    ) -> List[str]:
        """
        检测矛盾信息

        Args:
            ai_summary: AI生成的摘要
            source_content: 源内容

        Returns:
            List[str]: 矛盾信息列表
        """
        contradictions = []

        # 检测否定词的不一致使用
        negative_patterns = [
            (r'不(?:是|存在|属于)', '否定'),
            (r'(?:并非|并无|没有)', '强否定'),
            (r'(?:确属|确实|确实是)', '肯定'),
        ]

        for pattern, label in negative_patterns:
            ai_matches = re.findall(pattern, ai_summary)
            source_matches = re.findall(pattern, source_content)

            # 如果AI和源内容的肯定/否定性质不同
            if (label.startswith('否') and ai_matches and not source_matches) or \
               (label.startswith('肯') and source_matches and not ai_matches):
                contradictions.append(f"可能存在语义矛盾: AI使用「{ai_matches[0] if ai_matches else '肯定表述'}」与源内容表述可能不一致")

        return contradictions

    def calculate_consistency(
        self,
        ai_summary: str,
        source_content: str
    ) -> ConsistencyScore:
        """
        计算AI摘要与源内容的一致性评分

        Args:
            ai_summary: AI生成的摘要/推理内容
            source_content: 源网页的实际内容

        Returns:
            ConsistencyScore: 一致性评分结果
        """
        timestamp = datetime.now().isoformat()

        # 预处理
        ai_summary_clean = self._preprocess_text(ai_summary)
        source_content_clean = self._preprocess_text(source_content)

        # 1. 计算语义相似度
        jaccard_sim = self._calculate_jaccard_similarity(ai_summary_clean, source_content_clean)
        semantic_similarity = jaccard_sim * 100

        # 2. 检测事实一致性
        factual_score, factual_diffs = self._detect_factual_consistency(
            ai_summary_clean, source_content_clean
        )

        # 3. 检测完整性
        completeness_score, missing_info = self._detect_completeness(
            ai_summary_clean, source_content_clean
        )

        # 4. 检测矛盾信息
        contradictions = self._detect_contradictions(
            ai_summary_clean, source_content_clean
        )

        # 5. 计算总体一致性分数（加权平均）
        weights = {
            "semantic": 0.3,  # 语义相似度权重
            "factual": 0.4,  # 事实一致性权重
            "completeness": 0.3  # 完整性权重
        }

        overall_score = (
            semantic_similarity * weights["semantic"] +
            factual_score * weights["factual"] +
            completeness_score * weights["completeness"]
        )

        # 计算置信度（基于文本长度）
        confidence = min(1.0, (len(ai_summary_clean) + len(source_content_clean)) / 1000)

        # 6. 整合所有差异信息
        key_differences = []
        key_differences.extend(factual_diffs)
        key_differences.extend(contradictions)

        return ConsistencyScore(
            overall_score=round(overall_score, 2),
            semantic_similarity=round(semantic_similarity, 2),
            factual_consistency=round(factual_score, 2),
            completeness_score=round(completeness_score, 2),
            ai_summary=ai_summary_clean,
            source_content=source_content_clean,
            key_differences=key_differences,
            missing_info=missing_info,
            contradictory_info=contradictions,
            timestamp=timestamp,
            confidence=round(confidence, 2)
        )

    def generate_consistency_report(self, score: ConsistencyScore) -> Dict:
        """
        生成一致性报告

        Args:
            score: 一致性评分结果

        Returns:
            Dict: 格式化的报告
        """
        # 确定一致性等级
        if score.overall_score >= 80:
            level = "高一致性"
            level_color = "green"
        elif score.overall_score >= 60:
            level = "中等一致性"
            level_color = "yellow"
        else:
            level = "低一致性"
            level_color = "red"

        return {
            "consistency_level": level,
            "level_color": level_color,
            "scores": {
                "overall": score.overall_score,
                "semantic": score.semantic_similarity,
                "factual": score.factual_consistency,
                "completeness": score.completeness_score
            },
            "issues": {
                "key_differences": score.key_differences,
                "missing_info": score.missing_info,
                "contradictions": score.contradictory_info
            },
            "recommendation": self._generate_recommendation(score),
            "confidence": score.confidence,
            "timestamp": score.timestamp
        }

    def _generate_recommendation(self, score: ConsistencyScore) -> str:
        """
        根据评分生成建议

        Args:
            score: 一致性评分结果

        Returns:
            str: 建议
        """
        if score.overall_score >= 80:
            return "AI生成内容与源内容高度一致，可以信任。"
        elif score.overall_score >= 60:
            if score.key_differences:
                return f"AI生成内容与源内容基本一致，但存在{len(score.key_differences)}处差异，建议核实。"
            else:
                return "AI生成内容与源内容基本一致，但可能遗漏部分信息。"
        else:
            if score.contradictory_info:
                return f"警告：AI生成内容与源内容存在矛盾（{len(score.contradictory_info)}处），请务必人工核实。"
            else:
                return "AI生成内容与源内容一致性较低，建议人工核实后再使用。"


# 使用示例和测试
def main():
    """测试一致性评分功能"""
    scorer = ConsistencyScorer()

    # 测试案例1：高度一致
    ai_summary1 = "北京是中国的首都，位于华北地区，人口约2100万。"
    source_content1 = "北京，简称京，是中华人民共和国的首都，位于华北地区，人口约2100万。"

    score1 = scorer.calculate_consistency(ai_summary1, source_content1)
    report1 = scorer.generate_consistency_report(score1)

    print("=== 测试案例1：高度一致 ===")
    print(f"总体评分: {score1.overall_score}")
    print(f"一致性等级: {report1['consistency_level']}")
    print(f"建议: {report1['recommendation']}")
    print()

    # 测试案例2：存在差异
    ai_summary2 = "GPT-4模型参数量达到1万亿，训练成本约1亿美元。"
    source_content2 = "GPT-4模型的具体参数量未公开，外界估计在千亿级别，训练成本未知。"

    score2 = scorer.calculate_consistency(ai_summary2, source_content2)
    report2 = scorer.generate_consistency_report(score2)

    print("=== 测试案例2：存在差异 ===")
    print(f"总体评分: {score2.overall_score}")
    print(f"一致性等级: {report2['consistency_level']}")
    print(f"关键差异: {score2.key_differences}")
    print(f"建议: {report2['recommendation']}")
    print()

    # 测试案例3：矛盾信息
    ai_summary3 = "中国的首都是上海，位于华东地区。"
    source_content3 = "北京是中华人民共和国的首都，上海是最大的城市。"

    score3 = scorer.calculate_consistency(ai_summary3, source_content3)
    report3 = scorer.generate_consistency_report(score3)

    print("=== 测试案例3：矛盾信息 ===")
    print(f"总体评分: {score3.overall_score}")
    print(f"一致性等级: {report3['consistency_level']}")
    print(f"矛盾信息: {score3.contradictory_info}")
    print(f"建议: {report3['recommendation']}")


if __name__ == "__main__":
    main()
