"""
Fact-check route handlers: standard and streaming.
"""
import time
import json
import asyncio
import logging
import re
from typing import List

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import config, logger
from models import FactCheckRequest, FactCheckResponse, SearchResult
from services.search import SearchServiceError, _filter_irrelevant_results, _is_time_sensitive_claim, search_with_zhipu
from services.llm_service import build_llm_prompt, call_llm_api

router = APIRouter()

CORE_EVIDENCE_LIMIT = 10

_llm_client = None
_link_validator = None
_consistency_scorer = None
_evidence_chain_generator = None


def init_dependencies(llm_client, link_validator, consistency_scorer, evidence_chain_generator):
    global _llm_client, _link_validator, _consistency_scorer, _evidence_chain_generator
    _llm_client = llm_client
    _link_validator = link_validator
    _consistency_scorer = consistency_scorer
    _evidence_chain_generator = evidence_chain_generator


def _normalize_core_evidence_count_text(text: str, core_count: int) -> str:
    """Align model-written evidence-count phrases with the actual core evidence count."""
    if not text or core_count <= 0:
        return text

    def replace_count(match: re.Match) -> str:
        prefix = match.group("prefix") or ""
        unit = match.group("unit")
        qualifier = match.group("qualifier") or "核心"
        return f"{prefix}{core_count}{unit}{qualifier}证据"

    normalized = re.sub(
        r"(?<!第)(?P<prefix>所有|全部|上述|以上|这)?\s*\d+\s*(?P<unit>条|个)\s*(?P<qualifier>核心)?证据",
        replace_count,
        text,
    )

    return re.sub(
        r"(?P<prefix>所有|全部|上述|以上|这些|上述这些)\s*证据",
        lambda match: f"{match.group('prefix')}{core_count}条核心证据",
        normalized,
    )


def _select_core_evidence(claim: str, search_results: List[SearchResult]) -> List[SearchResult]:
    """Re-apply evidence quality gates before anything is shown to the model or UI."""
    filtered = _filter_irrelevant_results(claim, search_results)
    if len(filtered) < len(search_results):
        logger.info(f"核心证据复筛：{len(search_results)} → {len(filtered)}")
    if not filtered and not _is_time_sensitive_claim(claim):
        logger.info("核心证据复筛无结果，非时效敏感claim回退到原始Top N")
        return search_results[:CORE_EVIDENCE_LIMIT]
    return filtered[:CORE_EVIDENCE_LIMIT]


