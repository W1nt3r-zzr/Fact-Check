"""
Fact-check route handlers: standard and streaming.
"""
import time
import json
import asyncio
import inspect
import logging
import re
from typing import Any, AsyncIterator, List
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import config, logger
from models import FactCheckRequest, FactCheckResponse, SearchResult
from services.search import SearchServiceError, _filter_irrelevant_results, _is_time_sensitive_claim, search_evidence
from services.llm_service import build_llm_prompt, call_llm_api, sanitize_model_preamble
from services.task_queue import FactCheckTaskQueue

router = APIRouter()

# Keep the reasoning context bounded. Search can return many syndicated or
# lightly rewritten reports; only representative sources should enter the LLM
# prompt and evidence chain.
CORE_EVIDENCE_LIMIT = 18
HOMOGENEOUS_EVIDENCE_PER_CLUSTER = 3

_llm_client = None
_link_validator = None
_consistency_scorer = None
_evidence_chain_generator = None
_task_queue = FactCheckTaskQueue(config.MAX_CONCURRENT_CHECKS)


async def _resolve_maybe_awaitable(value: Any) -> Any:
    """Support both async SDK clients and sync clients with OpenAI-compatible APIs."""
    if inspect.isawaitable(value):
        return await value
    return value


async def _iterate_llm_stream(stream: Any) -> AsyncIterator[Any]:
    """Yield chunks from either an AsyncStream or a regular Stream."""
    if hasattr(stream, "__aiter__"):
        async for chunk in stream:
            yield chunk
        return

    for chunk in stream:
        yield chunk


def _normalize_title_for_source_dedup(title: str) -> str:
    """Normalize news titles so same article in different columns dedups before prompting."""
    if not title:
        return ""
    text = title.replace('　', ' ').replace(' ', ' ').strip()
    text = text.replace('，', ',').replace('。', '.').replace('！', '!').replace('？', '?')
    text = text.replace('：', ':').replace('；', ';').replace('“', '"').replace('”', '"')
    text = text.replace('（', '(').replace('）', ')').replace('【', '[').replace('】', ']')
    text = text.replace('、', ',').replace('—', '-').replace('–', '-')
    suffix_pattern = re.compile(
        r'\s*[-_|]\s*(?:'
        r'要闻|社会新闻|社会|新闻|资讯|原创|独家|综合|图片|视频|国内|国际|财经|科技|滚动|热点|专题|频道|客户端|'
        r'[一-龥a-zA-Z0-9]{2,20}(?:网新闻|新闻网|新闻|网|频道|资讯|要闻)'
        r')\s*$',
        flags=re.IGNORECASE
    )
    while True:
        stripped = suffix_pattern.sub('', text).strip()
        if stripped == text:
            break
        text = stripped
    return re.sub(r'\s+', ' ', text).lower().strip()


def _result_domain(result: SearchResult) -> str:
    if result.url:
        try:
            return _normalize_core_host(urlparse(result.url).netloc)
        except Exception:
            pass
    return _normalize_core_host((result.source or "").strip())


def _normalize_core_host(host: str) -> str:
    normalized = (host or "").lower()
    for prefix in ("www.", "m.", "wap."):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized


def _deduplicate_core_results(results: List[SearchResult]) -> List[SearchResult]:
    """Dedup before LLM/evidence chain so reposts do not become separate core evidence."""
    seen_urls = set()
    seen_domain_titles = set()
    seen_titles = set()
    seen_domain_summaries = set()
    deduped = []

    for result in results:
        normalized_url = ""
        if result.url:
            parsed = urlparse(result.url)
            normalized_url = ("https://" + _normalize_core_host(parsed.netloc) + parsed.path).rstrip("/").lower()
        if normalized_url and normalized_url in seen_urls:
            continue

        domain = _result_domain(result)
        title_norm = _normalize_title_for_source_dedup(result.name)
        summary_norm = re.sub(r'\s+', '', result.summary or "")[:240]

        domain_title_key = (domain, title_norm)
        if title_norm and domain_title_key in seen_domain_titles:
            logger.info(f"核心证据去重：跳过同源栏目转载「{result.name[:60]}...」")
            continue
        if title_norm and title_norm in seen_titles:
            logger.info(f"核心证据去重：跳过跨站同题转载「{result.name[:60]}...」")
            continue

        domain_summary_key = (domain, summary_norm)
        if summary_norm and len(summary_norm) >= 80 and domain_summary_key in seen_domain_summaries:
            logger.info(f"核心证据去重：跳过同源摘要重复「{result.name[:60]}...」")
            continue

        if normalized_url:
            seen_urls.add(normalized_url)
        if title_norm:
            seen_domain_titles.add(domain_title_key)
            seen_titles.add(title_norm)
        if summary_norm and len(summary_norm) >= 80:
            seen_domain_summaries.add(domain_summary_key)
        deduped.append(result)

    if len(deduped) < len(results):
        logger.info(f"核心证据同源去重：{len(results)} → {len(deduped)}")
    return deduped


