"""
证据链生成模块
为前端提供结构化的证据链数据，支持可视化展示
"""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
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

    # 立场
    stance: str = "neutral"  # 证据立场: support/oppose/neutral

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

    # AI归纳总结（放在最后，因为有默认值）
    ai_summary: Optional[Dict[str, str]] = None  # AI归纳总结（包含full和brief字段）


class EvidenceChainGenerator:
    """证据链生成器"""

    def __init__(self, glm_client=None):
        """初始化证据链生成器"""
        self.ranker = EvidenceRanker()
        self.link_validator = LinkValidator(timeout=5.0)
        self.glm_client = glm_client  # GLM客户端，用于立场检测

    async def generate_evidence_chain(
        self,
        claim: str,
        search_results: List[Dict[str, str]],
        enable_link_validation: bool = False,
        top_k: int = 5,
        reasoning_text: Optional[str] = None
    ) -> EvidenceChain:
        """
        生成证据链

        Args:
            claim: 待核查的说法
            search_results: 搜索结果列表
            enable_link_validation: 是否验证链接活性
            top_k: 返回Top K个证据
            reasoning_text: GLM-5推理文本（可选，用于提取证据立场）

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

        # 步骤3.5: 从推理文本中提取证据立场（如果提供了推理文本）
        if reasoning_text:
            logger.info("从推理文本中提取证据立场...")
            stance_map = self._extract_stances_from_reasoning(reasoning_text, top_evidences)

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
                key_quote=self._extract_key_quote(evidence.summary),
                highlights=highlights,
                link_status=link_status,
                publish_date=evidence.publish_date,
                tags=self._generate_tags(evidence)
            )
            chain_items.append(item)

        # 步骤6: 重新分类chain_items（因为我们需要EvidenceChainItem类型）
        supporting_items, opposing_items, neutral_items = self._categorize_chain_items(chain_items, claim)

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

        # 步骤11: AI归纳总结（与普通搜索引擎的核心区别）
        ai_summary = await self._generate_ai_summary(claim, chain_items, verdict)

        processing_time = (datetime.now() - start_time).total_seconds() * 1000

        # 构建证据链
        evidence_chain = EvidenceChain(
            claim=claim,
            verdict=verdict,
            confidence=confidence,
            supporting_evidence=[self._evidence_to_dict(e) for e in supporting_items],
            opposing_evidence=[self._evidence_to_dict(e) for e in opposing_items],
            neutral_evidence=[self._evidence_to_dict(e) for e in neutral_items],
            reasoning_summary=reasoning_summary,
            key_findings=key_findings,
            uncertainty_note=uncertainty_note,
            ai_summary=ai_summary,  # 添加AI归纳总结
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

                    # 确定高亮类型（使用立场字段而不是overall_score）
                    if evidence.stance == "support":
                        highlight_type = "support"
                    elif evidence.stance == "oppose":
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
            "stance": evidence.stance,  # 添加立场字段
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
        """生成推理过程摘要（基于立场而非评分）"""
        if not evidences:
            return f"未找到关于「{claim}」的有效证据。"

        # 统计各立场证据数量
        supporting_count = sum(1 for e in evidences if e.stance == "support")
        opposing_count = sum(1 for e in evidences if e.stance == "oppose")
        neutral_count = sum(1 for e in evidences if e.stance == "neutral")

        # 统计权威来源
        authoritative_count = sum(1 for e in evidences if e.tier == "Tier 1")

        summary = f"基于{len(evidences)}条证据进行分析，"

        # 根据立场分布判断
        if supporting_count > opposing_count * 2:
            summary += f"绝大多数证据（{supporting_count}条）支持该说法，仅{opposing_count}条反对。"
        elif opposing_count > supporting_count * 2:
            summary += f"绝大多数证据（{opposing_count}条）反对该说法，仅{supporting_count}条支持。"
        elif supporting_count > opposing_count:
            summary += f"多数证据支持该说法（{supporting_count}条支持 vs {opposing_count}条反对）。"
        elif opposing_count > supporting_count:
            summary += f"多数证据反对该说法（{opposing_count}条反对 vs {supporting_count}条支持）。"
        else:
            summary += f"支持与反对证据数量相当（各{supporting_count}条），存在争议。"

        # 中性证据
        if neutral_count > 0:
            summary += f" 另有{neutral_count}条中立证据提供背景信息。"

        # 权威来源
        if authoritative_count > 0:
            summary += f" 其中包含{authoritative_count}个权威来源。"

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
        """
        确定核查结论和置信度

        新逻辑：基于证据立场（支持/反对/中性）而非评分
        """
        if not evidences:
            return "信息不足，无法判断", 0.0

        # 统计各立场证据数量
        supporting_count = sum(1 for e in evidences if e.stance == "support")
        opposing_count = sum(1 for e in evidences if e.stance == "oppose")
        neutral_count = sum(1 for e in evidences if e.stance == "neutral")

        total_count = len(evidences)
        logger.info(f"证据立场统计 - 支持: {supporting_count}, 反对: {opposing_count}, 中性: {neutral_count}")

        # 计算支持率（支持证据 / (支持+反对)）
        relevant_count = supporting_count + opposing_count
        if relevant_count == 0:
            # 所有证据都是中性的
            verdict = "证据不足，无法判断"
            confidence = 30.0
        else:
            support_ratio = supporting_count / relevant_count

            # 根据支持率确定结论
            if support_ratio >= 0.7:  # 70%以上相关证据支持
                verdict = "属实"
            elif support_ratio <= 0.3:  # 70%以上相关证据反对
                verdict = "不实"
            else:  # 支持和反对证据比较接近
                verdict = "部分属实，存在争议"

            # 置信度计算
            # 基础置信度：基于证据数量
            base_confidence = min(80, total_count * 15)  # 每条证据+15%，最高80分

            # 质量加权：平均信源质量分数
            avg_score = sum(e.overall_score for e in evidences) / total_count
            quality_bonus = (avg_score - 50) * 0.8  # 平均分超过50的部分转换为置信度（提高权重以更重视证据质量）

            # 一致性加权：立场越一致，置信度越高
            if support_ratio >= 0.8 or support_ratio <= 0.2:
                consistency_bonus = 15  # 高度一致
            elif support_ratio >= 0.7 or support_ratio <= 0.3:
                consistency_bonus = 10  # 较为一致
            else:
                consistency_bonus = 0   # 存在争议

            # Tier 1来源加成
            tier1_bonus = 10 if any(e.tier == "Tier 1" for e in evidences) else 0

            confidence = base_confidence + quality_bonus + consistency_bonus + tier1_bonus
            confidence = min(100, max(0, confidence))  # 限制在0-100范围

        logger.info(f"结论: {verdict}, 置信度: {confidence:.1f}%")

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

    async def _generate_ai_summary(
        self,
        claim: str,
        evidences: List[EvidenceChainItem],
        verdict: str
    ) -> str:
        """
        使用GLM-5生成AI归纳总结（与普通搜索引擎的核心区别）

        Args:
            claim: 待核查的说法
            evidences: 证据项列表
            verdict: 核查结论

        Returns:
            str: AI归纳总结文本
        """
        if not self.glm_client:
            logger.warning("GLM客户端未初始化，跳过AI归纳总结")
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
- 开头先用1-2句话概括核心结论（作为简短摘要）
- 然后详细展开分析
- 语言简洁专业，避免重复
- 突出AI的归纳分析能力，而非简单罗列证据
- 使用项目符号（•）列出要点

请直接开始输出归纳总结："""

            logger.info("开始调用GLM-5生成AI归纳总结...")

            # 调用GLM-5
            response = self.glm_client.chat.completions.create(
                model="glm-5",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=2000  # 增加到2000以避免内容被截断
            )

            # 🔍 详细调试日志：检查完整响应结构
            logger.info(f"📦 GLM-5响应类型: {type(response)}")
            logger.info(f"📦 GLM-5响应对象: {response}")

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

            # 返回字典结构（包含完整总结和简短摘要）
            result = {
                "full": full_summary,
                "brief": brief_summary
            }

            logger.info(f"AI归纳总结生成完成，完整长度: {len(full_summary)} 字符，简短长度: {len(brief_summary)} 字符")

            return result

        except Exception as e:
            logger.error(f"AI归纳总结生成失败: {e}")
            return None

    def _extract_brief_summary(self, full_summary: str) -> str:
        """
        从完整归纳总结中提取简短摘要（1-2句话）

        Args:
            full_summary: 完整的AI归纳总结

        Returns:
            str: 简短摘要（最多150字符）
        """
        if not full_summary:
            return "暂无摘要"

        # 尝试按段落分割，取第一段
        paragraphs = full_summary.split('\n\n')
        first_paragraph = paragraphs[0].strip()

        # 🔧 移除常见的标题标记，提取真正的摘要内容
        # 标题格式可能是：**标题**\n内容 或 **标题**：内容
        title_patterns = [
            r'^\*\*核心事实提取\*\*[：:\s]*(?:\n\s*)?',  # **核心事实提取**
            r'^\*\*核心结论摘要\*\*[：:\s]*(?:\n\s*)?',  # **核心结论摘要**
            r'^\*\*摘要\*\*[：:\s]*(?:\n\s*)?',         # **摘要**
            r'^核心结论[：:\s]*(?:\n\s*)?',               # 核心结论
            r'^摘要[：:\s]*(?:\n\s*)?',                  # 摘要
            r'^###\s*\*\*摘要\*\*\s*',                   # ### **摘要**
            r'^•\s*\*\*.*?\*\*',                         # 以 • ** 开头的列表项标题
        ]

        for pattern in title_patterns:
            first_paragraph = re.sub(pattern, '', first_paragraph, flags=re.IGNORECASE | re.MULTILINE).strip()

        # 🔧 如果第一段移除标题后为空或太短，尝试使用第二段
        if len(first_paragraph) < 10 and len(paragraphs) > 1:
            second_paragraph = paragraphs[1].strip()
            # 清理第二段中的Markdown符号
            second_paragraph = re.sub(r'^[•\-\*]+\s*\*\*', '', second_paragraph).strip()
            second_paragraph = re.sub(r'\*\*', '', second_paragraph).strip()
            if len(second_paragraph) > 10:
                first_paragraph = second_paragraph

        # 🧹 清理Markdown格式符号（避免前端显示原始标记）
        first_paragraph = first_paragraph.replace('**', '').replace('*', '')  # 移除粗体/斜体
        first_paragraph = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', first_paragraph)  # 移除链接，保留文本
        first_paragraph = first_paragraph.replace('`', '')  # 移除代码符号
        first_paragraph = first_paragraph.strip()

        # 如果第一段超过150字符，截取到第一个句号
        if len(first_paragraph) > 150:
            # 寻找第一个句号、问号或感叹号
            for i, char in enumerate(first_paragraph):
                if char in '。！？.!?':
                    return first_paragraph[:i+1]
            # 如果没有标点，直接截取前150字符
            return first_paragraph[:147] + "..."

        return first_paragraph if first_paragraph else "暂无摘要"

    def _extract_stances_from_reasoning(
        self,
        reasoning_text: str,
        evidences: List[RankedEvidence]
    ) -> Dict[str, str]:
        """
        从GLM-5推理文本中提取证据立场信息

        Args:
            reasoning_text: GLM-5生成的推理文本
            evidences: 证据列表

        Returns:
            Dict[str, str]: URL到立场的映射 {"support", "oppose", "neutral"}
        """
        import re

        logger.info("开始从推理文本中提取证据立场...")

        # 匹配固定格式（修改prompt后GLM-5应该使用此格式）：
        # *   **证据 [1] [标题](URL)**
        #     *   **立场**：**支持**（请选择：支持/反对/中性，三者选一）
        #     *   **分析**：...

        pattern = re.compile(
            r'\*\*证据\s*\[\d+\]\s*\[([^\]]+)\]\(([^)]+)\).*?\*\*立场\*\*[:：]\s*\*\*(支持|反对|中性)\*\*',
            re.DOTALL
        )

        stance_map = {}
        matched_urls = set()

        for match in pattern.finditer(reasoning_text):
            title = match.group(1).strip()
            url = match.group(2).strip()
            stance_cn = match.group(3).strip()

            # 映射到英文
            stance_en = {
                "支持": "support",
                "反对": "oppose",
                "中性": "neutral"
            }.get(stance_cn, "neutral")

            stance_map[url] = stance_en
            matched_urls.add(url)
            logger.info(f"✓ 提取立场: {title[:50]}... -> {stance_cn} -> {stance_en}")

        # 回退策略：对于未匹配的证据，尝试通过URL在推理文本中查找立场关键词
        for e in evidences:
            if e.url not in stance_map:
                # 在推理文本中查找该URL附近的立场关键词
                url_pos = reasoning_text.find(e.url)
                if url_pos != -1:
                    # 提取URL前后300个字符的上下文
                    context_start = max(0, url_pos - 300)
                    context_end = min(len(reasoning_text), url_pos + 300)
                    context = reasoning_text[context_start:context_end]

                    # 检查立场关键词（优先支持，然后反对，最后中性）
                    if "**支持**" in context or "**立场**：**支持**" in context:
                        stance_map[e.url] = "support"
                        logger.info(f"✓ 通过上下文提取立场: {e.title[:50]}... -> 支持")
                    elif "**反对**" in context or "**立场**：**反对**" in context:
                        stance_map[e.url] = "oppose"
                        logger.info(f"✓ 通过上下文提取立场: {e.title[:50]}... -> 反对")
                    elif "**中性**" in context or "**立场**：**中性**" in context:
                        stance_map[e.url] = "neutral"
                        logger.info(f"✓ 通过上下文提取立场: {e.title[:50]}... -> 中性")
                    else:
                        # 真的无法提取，使用默认值
                        logger.debug(f"⚠️ 无法从上下文提取立场: {e.url}")

        logger.info(f"从推理文本中共提取到 {len(stance_map)} 个证据的立场信息")

        # 统计有多少证据没有被提取到立场
        no_stance_count = sum(1 for e in evidences if e.url not in stance_map)
        if no_stance_count > 0:
            logger.warning(f"⚠️ 有 {no_stance_count} 个证据未能从推理文本中提取立场，将默认为中性")
            # 输出未匹配证据的URL，方便调试
            for e in evidences:
                if e.url not in stance_map:
                    logger.debug(f"未匹配证据URL: {e.url}")

        return stance_map