@router.post("/api/v1/check/stream")
async def fact_check_stream(request: FactCheckRequest):
    """流式核查接口（返回Server-Sent Events）"""
    from fastapi.responses import StreamingResponse

    logger.info(f"开始流式核查: {request.claim}")

    async def generate():
        try:
            # 步骤1: 搜索证据
            yield f"event: progress\ndata: {{\"stage\": \"searching\", \"message\": \"正在联网搜索证据...\"}}\n\n"
            search_results = await search_with_zhipu(request.claim)

            if not search_results:
                yield f"event: error\ndata: {{\"message\": \"未找到相关搜索结果\"}}\n\n"
                return

            yield f"event: progress\ndata: {{\"stage\": \"found\", \"message\": \"检索到 {len(search_results)} 个相关结果，正在筛选核心证据并分析...\"}}\n\n"

            # 步骤2: 复筛核心证据并构造Prompt
            reasoning_results = _select_core_evidence(request.claim, search_results)
            if not reasoning_results:
                yield f"event: error\ndata: {{\"message\": \"未找到可用于核查的高相关近期证据\"}}\n\n"
                return
            prompt = build_llm_prompt(request.claim, reasoning_results)

            # 步骤3: 流式调用LLM
            request_params = {
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 6000,
                "stream": True,
            }

            if request.enable_thinking:
                logger.info("深度思考模式已启用")
                yield f"event: progress\ndata: {{\"stage\": \"thinking_start\", \"message\": \"AI开始深度思考...\", \"estimated_time\": 150}}\n\n"

            response = _llm_client.chat.completions.create(**request_params)

            full_content = ""
            thinking_content = ""

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta

                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        thinking_content += delta.reasoning_content
                        yield f"event: thinking\ndata: {{\"content\": {json.dumps(delta.reasoning_content)}, \"finished\": false}}\n\n"

                    if hasattr(delta, 'content') and delta.content:
                        full_content += delta.content
                        yield f"event: content\ndata: {{\"content\": {json.dumps(delta.content)}, \"finished\": false}}\n\n"

            if not full_content and thinking_content:
                logger.info("深度思考模式下content为空，使用reasoning_content作为推理内容")
                full_content = thinking_content

            full_content = _normalize_core_evidence_count_text(full_content, len(reasoning_results))

            yield f"event: progress\ndata: {{\"stage\": \"processing\", \"message\": \"正在生成证据链...\"}}\n\n"

            # 步骤4: 生成证据链
            if request.enable_evidence_chain:
                search_results_dicts = [
                    {
                        "title": result.name,
                        "url": result.url,
                        "summary": result.summary,
                        "date_published": result.date_published
                    }
                    for result in reasoning_results
                ]

                evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                    claim=request.claim,
                    search_results=search_results_dicts,
                    enable_link_validation=False,
                    top_k=CORE_EVIDENCE_LIMIT,
                    reasoning_text=full_content,
                    total_search_results=len(search_results)
                )

                result_data = {
                    "verdict": evidence_chain.verdict,
                    "confidence": evidence_chain.confidence,
                    "reasoning": full_content,
                    "thinking_process": thinking_content,
                    "evidence_chain": {
                        "supporting_evidence": evidence_chain.supporting_evidence,
                        "opposing_evidence": evidence_chain.opposing_evidence,
                        "neutral_evidence": evidence_chain.neutral_evidence,
                        "total_evidence": evidence_chain.total_evidence,
                        "total_search_results": evidence_chain.total_search_results,
                        "reasoning_summary": evidence_chain.reasoning_summary,
                        "ai_summary": evidence_chain.ai_summary
                    }
                }

                yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            else:
                result_data = {
                    "verdict": "信息不足，无法判断",
                    "reasoning": full_content
                }
                yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"

        except SearchServiceError as e:
            logger.error(f"搜索服务不可用: {e}")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"流式核查失败: {e}", exc_info=True)
            yield f"event: error\ndata: {{\"message\": \"{str(e)}\"}}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/api/v1/check", response_model=FactCheckResponse)
