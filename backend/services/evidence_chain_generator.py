"""
证据链生成模块
为前端提供结构化的证据链数据，支持可视化展示
"""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime
from urllib.parse import urlparse

from services.evidence_ranker import EvidenceRanker, RankedEvidence
from services.link_validator import LinkValidator, LinkValidationResult
from services.llm_service import sanitize_model_preamble
from utils.text import STOP_WORDS, extract_keywords

# Optional jieba import with graceful fallback
try:
    import jieba
    _JIEBA_AVAILABLE = True
except ImportError:
    jieba = None
    _JIEBA_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class EvidenceHighlight:
    """证据高亮信息"""
    text: str  # 高亮文本
    start_index: int  # 在原文中的起始位置
    end_index: int  # 在原文中的结束位置
    highlight_type: str  # 高亮类型：support/opposing/neutral


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

    # 立场
    stance: str = "neutral"  # 证据立场: support/oppose/neutral
    analysis: str = ""  # AI分析：该证据如何支持/反驳说法（从推理文本中提取）

    # 验证
    link_status: Optional[str] = None  # 链接状态
    publish_date: Optional[str] = None  # 发布日期

    # 标签
    tags: List[str] = field(default_factory=list)  # 标签（如"官方"、"媒体"、"学术"等）


@dataclass
class EvidenceChain:
    """完整的证据链"""
    claim: str  # 待核查的说法
    verdict: str  # 核查结论

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
    total_search_results: int  # 搜索返回的总结果数
    authoritative_sources: int  # 权威来源数
    unique_domain_count: int  # 独立来源域名数
    average_score: float  # 平均评分

    # 元数据
    generated_at: str  # 生成时间
    processing_time_ms: float  # 处理时间

    # AI归纳总结（放在最后，因为有默认值）
    ai_summary: Optional[Dict[str, str]] = None  # AI归纳总结（包含full和brief字段）