def _compact_for_similarity(text: str) -> str:
    compact = (text or "").lower()
    compact = re.sub(r"https?://\S+", "", compact)
    compact = re.sub(r"第\s*\d+\s*条", "", compact)
    compact = re.sub(r"\d{4}[-年/]\d{1,2}[-月/]\d{0,2}日?", "", compact)
    compact = re.sub(r"[^\w一-龥]+", "", compact)
    return compact


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    compact = _compact_for_similarity(text)
    if len(compact) <= n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _is_homogeneous_evidence(left: SearchResult, right: SearchResult) -> bool:
    """Detect same-fact reposts/rewrites that should not all consume LLM tokens."""
    left_compact = _compact_for_similarity(f"{left.name} {left.summary}")
    right_compact = _compact_for_similarity(f"{right.name} {right.summary}")
    if min(len(left_compact), len(right_compact)) < 36:
        return False

    left_title = _normalize_title_for_source_dedup(left.name)
    right_title = _normalize_title_for_source_dedup(right.name)
    if left_title and right_title:
        title_sets = (_char_ngrams(left_title, 2), _char_ngrams(right_title, 2))
        if _jaccard_similarity(*title_sets) >= 0.72:
            return True

    left_text = f"{left.name} {left.summary}"
    right_text = f"{right.name} {right.summary}"
    left_ngrams = _char_ngrams(left_text, 3)
    right_ngrams = _char_ngrams(right_text, 3)
    return _jaccard_similarity(left_ngrams, right_ngrams) >= 0.58


def _compress_homogeneous_core_results(
    ranked_results: List[SearchResult],
    max_per_cluster: int = HOMOGENEOUS_EVIDENCE_PER_CLUSTER,
) -> List[SearchResult]:
    """Keep only a few ranked representatives from each same-fact evidence cluster."""
    clusters: list[list[SearchResult]] = []
    selected: list[SearchResult] = []

    for result in ranked_results:
        matched_cluster = None
        for cluster in clusters:
            if any(_is_homogeneous_evidence(result, existing) for existing in cluster):
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append([result])
            selected.append(result)
            continue

        matched_cluster.append(result)
        if len(matched_cluster) <= max_per_cluster:
            selected.append(result)
        else:
            logger.info(f"核心证据同质压缩：跳过同事实重复报道「{result.name[:60]}...」")

    if len(selected) < len(ranked_results):
        logger.info(f"核心证据同质压缩：{len(ranked_results)} → {len(selected)}")
    return selected


def _core_evidence_quality_score(claim: str, result: SearchResult) -> float:
    text = f"{result.name} {result.summary} {result.source} {result.url}"
    score = 0.0

    authority_terms = [
        "中国驻", "总领馆", "领事馆", "使馆", "央视", "cctv", "新华", "新华社",
        "人民日报", "新京报", "澎湃", "界面新闻",
    ]
    if any(term.lower() in text.lower() for term in authority_terms):
        score += 3.0

    if re.search(r'\.gov\.cn|china-consulate|mfa\.gov\.cn|news\.cctv\.com|xinhuanet\.com', result.url or "", re.I):
        score += 3.0

    core_terms = [term for term in re.findall(r'[一-龥A-Za-z0-9]{2,10}', claim) if len(term) >= 2]
    if core_terms:
        hit_count = sum(1 for term in set(core_terms) if term in text)
        score += hit_count / len(set(core_terms))

    if result.date_published:
        score += 0.5

    uncertainty_terms = ["疑", "网传", "网友称", "传言", "据网传", "听说", "惨烈", "割喉"]
    if any(term in text for term in uncertainty_terms):
        score -= 2.5

    return score


def _rank_core_results(claim: str, results: List[SearchResult]) -> List[SearchResult]:
    indexed = list(enumerate(results))
    indexed.sort(
        key=lambda item: (_core_evidence_quality_score(claim, item[1]), -item[0]),
        reverse=True,
    )
    return [result for _, result in indexed]


def _drop_speculative_core_results(results: List[SearchResult]) -> List[SearchResult]:
    """Remove rumor/speculation-heavy items from the core set when better evidence exists."""
    speculative_pattern = re.compile(r"疑|网传|网友称|传言|据网传|听说|割喉|惨烈")
    filtered = [
        result for result in results
        if not speculative_pattern.search(f"{result.name} {result.summary}")
    ]
    if filtered and len(filtered) < len(results):
        logger.info(f"核心证据剔除强猜测结果：{len(results)} → {len(filtered)}")
        return filtered
    return results


def init_dependencies(llm_client, link_validator, consistency_scorer, evidence_chain_generator):
    global _llm_client, _link_validator, _consistency_scorer, _evidence_chain_generator
    _llm_client = llm_client
    _link_validator = link_validator
    _consistency_scorer = consistency_scorer
    _evidence_chain_generator = evidence_chain_generator