async def fact_check(request: FactCheckRequest):
    """信息核查主接口（支持深度思考模式 + 三层缓存）"""
    start_time = time.time()

    try:
        logger.info(f"开始核查: {request.claim}")
        logger.info(f"配置 - 思考模式: {request.enable_thinking}, 链接验证: {request.enable_link_validation}, 一致性检查: {request.enable_consistency_check}")

        # 步骤1: 联网搜索
        search_results = await search_with_zhipu(request.claim)

        # 步骤2: 没有结果则返回信息不足
        if not search_results:
            logger.warning("未找到有效搜索结果")
            return FactCheckResponse(
                verdict="信息不足，无法判断",
                evidence_quote="无",
                source_url="",
                search_keywords=request.claim,
                uncertainty_note="未找到权威信息源",
                reasoning="搜索未返回相关结果，无法进行信息核查",
                thinking_process=None,
                link_validation=None,
                consistency_score=None
            )

        # 步骤3: 复筛核心证据，后续Prompt和证据链只使用这批证据
        reasoning_results = _select_core_evidence(request.claim, search_results)
        if not reasoning_results:
            logger.warning("未找到可用于核查的高相关近期证据")
            return FactCheckResponse(
                verdict="信息不足，无法判断",
                evidence_quote="无",
                source_url="",
                search_keywords=request.claim,
                uncertainty_note="搜索结果未通过核心证据筛选",
                reasoning="搜索结果缺少高相关、近期且覆盖核心要素的证据，无法进行可靠核查",
                thinking_process=None,
                link_validation=None,
                consistency_score=None
            )

        # 步骤4: 链接活性检测（可选）
        link_validation_result = None
        if request.enable_link_validation:
            logger.info("开始链接活性检测...")
            urls = [result.url for result in reasoning_results[:5]]
            validation_results = await _link_validator.validate_multiple_links(urls, concurrent_limit=3)
            validation_report = _link_validator.generate_validation_report(validation_results)
            link_validation_result = {
                "report": validation_report,
                "details": [
                    {
                        "url": r.url,
                        "accessible": r.is_accessible,
                        "status_code": r.status_code,
                        "response_time_ms": r.response_time_ms,
                        "error": r.error_message
                    }
                    for r in validation_results
                ]
            }
            logger.info(f"链接验证完成: {validation_report['accessible_links']}/{validation_report['total_links']} 个链接可访问")

        # 步骤5: 构造推理Prompt
        prompt = build_llm_prompt(request.claim, reasoning_results)

        # 步骤6: 调用LLM进行推理
        reasoning_result = await call_llm_api(
            prompt,
            _llm_client,
            enable_thinking=request.enable_thinking,
            stream=request.stream
        )
        reasoning_result["reasoning"] = _normalize_core_evidence_count_text(
            reasoning_result.get("reasoning", ""),
            len(reasoning_results)
        )

        # 步骤7&8: 并行执行（一致性评分 + 证据链生成）
        consistency_result = None
        evidence_chain_result = None
        confidence_value = None

        async def compute_consistency():
            if request.enable_consistency_check and reasoning_result.get("reasoning"):
                logger.info("开始一致性评分...")
                source_content = " ".join([result.summary for result in reasoning_results[:3]])
                consistency_score = _consistency_scorer.calculate_consistency(
                    reasoning_result["reasoning"],
                    source_content
                )
                consistency_report = _consistency_scorer.generate_consistency_report(consistency_score)
                logger.info(f"一致性评分完成: {consistency_score.overall_score}/100")
                return consistency_report
            return None

        async def compute_evidence_chain():
            if request.enable_evidence_chain:
                logger.info("开始生成证据链...")
                search_results_dicts = [
                    {
                        "title": result.name,
                        "url": result.url,
                        "summary": result.summary,
                        "date_published": result.date_published
                    }
                    for result in reasoning_results
                ]
                reasoning_text = reasoning_result.get("reasoning", "")
                evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                    claim=request.claim,
                    search_results=search_results_dicts,
                    enable_link_validation=False,
                    top_k=CORE_EVIDENCE_LIMIT,
                    reasoning_text=reasoning_text,
                    total_search_results=len(search_results)
                )
                logger.info(f"证据链生成完成: {evidence_chain.total_evidence} 个证据, 置信度: {evidence_chain.confidence}%")
                return evidence_chain
            return None

        if request.enable_consistency_check or request.enable_evidence_chain:
            results = await asyncio.gather(
                compute_consistency(),
                compute_evidence_chain(),
                return_exceptions=True
            )

            consistency_result = results[0]
            evidence_chain = results[1]

            if evidence_chain and not isinstance(evidence_chain, Exception):
                evidence_chain_result = {
                    "supporting_evidence": evidence_chain.supporting_evidence,
                    "opposing_evidence": evidence_chain.opposing_evidence,
                    "neutral_evidence": evidence_chain.neutral_evidence,
                    "key_findings": evidence_chain.key_findings,
                    "total_evidence": evidence_chain.total_evidence,
                    "total_search_results": evidence_chain.total_search_results,
                    "authoritative_sources": evidence_chain.authoritative_sources,
                    "average_score": evidence_chain.average_score,
                    "reasoning_summary": evidence_chain.reasoning_summary,
                    "ai_summary": evidence_chain.ai_summary
                }
                confidence_value = evidence_chain.confidence

        # 步骤8: 返回结果
        elapsed_time = (time.time() - start_time) * 1000
        logger.info(f"核查完成，耗时: {elapsed_time:.1f}ms")

        if request.enable_evidence_chain and evidence_chain:
            final_verdict = evidence_chain.verdict
            final_confidence = evidence_chain.confidence
            logger.info(f"使用证据链结论: {final_verdict}, 置信度: {final_confidence}%")
        else:
            final_verdict = reasoning_result.get("verdict", "信息不足，无法判断")
            final_confidence = confidence_value

        response_data = FactCheckResponse(
            verdict=final_verdict,
            evidence_quote=reasoning_result.get("evidence_quote", "无"),
            source_url=reasoning_result.get("source_url", ""),
            search_keywords=reasoning_result.get("search_keywords", request.claim),
            uncertainty_note=reasoning_result.get("uncertainty_note", "无"),
            reasoning=reasoning_result.get("reasoning", "推理过程未提供"),
            confidence=final_confidence,
            thinking_process=reasoning_result.get("thinking_process"),
            link_validation=link_validation_result,
            consistency_score=consistency_result,
            evidence_chain=evidence_chain_result
        )

        return response_data

    except SearchServiceError as e:
        logger.error(f"搜索服务不可用: {e}")
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        logger.error(f"信息核查异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="信息核查服务异常")