class EvidenceChainGenerator:
    """证据链生成器"""

    def __init__(self, glm_client=None, model_name="glm-5.1"):
        """初始化证据链生成器"""
        self.ranker = EvidenceRanker()
        self.link_validator = LinkValidator(timeout=5.0)
        self.glm_client = glm_client
        self.model_name = model_name

    async def generate_evidence_chain(
        self,
        claim: str,
        search_results: List[Dict[str, str]],
        enable_link_validation: bool = False,
        top_k: int = 5,
        reasoning_text: Optional[str] = None,
        total_search_results: int = 0
    ) -> EvidenceChain:
        """
        生成证据链

        Args:
            claim: 待核查的说法
            search_results: 搜索结果列表
            enable_link_validation: 是否验证链接活性
            top_k: 返回Top K个证据
            reasoning_text: LLM推理文本（可选，用于提取证据立场）

        Returns:
            EvidenceChain: 结构化的证据链
        """
        start_time = datetime.now()

        logger.info(f"开始生成证据链: {claim}")
        logger.info(f"搜索结果数量: {len(search_results)}, 链接验证: {enable_link_validation}")

        # 步骤1: 证据排序
        ranked_evidences = self.ranker.rank_evidences(claim, search_results)

        # 步骤1.5: 去重（URL相同或同一域名下标题高度相似）
        ranked_evidences = self._deduplicate_evidences(ranked_evidences)

        # 步骤2: 链接验证（可选）
        link_validations = {}
        if enable_link_validation and ranked_evidences:
            urls = [e.url for e in ranked_evidences[:top_k]]
            try:
                validation_results = await self.link_validator.validate_multiple_links(
                    urls, concurrent_limit=3
                )
                link_validations = {r.url: r for r in validation_results}
                for ev in ranked_evidences[:top_k]:
                    validation = link_validations.get(ev.url)
                    if validation and validation.is_accessible:
                        if validation.final_url and validation.final_url != ev.url:
                            ev.url = validation.final_url
                            # 同步更新域名
                            try:
                                ev.domain = urlparse(validation.final_url).netloc.replace('www.', '')
                            except Exception:
                                pass
                    elif validation and not validation.is_accessible:
                        logger.info(f"链接不可访问但保留证据: {ev.url} ({validation.error_message})")
            except Exception as e:
                logger.error(f"链接验证失败: {e}")

        # 步骤3: 提取Top K证据
        top_evidences = ranked_evidences[:top_k]

        # 步骤3.5: 从推理文本中提取证据立场和分析（如果提供了推理文本）
        stance_map = {}
        analysis_map = {}
        if reasoning_text:
            logger.info("从推理文本中提取证据立场...")
            stance_map = self._extract_stances_from_reasoning(reasoning_text, top_evidences)

            # 同时提取每条证据的分析内容
            analysis_map = self._extract_evidence_analysis_from_reasoning(reasoning_text, top_evidences)

            # 将提取的立场赋值给证据
            for evidence in top_evidences:
                if evidence.url in stance_map:
                    evidence.stance = stance_map[evidence.url]
                    logger.info(f"证据「{evidence.title[:50]}...」立场: {evidence.stance}")
                else:
                    evidence.stance = "neutral"  # 未提取到立场的默认为中性
                    logger.warning(f"证据「{evidence.title[:50]}...」未能提取立场，默认为中性")
        else:
            logger.info("未提供推理文本，所有证据立场默认为中性")

        # 步骤4: 分类证据（支持/反对/中性）- 现在使用立场而非评分
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
                stance=evidence.stance,  # 添加立场字段
                summary=evidence.summary[:200],  # 限制摘要长度
                key_quote=self._extract_key_quote(evidence.summary, highlights),
                analysis=analysis_map.get(evidence.url, ""),
                highlights=highlights,
                link_status=link_status,
                publish_date=evidence.publish_date,
                tags=self._generate_tags(evidence)
            )
            chain_items.append(item)

        # 步骤5.5: 最终保险去重，避免同一报道在不同栏目进入前端卡片。
        chain_items = self._deduplicate_chain_items(chain_items)

        # 步骤6: 重新分类chain_items（因为我们需要EvidenceChainItem类型）
        supporting_items, opposing_items, neutral_items = self._categorize_chain_items(chain_items, claim)

        # 步骤6: 计算统计信息
        authoritative_count = sum(1 for e in chain_items if e.tier == "Tier 1")
        avg_score = sum(e.overall_score for e in chain_items) / len(chain_items) if chain_items else 0
        unique_domain_count = len(set(e.domain for e in chain_items))

        # 步骤7: 生成推理摘要
        reasoning_summary = self._generate_reasoning_summary(claim, chain_items)

        # 步骤8: 提取关键发现
        key_findings = self._extract_key_findings(chain_items)

        # 步骤9: 确定结论
        verdict = self._determine_verdict(chain_items)

        # 步骤10: 不确定性说明
        uncertainty_note = self._generate_uncertainty_note(chain_items)

        # 步骤11: AI归纳总结（优先从推理结果提取，避免第二次LLM调用）
        ai_summary = None
        if reasoning_text:
            ai_summary = self._extract_ai_summary_from_reasoning(reasoning_text)
        if not ai_summary:
            ai_summary = await self._generate_ai_summary(claim, chain_items, verdict)

        processing_time = (datetime.now() - start_time).total_seconds() * 1000

        # 构建证据链
        evidence_chain = EvidenceChain(
            claim=claim,
            verdict=verdict,
            supporting_evidence=[self._evidence_to_dict(e) for e in supporting_items],
            opposing_evidence=[self._evidence_to_dict(e) for e in opposing_items],
            neutral_evidence=[self._evidence_to_dict(e) for e in neutral_items],
            reasoning_summary=reasoning_summary,
            key_findings=key_findings,
            uncertainty_note=uncertainty_note,
            ai_summary=ai_summary,  # 添加AI归纳总结
            total_evidence=len(chain_items),
            total_search_results=total_search_results or len(search_results),
            authoritative_sources=authoritative_count,
            unique_domain_count=unique_domain_count,
            average_score=round(avg_score, 2),
            generated_at=datetime.now().isoformat(),
            processing_time_ms=round(processing_time, 2)
        )

        logger.info(f"证据链生成完成: {len(chain_items)} 个证据, 耗时: {processing_time:.0}ms")

        return evidence_chain

    def _normalize_text_for_dedup(self, text: str) -> str:
        """规范化文本用于去重：统一空格/标点、去掉末尾常见网站后缀。"""
        if not text:
            return ""
        # 统一空格字符
        t = text.replace('　', ' ').replace(' ', ' ')
        # 统一常见全角标点为半角
        t = t.replace('，', ',').replace('。', '.').replace('！', '!').replace('？', '?')
        t = t.replace('：', ':').replace('；', ';').replace('“', '"').replace('”', '"')
        t = t.replace('（', '(').replace('）', ')').replace('【', '[').replace('】', ']')
        t = t.replace('、', ',').replace('—', '-').replace('–', '-')
        # 递归去掉末尾常见栏目/站点后缀：
        # 例如 "-要闻_华商网新闻" 需要先去掉 "_华商网新闻"，再去掉 "-要闻"。
        suffix_pattern = re.compile(
            r'\s*[-_|]\s*(?:'
            r'要闻|社会新闻|社会|新闻|资讯|原创|独家|综合|图片|视频|国内|国际|财经|科技|滚动|热点|专题|频道|客户端|'
            r'[一-龥a-zA-Z0-9]{2,20}(?:网新闻|新闻网|新闻|网|频道|资讯|要闻)'
            r')\s*$',
            flags=re.IGNORECASE
        )
        while True:
            stripped = suffix_pattern.sub('', t).strip()
            if stripped == t:
                break
            t = stripped
        return t.lower().strip()

    def _deduplicate_evidences(
        self,
        evidences: List[RankedEvidence]
    ) -> List[RankedEvidence]:
        """
        对排序后的证据进行去重，保留排名最高的。

        去重维度：
        1. URL 完全相同（去掉查询参数和锚点）
        2. 同一域名下标题高度相似（规范化后互相包含或完全相等，且长度>=10）
        3. 跨域名标题高度相似（检测不同网站转载同一报道）
        4. 同一域名下内容摘要完全重复（同一文章在不同栏目发布，标题不同但内容相同）
        """
        seen_urls: set[str] = set()
        seen_domain_titles: dict[str, set[str]] = {}
        seen_titles: set[str] = set()  # 用于跨域名转载检测（存储规范化后标题）
        seen_domain_summaries: dict[str, set[str]] = {}  # 用于摘要重复检测
        result: List[RankedEvidence] = []

        for ev in evidences:
            # 1. URL 去重：去掉查询参数和锚点，统一大小写
            parsed = urlparse(ev.url)
            url_normalized = (parsed.scheme + "://" + parsed.netloc + parsed.path).rstrip("/").lower()
            if url_normalized in seen_urls:
                logger.info(f"去重：跳过URL重复证据「{ev.title[:50]}...」")
                continue
            seen_urls.add(url_normalized)

            # 规范化标题
            domain = ev.domain.lower()
            title_norm = self._normalize_text_for_dedup(ev.title)

            # 2. 同一域名下标题相似去重
            if domain not in seen_domain_titles:
                seen_domain_titles[domain] = set()

            is_duplicate = False
            for kept_title in seen_domain_titles[domain]:
                # 互相包含且长度都>=10视为重复
                if (title_norm in kept_title or kept_title in title_norm) and len(title_norm) >= 10 and len(kept_title) >= 10:
                    logger.info(f"去重：跳过标题相似证据「{ev.title[:50]}...」")
                    is_duplicate = True
                    break
            if is_duplicate:
                continue
            seen_domain_titles[domain].add(title_norm)

            # 3. 跨域名标题相似去重（检测转载/洗稿）
            # 使用规范化后的标题进行匹配，对细微字符差异更鲁棒
            is_cross_duplicate = False
            for kept_norm in seen_titles:
                # 规范化后完全相等，或互相包含且长度>=10
                if title_norm == kept_norm:
                    logger.info(f"去重：跳过跨域名转载证据（标题完全相同）「{ev.title[:50]}...」")
                    is_cross_duplicate = True
                    break
                if (title_norm in kept_norm or kept_norm in title_norm) and len(title_norm) >= 10 and len(kept_norm) >= 10:
                    logger.info(f"去重：跳过跨域名转载证据（标题相似）「{ev.title[:50]}...」")
                    is_cross_duplicate = True
                    break
            if is_cross_duplicate:
                continue
            seen_titles.add(title_norm)

            # 4. 同一域名下内容摘要完全重复检测（同一文章在不同栏目发布，标题不同但内容相同）
            summary_norm = self._normalize_text_for_dedup(ev.summary)[:200]
            if summary_norm and len(summary_norm) >= 20:
                if domain not in seen_domain_summaries:
                    seen_domain_summaries[domain] = set()
                if summary_norm in seen_domain_summaries[domain]:
                    logger.info(f"去重：跳过内容重复证据（同一文章不同栏目）「{ev.title[:50]}...」")
                    continue
                seen_domain_summaries[domain].add(summary_norm)

            result.append(ev)

        if len(result) < len(evidences):
            logger.info(f"证据去重：{len(evidences)} -> {len(result)}")
        return result

    def _deduplicate_chain_items(self, items: List[EvidenceChainItem]) -> List[EvidenceChainItem]:
        """Final deduplication pass on UI-facing evidence items."""
        seen_domain_titles: set[tuple[str, str]] = set()
        seen_titles: set[str] = set()
        seen_domain_summaries: set[tuple[str, str]] = set()
        result: List[EvidenceChainItem] = []

        for item in items:
            title_norm = self._normalize_text_for_dedup(item.title)
            summary_norm = re.sub(r'\s+', '', self._normalize_text_for_dedup(item.summary))[:240]
            domain = item.domain.lower()

            domain_title_key = (domain, title_norm)
            if title_norm and domain_title_key in seen_domain_titles:
                logger.info(f"证据链最终去重：跳过同源栏目转载「{item.title[:50]}...」")
                continue
            if title_norm and title_norm in seen_titles:
                logger.info(f"证据链最终去重：跳过跨站同题转载「{item.title[:50]}...」")
                continue

            domain_summary_key = (domain, summary_norm)
            if summary_norm and len(summary_norm) >= 80 and domain_summary_key in seen_domain_summaries:
                logger.info(f"证据链最终去重：跳过同源摘要重复「{item.title[:50]}...」")
                continue

            if title_norm:
                seen_domain_titles.add(domain_title_key)
                seen_titles.add(title_norm)
            if summary_norm and len(summary_norm) >= 80:
                seen_domain_summaries.add(domain_summary_key)
            result.append(item)

        if len(result) < len(items):
            logger.info(f"证据链最终去重：{len(items)} -> {len(result)}")
        return result

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
            # 使用立场字段进行分类（而不是overall_score）
            if evidence.stance == "support":
                supporting.append(evidence)
            elif evidence.stance == "oppose":
                opposing.append(evidence)
            else:  # "neutral" or any other value
                neutral.append(evidence)

        return supporting, opposing, neutral

    def _categorize_chain_items(
        self,
        items: List[EvidenceChainItem],
        claim: str
    ) -> tuple[List[EvidenceChainItem], List[EvidenceChainItem], List[EvidenceChainItem]]:
        """
        将EvidenceChainItem类型的证据分为支持/反对/中性三类

        Args:
            items: 证据项列表
            claim: 待核查的说法

        Returns:
            tuple: (支持性证据, 反对性证据, 中性证据)
        """
        supporting = []
        opposing = []
        neutral = []

        for item in items:
            # 使用立场字段进行分类（而不是overall_score）
            if item.stance == "support":
                supporting.append(item)
            elif item.stance == "oppose":
                opposing.append(item)
            else:  # "neutral" or any other value
                neutral.append(item)

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
        summary = evidence.summary

        highlight_type = self._get_highlight_type(evidence.stance)
        candidates = self._extract_highlight_candidates(claim)
        matches = self._find_candidate_matches(summary, candidates)
        if not matches:
            return []

        selected_spans = self._select_assertion_spans(summary, matches, claim, max_spans=2)
        if not selected_spans:
            return []

        return [
            EvidenceHighlight(
                text=summary[start_idx:end_idx],
                start_index=start_idx,
                end_index=end_idx,
                highlight_type=highlight_type,
            )
            for start_idx, end_idx in selected_spans
        ]

    def _select_assertion_spans(
        self,
        summary: str,
        matches: List[tuple[int, int, str]],
        claim: str,
        max_spans: int = 2
    ) -> List[tuple[int, int]]:
        sentence_candidates = self._score_candidate_sentences(summary, matches, claim)
        if not sentence_candidates:
            return []

        ranked = sorted(
            sentence_candidates.items(),
            key=lambda item: (
                item[1]["score"],
                item[1]["hits"],
                item[1]["coverage"],
                -(item[0][1] - item[0][0]),
                -item[0][0],
            ),
            reverse=True
        )

        best_score = ranked[0][1]["score"]
        min_score = max(8, best_score * 0.65)
        selected = []

        for span, data in ranked:
            if len(selected) >= max_spans:
                break
            if data["score"] < min_score:
                continue
            if self._is_overlapping_range(span[0], span[1], selected):
                continue
            selected.append(span)

        return sorted(selected, key=lambda item: item[0])

    def _score_candidate_sentences(
        self,
        summary: str,
        matches: List[tuple[int, int, str]],
        claim: str
    ) -> Dict[tuple[int, int], Dict[str, Any]]:
        sentence_candidates = {}
        claim_keywords = self._extract_keywords_from_claim(claim)

        for start_idx, end_idx, candidate in matches:
            sentence_start, sentence_end = self._find_sentence_boundaries(summary, start_idx, end_idx)
            key = (sentence_start, sentence_end)
            if key not in sentence_candidates:
                sentence_candidates[key] = {
                    "hits": 0,
                    "coverage": 0,
                    "candidates": set(),
                    "text": summary[sentence_start:sentence_end],
                }
            sentence_candidates[key]["hits"] += 1
            sentence_candidates[key]["coverage"] += end_idx - start_idx
            sentence_candidates[key]["candidates"].add(candidate)

        for data in sentence_candidates.values():
            data["score"] = self._score_assertion_sentence(
                data["text"],
                data["candidates"],
                claim_keywords,
            )

        return sentence_candidates

    def _select_best_assertion_span(
        self,
        summary: str,
        matches: List[tuple[int, int, str]],
        claim: str
    ) -> Optional[tuple[int, int]]:
        spans = self._select_assertion_spans(summary, matches, claim, max_spans=1)
        return spans[0] if spans else None

    def _extract_keywords_from_claim(self, claim: str) -> List[str]:
        """从说法中提取关键词。优先使用 jieba 分词，不可用时降级到正则提取。"""
        if _JIEBA_AVAILABLE and jieba is not None:
            words = jieba.cut(claim)
            keywords = [w for w in words if len(w) >= 2 and w not in STOP_WORDS]
            return list(set(keywords))[:10]
        return extract_keywords(claim, top_n=10)

    def _extract_highlight_candidates(self, claim: str) -> List[str]:
        """提取适合在摘要中高亮的候选片段。"""
        candidates = []
        seen = set()

        def add_candidate(value: str):
            value = value.strip(" ，。；：、()（）[]【】\"'")
            if len(value) < 2 or value in seen:
                return
            seen.add(value)
            candidates.append(value)

        url_pattern = re.compile(r"https?://[^\s，。；、】【\"'<>]+")
        host_port_pattern = re.compile(r"(?:localhost|\d{1,3}(?:\.\d{1,3}){3}):\d{2,5}")
        path_pattern = re.compile(r"/api(?:/[A-Za-z0-9._-]+)+")

        for match in url_pattern.findall(claim):
            add_candidate(match)

        for match in host_port_pattern.findall(claim):
            add_candidate(match)

        for match in path_pattern.findall(claim):
            add_candidate(match)

        for keyword in sorted(self._extract_keywords_from_claim(claim), key=len, reverse=True):
            add_candidate(keyword)

        return sorted(candidates, key=len, reverse=True)

    def _get_highlight_type(self, stance: str) -> str:
        if stance == "support":
            return "support"
        if stance == "oppose":
            return "oppose"
        return "neutral"

    def _find_candidate_matches(
        self,
        summary: str,
        candidates: List[str]
    ) -> List[tuple[int, int, str]]:
        matches = []
        used_ranges = []

        for candidate in candidates:
            start_pos = 0
            while True:
                start_idx = summary.find(candidate, start_pos)
                if start_idx == -1:
                    break

                end_idx = start_idx + len(candidate)
                if self._is_overlapping_range(start_idx, end_idx, used_ranges):
                    start_pos = start_idx + 1
                    continue

                matches.append((start_idx, end_idx, candidate))
                used_ranges.append((start_idx, end_idx))
                start_pos = end_idx

        return sorted(matches, key=lambda item: (item[0], -(item[1] - item[0])))

    def _find_sentence_boundaries(
        self,
        text: str,
        start_idx: int,
        end_idx: int
    ) -> tuple[int, int]:
        sentence_delimiters = "。！？；!?\n"

        sentence_start = 0
        for idx in range(start_idx - 1, -1, -1):
            if text[idx] in sentence_delimiters:
                sentence_start = idx + 1
                break

        sentence_end = len(text)
        for idx in range(end_idx, len(text)):
            if text[idx] in sentence_delimiters:
                sentence_end = idx + 1
                break

        while sentence_start < sentence_end and text[sentence_start].isspace():
            sentence_start += 1
        while sentence_end > sentence_start and text[sentence_end - 1].isspace():
            sentence_end -= 1

        return sentence_start, sentence_end

    def _score_assertion_sentence(
        self,
        sentence: str,
        candidates: set[str],
        claim_keywords: List[str]
    ) -> float:
        score = sum(len(candidate) for candidate in candidates)

        source_cues = [
            "数据显示", "通报", "公告", "研究显示", "抽检结果显示",
            "证实", "表明", "指出", "发布", "回应", "报告显示"
        ]
        negation_cues = [
            "不存在", "未检出", "未发现", "并非", "不是", "不足以证明",
            "不能证明", "尚无证据", "没有证据", "无证据表明"
        ]
        fact_cues = [
            "新增", "下降", "上升", "确诊", "检出", "达到", "转运",
            "处罚", "显示", "证据", "结果", "病例", "环比", "同比"
        ]
        rumor_cues = [
            "网传", "传言", "说法", "传播", "热议", "讨论",
            "社交平台", "网友", "引发关注", "话题"
        ]

        score += sum(8 for cue in source_cues if cue in sentence)
        score += sum(7 for cue in negation_cues if cue in sentence)
        score += sum(4 for cue in fact_cues if cue in sentence)
        score += sum(3 for keyword in claim_keywords if keyword in sentence)

        if re.search(r'\d+(?:\.\d+)?[%％例年月日天家次项名万亿千百]', sentence):
            score += 6
        elif re.search(r'\d+(?:\.\d+)?', sentence):
            score += 3

        if re.search(r'(国家统计局|卫健委|市场监管|医院|研究|法院|警方|教育局|政府)', sentence):
            score += 6

        rumor_penalty = sum(6 for cue in rumor_cues if cue in sentence)
        if rumor_penalty:
            score -= rumor_penalty
            if not any(cue in sentence for cue in source_cues + negation_cues):
                score -= 6

        return score

    def _is_overlapping_range(
        self,
        start_idx: int,
        end_idx: int,
        used_ranges: List[tuple[int, int]]
    ) -> bool:
        return any(start_idx < used_end and end_idx > used_start for used_start, used_end in used_ranges)

    def _extract_key_quote(
        self,
        summary: str,
        highlights: Optional[List[EvidenceHighlight]] = None
    ) -> str:
        """从摘要中提取关键引用"""
        if highlights:
            return highlights[0].text[:150]
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
            "stance": evidence.stance,  # 添加立场字段
            "scores": {
                "overall": evidence.overall_score,
                "relevance": evidence.relevance_score,
                "authority": evidence.authority_score,
                "freshness": evidence.freshness_score
            },
            "content": {
                "summary": evidence.summary,
                "key_quote": evidence.key_quote,
                "analysis": evidence.analysis
            },
            "highlights": [
                {
                    "text": h.text,
                    "start_index": h.start_index,
                    "end_index": h.end_index,
                    "type": h.highlight_type,
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
        """生成推理过程摘要：聚焦证据质量、来源分布与分析方法（不重复结论）"""
        if not evidences:
            return f"未找到关于「{claim}」的有效证据。"

        total = len(evidences)
        # 来源等级分布
        tier1 = sum(1 for e in evidences if e.tier == "Tier 1")
        tier2 = sum(1 for e in evidences if e.tier == "Tier 2")
        tier3 = total - tier1 - tier2

        # 独立来源域名数
        unique_domains = len(set(e.domain for e in evidences))

        # 时效性
        avg_freshness = sum(e.freshness_score for e in evidences) / total if total else 0

        # 平均证据质量
        avg_score = sum(e.overall_score for e in evidences) / total if total else 0

        summary = f"共检索到{total}条证据，覆盖{unique_domains}个不同域名来源。"
        if total >= 3 and unique_domains < total * 0.6:
            summary += " 其中部分证据可能存在转载或改写关系，证据数量不能直接等同于独立信源数量。"

        # 来源质量分析
        source_parts = []
        if tier1 > 0:
            source_parts.append(f"{tier1}条来自官方/权威渠道")
        if tier2 > 0:
            source_parts.append(f"{tier2}条来自主流媒体")
        if tier3 > 0:
            source_parts.append(f"{tier3}条来自其他网络来源")
        if source_parts:
            summary += " 其中" + "，".join(source_parts) + "。"

        # 时效性评估
        if avg_freshness >= 70:
            summary += " 证据整体时效性良好，多数为近期信息。"
        elif avg_freshness >= 40:
            summary += " 证据时效性一般，部分信息可能已过时。"
        else:
            summary += " 证据时效性偏低，需注意信息的适用性。"

        # 证据质量评估
        if avg_score >= 70:
            summary += " 综合评估证据质量较高，来源可信度较好。"
        elif avg_score >= 50:
            summary += " 综合评估证据质量中等，建议结合更多来源验证。"

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

    def _determine_verdict(self, evidences: List[EvidenceChainItem]) -> str:
        """
        基于证据立场（支持/反对/中性）确定核查结论。
        """
        if not evidences:
            return "信息不足，无法判断"

        supporting_count = sum(1 for e in evidences if e.stance == "support")
        opposing_count = sum(1 for e in evidences if e.stance == "oppose")
        neutral_count = sum(1 for e in evidences if e.stance == "neutral")
        logger.info(f"证据立场统计 - 支持: {supporting_count}, 反对: {opposing_count}, 中性: {neutral_count}")

        relevant_count = supporting_count + opposing_count
        if relevant_count == 0:
            verdict = "证据不足，无法判断"
        else:
            support_ratio = supporting_count / relevant_count
            if support_ratio >= 0.7:
                verdict = "属实"
            elif support_ratio <= 0.3:
                verdict = "不实"
            else:
                verdict = "部分属实，存在争议"

        logger.info(f"结论: {verdict}")
        return verdict

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

        # 检查独立信源（跨域名转载检测）
        unique_domains = len(set(e.domain for e in evidences))
        total_count = len(evidences)
        if total_count >= 3 and unique_domains < total_count * 0.6:
            notes.append("多个证据可能来自同一原始报道的多次转载或改写，表面交叉核实但实际信息源单一，结论可信度有限。")

        return "；".join(notes) if notes else "证据较为一致，可信度较高。"

    async def _generate_ai_summary(
        self,
        claim: str,
        evidences: List[EvidenceChainItem],
        verdict: str
    ) -> str:
        """
        使用LLM生成AI归纳总结（与普通搜索引擎的核心区别）

        Args:
            claim: 待核查的说法
            evidences: 证据项列表
            verdict: 核查结论

        Returns:
            str: AI归纳总结文本
        """
        if not self.glm_client:
            logger.warning("LLM客户端未初始化，跳过AI归纳总结")
            return None

        try:
            # 准备证据摘要（仅使用前5个证据以节省token）
            top_evidences = evidences[:5]
            evidence_summary = ""

            for i, ev in enumerate(top_evidences, 1):
                stance_text = {"support": "支持", "oppose": "反对", "neutral": "中性"}.get(ev.stance, "中性")
                evidence_summary += f"""
证据{i}：{ev.title}
- 立场：{stance_text}
- 来源：{ev.domain} ({ev.tier})
- 摘要：{ev.summary[:150]}...
"""

            # 构建prompt
            prompt = f"""你是一个专业的事实核查分析助手。基于以下证据，对待核查的说法进行**深度归纳总结**。

【待核查说法】
{claim}

【核查结论】
{verdict}

【证据概览】
{evidence_summary}

请提供一份简洁但有深度的归纳总结（200-300字），包括：

1. **核心事实提取**：从证据中提炼3-5个关键信息点
2. **洞察分析**：
   - 证据的共同主题和趋势
   - 信息来源的多样性分析（官方/媒体/学术等）
   - 时间维度的观察（近期/历史）
3. **与说法的关系**：
   - 哪些部分被证实？
   - 哪些部分存在争议或无法确定？
   - 是否有需要注意的限定条件？

**重要要求**：
- 直接输出归纳总结内容，不要重复上述问题或标题
- 开头先用1-2句话概括核心结论（作为简短摘要），必须是自然语言段落，不要出现"核心事实提取""洞察分析"等分节标题
- 然后详细展开分析
- 语言简洁专业，避免重复
- 突出AI的归纳分析能力，而非简单罗列证据
- 使用项目符号（•）列出要点
- 每个项目符号必须单独占一行，禁止把两个项目符号写在同一行

请直接开始输出归纳总结："""

            logger.info("开始调用LLM生成AI归纳总结...")

            # 🔥 自动重试机制：检测截断并自动增加max_tokens
            # v0.5.2 优化：从1500提升到3000，避免复杂说法触发重试（节省~2分钟）
            max_attempts = 3  # 最多重试3次
            base_max_tokens = 3000  # 初始max_tokens（提升以避免复杂说法的重试开销）
            response = None
            actual_max_tokens = base_max_tokens
            attempt_count = 0  # 记录实际尝试次数

            for attempt in range(max_attempts):
                attempt_count = attempt + 1
                logger.info(f"🔄 尝试 {attempt_count}/{max_attempts}，max_tokens={actual_max_tokens}")

                response = await self.glm_client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=actual_max_tokens
                )

                # 🔍 检测是否被截断
                if hasattr(response, 'choices') and len(response.choices) > 0:
                    choice = response.choices[0]
                    finish_reason = getattr(choice, 'finish_reason', None)
                    content = getattr(choice.message, 'content', '')

                    logger.info(f"📊 finish_reason: {finish_reason}, content长度: {len(content) if content else 0}")

                    # 检查是否被截断
                    is_truncated = (
                        finish_reason == 'length' or  # 达到token上限
                        (content and len(content) > 100 and not content[-1] in '。！？.!?，,、')  # 内容没有结束标点
                    )

                    if is_truncated and attempt < max_attempts - 1:
                        # 截断了，增加max_tokens重试
                        old_tokens = actual_max_tokens
                        actual_max_tokens += 500  # 每次增加500 tokens
                        logger.warning(f"⚠️ 内容被截断，增加max_tokens: {old_tokens} → {actual_max_tokens}")
                        continue
                    elif is_truncated:
                        # 最后一次尝试仍然截断，记录警告但继续处理
                        logger.error(f"❌ 内容仍然被截断（max_tokens={actual_max_tokens}），将使用不完整内容")
                        break
                    else:
                        # 内容完整，退出循环
                        logger.info(f"✅ 内容完整生成（finish_reason={finish_reason}）")
                        break
                else:
                    logger.error("❌ 响应格式异常，无法检测截断")
                    break


            # 🔍 详细调试日志：检查完整响应结构
            logger.info(f"📦 LLM响应类型: {type(response)}")

            # 🔍 监控日志：记录实际 token 使用
            if hasattr(response, 'usage'):
                usage = response.usage
                logger.info(f"📊 Token使用监控: {usage.completion_tokens} tokens (上限{actual_max_tokens}), "
                           f"prompt_tokens: {usage.prompt_tokens}, "
                           f"total_tokens: {usage.total_tokens}")
            else:
                logger.warning("⚠️ 响应中没有 usage 字段，无法记录 token 使用情况")

            # 检查choices字段
            if hasattr(response, 'choices'):
                logger.info(f"📦 response.choices 存在")
                logger.info(f"📦 choices类型: {type(response.choices)}")
                logger.info(f"📦 choices长度: {len(response.choices)}")

                if len(response.choices) > 0:
                    choice = response.choices[0]
                    logger.info(f"📦 choices[0]类型: {type(choice)}")
                    logger.info(f"📦 choices[0]对象: {choice}")

                    # 检查message字段
                    if hasattr(choice, 'message'):
                        logger.info(f"📦 choices[0].message 存在")
                        logger.info(f"📦 message类型: {type(choice.message)}")
                        logger.info(f"📦 message对象: {choice.message}")

                        # 尝试获取content
                        if hasattr(choice.message, 'content'):
                            content = choice.message.content
                            logger.info(f"📦 message.content类型: {type(content)}")
                            logger.info(f"📦 message.content长度: {len(content) if content else 0}")
                            logger.info(f"📦 message.content前100字符: {content[:100] if content else '(空)'}")

                            # 检查是否是空字符串
                            if content == "":
                                logger.error("❌ message.content 是空字符串！")
                                logger.error(f"❌ 完整message属性: {dir(choice.message)}")
                                # 尝试其他可能的字段
                                if hasattr(choice.message, 'text'):
                                    logger.info(f"📦 尝试message.text: {choice.message.text[:100]}")
                                if hasattr(choice, 'text'):
                                    logger.info(f"📦 尝试choice.text: {choice.text[:100]}")
                            else:
                                ai_summary = content.strip()
                        else:
                            logger.error("❌ message对象没有content属性")
                            logger.error(f"❌ message可用的属性: {dir(choice.message)}")
                    else:
                        logger.error("❌ choices[0]没有message属性")
                        logger.error(f"❌ choice可用的属性: {dir(choice)}")
                else:
                    logger.error("❌ choices数组为空")
            else:
                logger.error("❌ response对象没有choices属性")
                logger.error(f"❌ response可用的属性: {dir(response)}")

            # 🔧 修复：调整优先级，先读取 content（最终总结），再读取 reasoning_content（思考过程）
            full_summary = None
            if hasattr(choice.message, 'content') and choice.message.content and choice.message.content.strip():
                full_summary = choice.message.content.strip()
                logger.info(f"✅ 从 content 获取到内容，长度: {len(full_summary)} 字符")
            elif hasattr(choice.message, 'reasoning_content') and choice.message.reasoning_content:
                # reasoning_content 可能包含完整的思考过程
                reasoning_content = choice.message.reasoning_content.strip()
                logger.info(f"✅ 从 reasoning_content 获取到内容，长度: {len(reasoning_content)} 字符")

                # 尝试从 reasoning_content 中提取最终总结（跳过前面的思考过程）
                # 寻找常见的总结开始标记
                summary_markers = [
                    "*草稿：*",
                    "草稿：",
                    "### ",
                    "**核心事实",
                    "该说法",
                    "证据证实"
                ]

                # 尝试找到最后一个标记（最终总结通常在思考过程的末尾）
                last_marker_pos = -1
                for marker in summary_markers:
                    pos = reasoning_content.rfind(marker)
                    if pos != -1 and pos > last_marker_pos:
                        last_marker_pos = pos

                if last_marker_pos > 0:
                    full_summary = reasoning_content[last_marker_pos:].strip()
                    logger.info(f"✅ 从 reasoning_content 中提取最终总结，长度: {len(full_summary)} 字符")
                else:
                    # 如果找不到标记，直接使用整个 reasoning_content
                    full_summary = reasoning_content
                    logger.warning(f"⚠️ 未能在 reasoning_content 中找到总结标记，使用全部内容")
            else:
                logger.error("❌ reasoning_content 和 content 都是空的！")
                return None

            # 生成简短摘要（前150个字符或第一句话）
            brief_summary = self._extract_brief_summary(full_summary)
            logger.info(f"📝 简短摘要: {brief_summary}")

            # 🔥 v0.5.2 记录重试信息（用于前端透明反馈）
            retry_info = {
                "attempts": attempt_count,
                "final_max_tokens": actual_max_tokens,
                "base_max_tokens": base_max_tokens
            }
            logger.info(f"📊 重试信息: {attempt_count}次尝试, 最终max_tokens={actual_max_tokens}")

            # 返回字典结构（包含完整总结、简短摘要、重试信息）
            result = {
                "full": full_summary,
                "brief": brief_summary,
                "retry_info": retry_info  # v0.5.2 新增：用于前端显示透明反馈
            }

            logger.info(f"AI归纳总结生成完成，完整长度: {len(full_summary)} 字符，简短长度: {len(brief_summary)} 字符")

            return result

        except Exception as e:
            logger.error(f"AI归纳总结生成失败: {e}")
            return None

    def _extract_ai_summary_from_reasoning(self, reasoning_text: str):
        """从第一次LLM推理结果中提取归纳总结（避免第二次LLM调用）"""
        if not reasoning_text:
            return None

        # 匹配 ### 5. 归纳总结 后的内容
        summary_section = re.search(
            r'###\s*5[\.、]\s*.*?(?:结论判定|归纳总结|结论).*?\n+(.+?)(?=###|$)',
            reasoning_text,
            re.IGNORECASE | re.DOTALL
        )

        if not summary_section:
            # 降级：匹配"归纳总结"关键词后的内容
            fallback = re.search(
            r'(?:归纳总结|结论)[：:]*\s*\n*(.+?)(?=###|$)',
                reasoning_text,
                re.IGNORECASE | re.DOTALL
            )
            if fallback:
                summary_section = fallback
            else:
                logger.warning("未能从推理结果中提取结论判定")
                return None

        full_text = summary_section.group(1).strip()
        # 清理 Markdown 链接但保留加粗标记
        full_text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', full_text)
        full_text = self._normalize_ai_summary_format(full_text)

        # brief 提取第一句话（核心结论）
        brief = self._extract_brief_summary(full_text)

        logger.info(f"从推理结果中提取归纳总结: {len(full_text)}字符")
        return {
            "full": full_text,
            "brief": brief,
            "retry_info": None
        }

    def _extract_brief_summary(self, full_summary: str) -> str:
        """从完整归纳总结中提取简短摘要（3-5句，目标200-350字）"""
        if not full_summary:
            return "暂无摘要"

        # 清理 Markdown 标记但保留文字
        text = self._normalize_ai_summary_format(full_summary)
        text = self._keep_summary_opening_segment(text)
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
        text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^[•\-\*]\s+', '', text, flags=re.MULTILINE)
        text = self._remove_summary_section_headings(text)
        text = text.strip()

        # 提取完整句子（以。！？结尾）
        sentences = []
        current = ''
        text_length = len(text)
        for idx, char in enumerate(text):
            current += char
            is_decimal_point = (
                char == '.'
                and idx > 0
                and idx + 1 < text_length
                and text[idx - 1].isdigit()
                and text[idx + 1].isdigit()
            )
            if char in '。！？!?' or (char == '.' and not is_decimal_point):
                sentence = current.strip()
                if len(sentence) > 10:
                    sentences.append(sentence)
                current = ''
                if len(sentences) >= 3 and sum(len(s) for s in sentences) >= 200:
                    break
                if len(sentences) >= 5:
                    break

        # 如果没找到完整句子，回退到前350字符
        if not sentences:
            return text[:347] + '...' if len(text) > 350 else text or '暂无摘要'

        brief = ''.join(sentences)

        # 超过400字截取到句号
        if len(brief) > 400:
            for i in range(399, 150, -1):
                if brief[i] in '。！？.!?':
                    brief = brief[:i + 1]
                    break
            else:
                brief = brief[:347] + '...'

        return brief or '暂无摘要'

    def _normalize_ai_summary_format(self, text: str) -> str:
        """规整模型摘要格式，避免列表项粘连到上一句。"""
        if not text:
            return ""

        normalized = sanitize_model_preamble(text)
        normalized = normalized.replace('\r\n', '\n').replace('\r', '\n')
        normalized = re.sub(r'[ \t]+\n', '\n', normalized)
        structural_labels = (
            '关键误导点',
            '身份确认',
            '财富性质澄清',
            '核心结论',
            '结论判定',
            '事实核查结论',
            '说法拆解',
        )
        normalized = re.sub(
            rf'(?<!\n)(?=({"|".join(map(re.escape, structural_labels))})：)',
            '\n',
            normalized,
        )
        normalized = re.sub(r'(?<=[。！？.!?])\s+(?=(?:[-•*]|\d+[\.、])\s+)', '\n', normalized)
        normalized = re.sub(r'(?<=[。！？.!?])(?=(?:[-•*]|\d+[\.、])\s+)', '\n', normalized)
        normalized = re.sub(r'\n{2,}', '\n', normalized)
        return normalized.strip()

    def _keep_summary_opening_segment(self, text: str) -> str:
        """优先保留模型输出中的开头摘要段，丢弃展开分析。"""
        if not text:
            return ""

        split_markers = [
            r'【\s*展开分析\s*】',
            r'^\s*展开分析[：:]?\s*$',
            r'^\s*(?:[-•*]\s*)?\**核心事实提取\**[：:]\s*',
            r'^\s*(?:[-•*]\s*)?\**深度洞察\**[：:]\s*',
            r'^\s*(?:[-•*]\s*)?\**洞察分析\**[：:]\s*',
            r'^\s*(?:[-•*]\s*)?\**与说法的(?:精确对比|关系)\**[：:]\s*',
        ]

        opening = text
        for marker in split_markers:
            match = re.search(marker, opening, flags=re.MULTILINE)
            if match:
                opening = opening[:match.start()]
                break

        opening = re.sub(r'【\s*开头段落\s*】\s*', '', opening)
        opening = re.sub(r'^\s*开头段落[：:]?\s*', '', opening, flags=re.MULTILINE)
        return opening.strip() or text

    def _remove_summary_section_headings(self, text: str) -> str:
        """从简短摘要候选文本中移除结构化分节标题。"""
        section_headings = (
            "开头段落",
            "展开分析",
            "核心事实提取",
            "核心事实",
            "深度洞察",
            "洞察分析",
            "与说法的精确对比",
            "与说法的关系",
            "展开分析",
        )

        cleaned_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            stripped = re.sub(r'^[•\-\*]\s*', '', stripped)
            stripped = re.sub(r'^\d+[\.、]\s*', '', stripped)
            stripped = stripped.strip()

            heading_only = stripped.strip('* ：:') in section_headings
            if heading_only:
                continue

            for heading in section_headings:
                stripped = re.sub(
                    rf'^\**{re.escape(heading)}\**[：:]\s*(?=(?:[-•*]|\d+[\.、])\s+)',
                    '',
                    stripped
                )

            if stripped:
                cleaned_lines.append(stripped)

        return "\n".join(cleaned_lines)

    def _extract_stances_from_reasoning(
        self,
        reasoning_text: str,
        evidences: List[RankedEvidence]
    ) -> Dict[str, str]:
        """
        从LLM推理文本中提取证据立场信息

        Args:
            reasoning_text: LLM生成的推理文本
            evidences: 证据列表

        Returns:
            Dict[str, str]: URL到立场的映射 {"support", "oppose", "neutral"}
        """
        logger.info("开始从推理文本中提取证据立场...")

        stance_map = {}

        # 策略1: 精确格式匹配 - **证据 [N] [标题](URL)** - **立场**：**支持/反对/中性**
        patterns_strict = [
            re.compile(
                r'\*\*证据\s*\[\d+\]\s*\[([^\]]+)\]\(([^)]+)\).*?\*\*立场\*\*[：:]\s*\*\*(支持|反对|中性)\*\*',
                re.DOTALL
            ),
            # 新prompt格式: **证据 [N] [标题](URL)** - **立场**：**支持**
            re.compile(
                r'\*\*证据\s*\[\d+\]\s*\[([^\]]+)\]\(([^)]+)\)[^*]*\*\*立场\*\*[：:]\s*\*\*(支持|反对|中性)\*\*',
            ),
        ]

        for pattern in patterns_strict:
            for match in pattern.finditer(reasoning_text):
                title = match.group(1).strip()
                url = match.group(2).strip()
                stance_cn = match.group(3).strip()

                stance_en = {"支持": "support", "反对": "oppose", "中性": "neutral"}.get(stance_cn, "neutral")
                stance_map[url] = stance_en
                logger.info(f"✓ 精确匹配立场: {title[:50]}... -> {stance_cn}")

        # 策略2: 宽松匹配 - 在URL附近查找立场关键词（无需严格格式）
        if len(stance_map) < len(evidences):
            # 构建每条证据在文本中的位置 -> 立场 映射
            # 将文本按证据URL分割，每段对应一条证据
            url_positions = []
            for e in evidences:
                pos = reasoning_text.find(e.url)
                if pos != -1:
                    url_positions.append((pos, e.url, e.title))

            # 按位置排序
            url_positions.sort(key=lambda x: x[0])

            for idx, (pos, url, title) in enumerate(url_positions):
                if url in stance_map:
                    continue  # 已经精确匹配过了

                # 取当前URL到下一个URL之间的文本作为该证据的分析区域
                start = pos
                end = url_positions[idx + 1][0] if idx + 1 < len(url_positions) else min(len(reasoning_text), pos + 800)
                section = reasoning_text[start:end]

                # 在该区域查找立场关键词
                # 优先匹配明确的立场声明
                stance_patterns = [
                    r'\*\*立场\*\*[：:]\s*\*\*(支持|反对|中性)\*\*',
                    r'立场[：:]\s*\*\*(支持|反对|中性)\*\*',
                    r'\*\*立场\*\*[：:](支持|反对|中性)',
                    r'立场[：:]\s*(支持|反对|中性)',
                ]

                found = False
                for sp in stance_patterns:
                    m = re.search(sp, section)
                    if m:
                        stance_cn = m.group(1).strip()
                        stance_en = {"支持": "support", "反对": "oppose", "中性": "neutral"}.get(stance_cn, "neutral")
                        stance_map[url] = stance_en
                        logger.info(f"✓ 宽松匹配立场: {title[:50]}... -> {stance_cn}")
                        found = True
                        break

                if not found:
                    # 最后尝试：在整个section中查找立场关键词的简单出现
                    # 使用计数判断（出现次数最多的立场）
                    support_count = len(re.findall(r'\*\*支持\*\*|立场.*?支持', section))
                    oppose_count = len(re.findall(r'\*\*反对\*\*|立场.*?反对', section))
                    neutral_count = len(re.findall(r'\*\*中性\*\*|立场.*?中性', section))

                    if support_count > oppose_count and support_count > neutral_count:
                        stance_map[url] = "support"
                        logger.info(f"✓ 统计推断立场: {title[:50]}... -> 支持")
                    elif oppose_count > support_count and oppose_count > neutral_count:
                        stance_map[url] = "oppose"
                        logger.info(f"✓ 统计推断立场: {title[:50]}... -> 反对")
                    elif neutral_count > 0:
                        stance_map[url] = "neutral"
                        logger.info(f"✓ 统计推断立场: {title[:50]}... -> 中性")
                    else:
                        logger.debug(f"⚠️ 无法提取立场: {url}")

        logger.info(f"从推理文本中共提取到 {len(stance_map)}/{len(evidences)} 个证据的立场信息")

        no_stance_count = sum(1 for e in evidences if e.url not in stance_map)
        if no_stance_count > 0:
            logger.warning(f"⚠️ 有 {no_stance_count} 个证据未能提取立场，将默认为中性")
            for e in evidences:
                if e.url not in stance_map:
                    logger.debug(f"未匹配证据: {e.title[:50]}")

        return stance_map

    def _extract_evidence_analysis_from_reasoning(
        self,
        reasoning_text: str,
        evidences: List[RankedEvidence]
    ) -> Dict[str, str]:
        """
        从模型推理文本中提取每条证据的分析内容。

        模型在第1节"证据立场分析"中的输出格式：
        **证据 [N] [标题](URL)** - 来源：**媒体** - **立场**：**支持** - 分析：该证据...

        Args:
            reasoning_text: 模型生成的推理文本
            evidences: 证据列表

        Returns:
            Dict[str, str]: URL到分析文本的映射
        """
        logger.info("开始从推理文本中提取证据分析...")
        analysis_map = {}

        # 策略1: 精确匹配单行格式
        pattern_strict = re.compile(
            r'\*\*证据\s*\[\d+\]\s*\[([^\]]+)\]\(([^)]+)\).*?'
            r'[–—\-]\s*分析[：:]\s*([^\n]+)',
        )
        for match in pattern_strict.finditer(reasoning_text):
            url = match.group(2).strip()
            analysis = match.group(3).strip()
            analysis = re.sub(r'\*\*', '', analysis)
            analysis = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', analysis)
            if len(analysis) > 5:
                analysis_map[url] = analysis[:300]
                logger.info(f"✓ 精确匹配分析: {url[:60]}... -> {analysis[:60]}...")

        # 策略2: 多行分析（分析内容跨越多行）
        if len(analysis_map) < len(evidences):
            pattern_multiline = re.compile(
                r'\*\*证据\s*\[\d+\]\s*\[([^\]]+)\]\(([^)]+)\).*?'
                r'[–—\-]\s*分析[：:]\s*(.*?)(?=\*\*证据\s*\[|\n###|\Z)',
                re.DOTALL
            )
            for match in pattern_multiline.finditer(reasoning_text):
                url = match.group(2).strip()
                if url in analysis_map:
                    continue
                analysis = match.group(3).strip()
                lines = [l.strip() for l in analysis.split('\n') if l.strip()]
                if lines:
                    analysis = lines[0]
                analysis = re.sub(r'\*\*', '', analysis)
                analysis = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', analysis)
                if len(analysis) > 5:
                    analysis_map[url] = analysis[:300]
                    logger.info(f"✓ 多行匹配分析: {url[:60]}... -> {analysis[:60]}...")

        # 策略3: 按URL分段，在证据段落内查找"分析："
        if len(analysis_map) < len(evidences):
            url_positions = []
            for e in evidences:
                pos = reasoning_text.find(e.url)
                if pos != -1:
                    url_positions.append((pos, e.url, e.title))
            url_positions.sort(key=lambda x: x[0])

            for idx, (pos, url, title) in enumerate(url_positions):
                if url in analysis_map:
                    continue

                start = pos
                end = url_positions[idx + 1][0] if idx + 1 < len(url_positions) else min(len(reasoning_text), pos + 800)
                section = reasoning_text[start:end]

                analysis_match = re.search(
                    r'[–—\-]\s*分析[：:]\s*([^\n].*?)(?=\n\s*\n|\n\*\*|\Z)',
                    section,
                    re.DOTALL
                )
                if analysis_match:
                    analysis = analysis_match.group(1).strip()
                    analysis = re.sub(r'\*\*', '', analysis)
                    analysis = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', analysis)
                    if len(analysis) > 5:
                        analysis_map[url] = analysis[:300]
                        logger.info(f"✓ 分段匹配分析: {title[:50]}...")

        logger.info(f"从推理文本中共提取到 {len(analysis_map)}/{len(evidences)} 个证据的分析")
        return analysis_map