@router.get("/api/v1/queue-status")
async def queue_status():
    snapshot = await _task_queue.snapshot()
    return snapshot.to_dict()


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
        deduped = _drop_speculative_core_results(_deduplicate_core_results(search_results))
        ranked = _rank_core_results(claim, deduped)
        return _compress_homogeneous_core_results(ranked)[:CORE_EVIDENCE_LIMIT]
    deduped = _drop_speculative_core_results(_deduplicate_core_results(filtered))
    ranked = _rank_core_results(claim, deduped)
    return _compress_homogeneous_core_results(ranked)[:CORE_EVIDENCE_LIMIT]


@router.post("/api/v1/check/stream")
async def fact_check_stream(request: FactCheckRequest):
    """流式核查接口（返回Server-Sent Events）"""
    from fastapi.responses import StreamingResponse

    logger.info(f"开始流式核查: {request.claim}")
    task_id = _task_queue.create_task_id()

    async def generate():
        acquired_queue_slot = False

        async def progress_event(stage: str, message: str, **extra):
            snapshot = await _task_queue.snapshot(task_id, state="running")
            payload = {
                "stage": stage,
                "message": message,
                "queue": snapshot.to_dict(),
                **extra,
            }
            return f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            async for queue_snapshot in _task_queue.acquire(task_id):
                queue_data = queue_snapshot.to_dict()
                if queue_snapshot.state == "queued":
                    message = (
                        f"当前有 {queue_snapshot.running} 个核查任务正在运行，"
                        f"{queue_snapshot.queued} 个任务排队；你前面还有 {queue_snapshot.queued_ahead} 个任务。"
                    )
                    payload = {
                        "stage": "queued",
                        "message": message,
                        "queue": queue_data,
                    }
                    yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                else:
                    acquired_queue_slot = True
                    payload = {
                        "stage": "queue_started",
                        "message": (
                            f"已进入核查流程。当前同时运行 {queue_snapshot.running}/"
                            f"{queue_snapshot.max_concurrent} 个任务。"
                        ),
                        "queue": queue_data,
                    }
                    yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break

            # 步骤1: 搜索证据
            yield await progress_event("searching", "正在联网搜索证据...")
            search_results = await search_evidence(request.claim)

            if not search_results:
                yield f"event: error\ndata: {{\"message\": \"未找到相关搜索结果\"}}\n\n"
                return

            yield await progress_event("found", f"检索到 {len(search_results)} 个相关结果，正在筛选核心证据并分析...")

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
                yield await progress_event("thinking_start", "AI开始深度思考...", estimated_time=150)

            response = await _resolve_maybe_awaitable(
                _llm_client.chat.completions.create(**request_params)
            )

            full_content = ""
            thinking_content = ""

            async for chunk in _iterate_llm_stream(response):
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

            full_content = sanitize_model_preamble(
                _normalize_core_evidence_count_text(full_content, len(reasoning_results))
            )

            yield await progress_event("processing", "正在生成证据链...")

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
                    enable_link_validation=request.enable_link_validation,
                    top_k=len(reasoning_results),
                    reasoning_text=full_content,
                    total_search_results=len(search_results)
                )

                result_data = {
                    "verdict": evidence_chain.verdict,
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
        finally:
            if acquired_queue_slot:
                await _task_queue.release(task_id)

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
    task_id = _task_queue.create_task_id()
    acquired_queue_slot = False

    try:
        await _task_queue.wait_until_acquired(task_id)
        acquired_queue_slot = True

        logger.info(f"开始核查: {request.claim}")
        logger.info(f"配置 - 思考模式: {request.enable_thinking}, 链接验证: {request.enable_link_validation}, 一致性检查: {request.enable_consistency_check}")

        # 步骤1: 联网搜索
        search_results = await search_evidence(request.claim)

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
            stream=False
        )
        reasoning_result["reasoning"] = sanitize_model_preamble(
            _normalize_core_evidence_count_text(
                reasoning_result.get("reasoning", ""),
                len(reasoning_results)
            )
        )

        # 步骤7&8: 并行执行（一致性评分 + 证据链生成）
        consistency_result = None
        evidence_chain_result = None

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
                    enable_link_validation=request.enable_link_validation,
                    top_k=len(reasoning_results),
                    reasoning_text=reasoning_text,
                    total_search_results=len(search_results)
                )
                logger.info(f"证据链生成完成: {evidence_chain.total_evidence} 个证据")
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

        # 步骤8: 返回结果
        elapsed_time = (time.time() - start_time) * 1000
        logger.info(f"核查完成，耗时: {elapsed_time:.1f}ms")

        if request.enable_evidence_chain and evidence_chain:
            final_verdict = evidence_chain.verdict
            logger.info(f"使用证据链结论: {final_verdict}")
        else:
            final_verdict = reasoning_result.get("verdict", "信息不足，无法判断")

        response_data = FactCheckResponse(
            verdict=final_verdict,
            evidence_quote=reasoning_result.get("evidence_quote", "无"),
            source_url=reasoning_result.get("source_url", ""),
            search_keywords=reasoning_result.get("search_keywords", request.claim),
            uncertainty_note=reasoning_result.get("uncertainty_note", "无"),
            reasoning=reasoning_result.get("reasoning", "推理过程未提供"),
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
    finally:
        if acquired_queue_slot:
            await _task_queue.release(task_id)
