"""
Fact-check route handlers: standard and streaming.
"""
import time
import json
import asyncio
import hashlib
import inspect
import logging
import os
import re
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import config, logger
from models import FactCheckRequest, FactCheckResponse, SearchResult
from services.search import SearchServiceError, _filter_irrelevant_results, _is_time_sensitive_claim, search_evidence
from services.llm_service import (
    build_assistant_llm_prompt,
    build_llm_prompt,
    call_llm_api,
    sanitize_model_preamble,
)
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


# ==================== 预计算缓存工具 ====================

def _get_cache_dir() -> Path:
    """获取预计算缓存目录，不存在则自动创建。"""
    cache_dir = Path(config.PRECOMPUTE_CACHE_DIR)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _load_cache(news_id: int) -> Optional[Dict]:
    """按 news_id 加载预计算结果缓存。"""
    cache_path = _get_cache_dir() / f"{news_id}.json"
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"加载缓存失败 news_id={news_id}: {e}")
        return None


def _save_cache(news_id: int, data: Dict) -> None:
    """保存预计算结果到缓存文件。"""
    cache_path = _get_cache_dir() / f"{news_id}.json"
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"缓存已保存 news_id={news_id} -> {cache_path}")
    except Exception as e:
        logger.error(f"保存缓存失败 news_id={news_id}: {e}")


def _build_claim_fingerprint(claim: str) -> str:
    """对 claim 文本做规范化指纹，用于匹配。"""
    normalized = re.sub(r"\s+", "", claim)
    normalized = re.sub(
        r"[，。！？、；：""''「」【】《》（）—…\-,.!?;:""''\[\]()\n]",
        "",
        normalized,
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _normalize_for_match(text: str) -> str:
    """对文本做规范化（去空白、去标点、去换行），用于子串匹配和相似度计算。"""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？、；：""''「」【】《》（）—…\-,.!?;:""''\[\]()\n]", "", text)
    return text.lower()


def _jaccard_trigrams(a: str, b: str) -> float:
    """计算两个字符串的 trigram Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    trigrams_a = {a[i:i+3] for i in range(len(a) - 2)}
    trigrams_b = {b[i:i+3] for i in range(len(b) - 2)}
    if not trigrams_a or not trigrams_b:
        return 0.0
    intersection = len(trigrams_a & trigrams_b)
    union = len(trigrams_a | trigrams_b)
    return intersection / union if union > 0 else 0.0


def _find_cache_by_claim(claim: str) -> Optional[Dict]:
    """多策略匹配预计算缓存。

    按优先级依次尝试：
    1. 完整 claim 指纹精确匹配
    2. 缓存中的 title 指纹匹配（用户只粘贴了标题）
    3. 缓存中的 body 指纹匹配（用户只粘贴了正文）
    4. 用户粘贴的文本包含缓存 title（标题+正文混贴）
    5. 缓存 title/body 包含用户粘贴的文本（只贴片段）
    6. trigram Jaccard 相似度 > 0.5
    """
    fingerprint = _build_claim_fingerprint(claim)
    normalized_claim = _normalize_for_match(claim)
    cache_dir = _get_cache_dir()

    all_caches = []
    for cache_file in sorted(cache_dir.glob("*.json")):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            all_caches.append(data)
        except Exception:
            continue

    if not all_caches:
        return None

    # 策略 1: 完整 claim 指纹精确匹配
    for data in all_caches:
        if data.get("claim_fingerprint") == fingerprint:
            logger.info(f"缓存命中 (精确指纹): news_id={data.get('news_id')}")
            return data

    # 策略 2: title 指纹匹配
    fingerprint_title = _build_claim_fingerprint(claim)
    for data in all_caches:
        if data.get("title_fingerprint") == fingerprint_title:
            logger.info(f"缓存命中 (标题指纹): news_id={data.get('news_id')}")
            return data

    # 策略 3: body 指纹匹配
    for data in all_caches:
        if data.get("body_fingerprint") == fingerprint:
            logger.info(f"缓存命中 (正文指纹): news_id={data.get('news_id')}")
            return data

    # 策略 4: 用户粘贴包含缓存 title 或正文
    for data in all_caches:
        cached_title = _normalize_for_match(data.get("title", ""))
        cached_body = _normalize_for_match(data.get("body", ""))
        if cached_title and cached_title in normalized_claim:
            logger.info(f"缓存命中 (包含标题): news_id={data.get('news_id')}")
            return data
        if cached_body and cached_body in normalized_claim:
            logger.info(f"缓存命中 (包含正文): news_id={data.get('news_id')}")
            return data

    # 策略 5: 缓存 title/body 包含用户粘贴文本
    for data in all_caches:
        cached_title = _normalize_for_match(data.get("title", ""))
        cached_body = _normalize_for_match(data.get("body", ""))
        if normalized_claim and (
            (cached_title and normalized_claim in cached_title) or
            (cached_body and normalized_claim in cached_body)
        ):
            logger.info(f"缓存命中 (被包含于缓存): news_id={data.get('news_id')}")
            return data

    # 策略 6: trigram Jaccard 相似度
    best_match = None
    best_score = 0.0
    for data in all_caches:
        for cached_key in ("title", "body", "claim"):
            cached_text = _normalize_for_match(data.get(cached_key, ""))
            if not cached_text:
                continue
            score = _jaccard_trigrams(normalized_claim, cached_text)
            if score > best_score:
                best_score = score
                best_match = data

    if best_score > 0.5:
        logger.info(f"缓存命中 (Jaccard={best_score:.2f}): news_id={best_match.get('news_id')}")
        return best_match

    logger.info(f"缓存未命中 (最佳 Jaccard={best_score:.2f})")
    return None


def _get_precomputed_cache_for_request(request: FactCheckRequest) -> Optional[Dict]:
    """Resolve precomputed playback cache, preferring explicit experiment news_id."""
    if request.news_id:
        cached = _load_cache(request.news_id)
        if cached:
            logger.info(f"预计算缓存命中 (news_id={request.news_id})")
            return cached
        logger.info(f"预计算缓存未命中 news_id={request.news_id}，降级到文本匹配")

    return _find_cache_by_claim(request.claim)


# ==================== 回放分块工具 ====================

def _chunk_text(text: str, target_chars: int = 150) -> List[str]:
    """按自然句边界切分文本，每块约 target_chars 字。

    在 target_chars 附近寻找句号、换行等自然断点。
    最少 10 块，最多 50 块，适配极短/极长内容。
    """
    if not text:
        return []
    if len(text) <= target_chars:
        return [text]

    chunks: List[str] = []
    pos = 0
    while pos < len(text):
        end = min(pos + target_chars, len(text))
        if end < len(text):
            # 从 target_chars 位置向后搜索自然断点
            for seek in range(end, max(pos + target_chars // 2, pos), -1):
                if text[seek - 1] in "\n。！？.!?":
                    end = seek
                    break
            else:
                # 回退：在空格/逗号处断
                for seek in range(end, max(pos + target_chars // 2, pos), -1):
                    if text[seek - 1] in " ，,；;":
                        end = seek
                        break
        chunks.append(text[pos:end])
        pos = end

    # 限制最少 10 块、最多 50 块
    if len(chunks) < 10 and len(text) > target_chars * 5:
        # 内容不足以自然分块达到 10 块，强制均分
        force_size = max(1, len(text) // 10)
        chunks = [text[i:i + force_size] for i in range(0, len(text), force_size)]
    if len(chunks) > 50:
        force_size = max(1, len(text) // 50)
        chunks = [text[i:i + force_size] for i in range(0, len(text), force_size)]

    return chunks


def _extract_domain(url: str) -> str:
    """从 URL 提取域名（去掉 www. 前缀）。"""
    try:
        parts = url.split("/")
        if len(parts) > 2:
            return parts[2].replace("www.", "")
    except Exception:
        pass
    return url


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


def _clean_assistant_reply(text: str) -> str:
    """Convert model output to plain assistant prose for the B-group UI."""
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"```([\s\S]*?)```", r"\1", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*\n]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+[.)、]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(
        r"^\s*【(?:开头摘要|核心事实提取|核心事实|深度洞察|与说法的精确对比|证据立场分析|证据关系分析|不确定性与局限|关键引用)】\s*",
        "",
        cleaned,
        flags=re.MULTILINE,
    )
    cleaned = re.sub(
        r"^\s*(?:开头摘要|核心事实提取|核心事实|深度洞察|与说法的精确对比|证据立场分析|证据关系分析|不确定性与局限|关键引用)\s*[:：]\s*",
        "",
        cleaned,
        flags=re.MULTILINE,
    )

    paragraphs = []
    seen = set()
    for paragraph in re.split(r"\n{2,}|\n(?=\S)", cleaned):
        normalized = re.sub(r"\s+", " ", paragraph).strip(" \t-:：")
        if not normalized:
            continue
        dedupe_key = re.sub(r"\s+", "", normalized)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        paragraphs.append(normalized)

    return "\n\n".join(paragraphs).strip()


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

            # === 缓存检测：命中预计算结果则启用 30 秒回放模式 ===
            cached = _get_precomputed_cache_for_request(request)
            if cached:
                logger.info(f"流式核查命中预计算缓存 (指纹匹配 news_id={cached.get('news_id')})，启用 30s 回放")
                # 释放队列槽位——回放不需要占用并发资源
                await _task_queue.release(task_id)
                acquired_queue_slot = False
                async for event_str in _generate_paced_playback(cached, request.claim):
                    yield event_str
                return

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
            prompt = (
                build_assistant_llm_prompt(request.claim, reasoning_results)
                if request.response_mode == "assistant"
                else build_llm_prompt(request.claim, reasoning_results)
            )

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
            assistant_reply = (
                _clean_assistant_reply(full_content)
                if request.response_mode == "assistant"
                else ""
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

                # 所有检索结果（含未入选核心证据的）用于展示完整来源
                all_search_results_dicts = [
                    {
                        "title": result.name,
                        "url": result.url,
                        "domain": result.source or (lambda u: (u.split('/')[2].replace('www.', '') if len(u.split('/')) > 2 else u))(result.url)
                    }
                    for result in search_results
                ]

                evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                    claim=request.claim,
                    search_results=search_results_dicts,
                    enable_link_validation=request.enable_link_validation,
                    top_k=len(reasoning_results),
                    reasoning_text=full_content,
                    total_search_results=len(search_results),
                    all_search_results=all_search_results_dicts
                )

                result_data = {
                    "verdict": evidence_chain.verdict,
                    "reasoning": full_content,
                    "assistant_reply": assistant_reply,
                    "thinking_process": thinking_content,
                    "evidence_chain": {
                        "supporting_evidence": evidence_chain.supporting_evidence,
                        "opposing_evidence": evidence_chain.opposing_evidence,
                        "neutral_evidence": evidence_chain.neutral_evidence,
                        "total_evidence": evidence_chain.total_evidence,
                        "total_search_results": evidence_chain.total_search_results,
                        "reasoning_summary": evidence_chain.reasoning_summary,
                        "ai_summary": evidence_chain.ai_summary,
                        "all_search_results": getattr(evidence_chain, "all_search_results", [])
                    }
                }

                yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
            else:
                result_data = {
                    "verdict": "信息不足，无法判断",
                    "reasoning": full_content,
                    "assistant_reply": assistant_reply,
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
        prompt = (
            build_assistant_llm_prompt(request.claim, reasoning_results)
            if request.response_mode == "assistant"
            else build_llm_prompt(request.claim, reasoning_results)
        )

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
        assistant_reply = (
            _clean_assistant_reply(reasoning_result.get("reasoning", ""))
            if request.response_mode == "assistant"
            else None
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

                # 所有检索结果（含未入选核心证据的）用于展示完整来源
                all_search_results_dicts = [
                    {
                        "title": result.name,
                        "url": result.url,
                        "domain": result.source or (lambda u: (u.split('/')[2].replace('www.', '') if len(u.split('/')) > 2 else u))(result.url)
                    }
                    for result in search_results
                ]

                reasoning_text = reasoning_result.get("reasoning", "")
                evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                    claim=request.claim,
                    search_results=search_results_dicts,
                    enable_link_validation=request.enable_link_validation,
                    top_k=len(reasoning_results),
                    reasoning_text=reasoning_text,
                    total_search_results=len(search_results),
                    all_search_results=all_search_results_dicts
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
                    "ai_summary": evidence_chain.ai_summary,
                    "all_search_results": getattr(evidence_chain, "all_search_results", [])
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
            assistant_reply=assistant_reply,
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


# ==================== 定时回放 SSE 生成器 ====================

def _build_progress_event(stage: str, message: str, **extra) -> str:
    """构建 progress SSE 事件字符串。"""
    payload = {"stage": stage, "message": message, "queue": {}, **extra}
    return f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_thinking_event(content: str, finished: bool = False) -> str:
    """构建 thinking SSE 事件字符串。"""
    payload = {"content": content, "finished": finished}
    return f"event: thinking\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _build_content_event(content: str, finished: bool = False) -> str:
    """构建 content SSE 事件字符串。"""
    payload = {"content": content, "finished": finished}
    return f"event: content\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _generate_paced_playback(
    cached: Dict,
    claim: str,
) -> AsyncIterator[str]:
    """从预计算结果生成 ~30s 定时回放 SSE 事件流。

    使用 time.monotonic() 绝对时钟，防止累积漂移。
    """
    t0 = time.monotonic()
    TOTAL = config.PLAYBACK_TOTAL_DURATION
    search_count = cached.get("search_count", 0)
    core_count = cached.get("core_count", 0)
    thinking_content = cached.get("thinking_content", "") or ""
    full_content = cached.get("full_content", "") or ""
    evidence_chain_data = cached.get("evidence_chain")
    assistant_reply = cached.get("assistant_reply", "") or ""

    async def _sleep_until(target_elapsed: float):
        """休眠直到从 t0 起恰好经过 target_elapsed 秒。"""
        delay = target_elapsed - (time.monotonic() - t0)
        if delay > 0.001:
            await asyncio.sleep(delay)

    try:
        # ===== Phase 1: 进度展示 (0 - 3.0s) =====
        yield _build_progress_event("queue_started", "已进入核查流程。")
        await _sleep_until(1.0)

        yield _build_progress_event("searching", "正在联网搜索证据...")
        await _sleep_until(2.0)

        yield _build_progress_event(
            "found",
            f"检索到 {search_count} 个相关结果，正在基于其中 {core_count} 条核心证据分析...",
        )
        await _sleep_until(3.0)

        # ===== Phase 2: 思考展示 (3.0 - 8.0s 或 3.0 - 5.0s) =====
        has_thinking = bool(thinking_content and thinking_content.strip())

        if has_thinking:
            yield _build_progress_event("thinking_start", "AI 开始深度思考...")
            thinking_chunks = _chunk_text(
                thinking_content, config.PLAYBACK_THINKING_CHUNK_SIZE
            )
            thinking_end = 8.0
            interval = (thinking_end - 3.0) / len(thinking_chunks) if thinking_chunks else 0.5
            for i, chunk in enumerate(thinking_chunks):
                await _sleep_until(3.0 + (i + 1) * interval)
                yield _build_thinking_event(chunk)
        else:
            await _sleep_until(3.5)
            yield _build_progress_event("thinking_start", "AI 开始深度思考...")
            await _sleep_until(5.0)

        # ===== Phase 3: 内容展示 (当前时间 - (TOTAL - 4.0)s) =====
        content_start = time.monotonic() - t0
        done_phase_duration = 4.0
        content_end = max(content_start + 3.0, TOTAL - done_phase_duration)
        content_duration = content_end - content_start

        content_chunks = _chunk_text(full_content, config.PLAYBACK_CHUNK_SIZE)
        interval = content_duration / len(content_chunks) if content_chunks else 1.0

        for i, chunk in enumerate(content_chunks):
            await _sleep_until(content_start + (i + 1) * interval)
            yield _build_content_event(chunk)

        # ===== Phase 4: 结果完成 (最后 4 秒) =====
        await _sleep_until(TOTAL - 3.0)
        yield _build_progress_event("processing", "正在生成证据链...")

        await _sleep_until(TOTAL - 1.0)

        # 构建 done 事件
        if evidence_chain_data:
            result_data = {
                "verdict": evidence_chain_data.get("verdict", "信息不足，无法判断"),
                "reasoning": full_content,
                "assistant_reply": assistant_reply,
                "thinking_process": thinking_content,
                "evidence_chain": evidence_chain_data,
            }
        else:
            result_data = {
                "verdict": "信息不足，无法判断",
                "reasoning": full_content,
                "assistant_reply": assistant_reply,
            }

        yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"
        await _sleep_until(TOTAL)

    except Exception as e:
        logger.error(f"回放生成器异常: {e}", exc_info=True)
        yield f'event: error\ndata: {{"message": "{str(e)}"}}\n\n'


# ==================== 回放核查端点（A组专用） ====================

@router.post("/api/v1/check/playback")
async def fact_check_playback(request: FactCheckRequest):
    """预计算回放端点（A组 / plugin_structured 专用）。

    从缓存读取预计算好的完整结果，按 ~30s 时间线分块发射 SSE 事件。
    缓存未命中时降级到实时流式计算。
    """
    logger.info(f"开始回放核查 (news_id={request.news_id}): {request.claim[:80]}...")

    async def generate():
        try:
            # --- 步骤 0: 查找缓存 ---
            cached = _get_precomputed_cache_for_request(request)
            if cached:
                logger.info(f"回放命中缓存: news_id={cached.get('news_id')}")
            if not cached:
                logger.info("回放未命中缓存，降级到实时流式")

            if cached:
                # 缓存命中：走定时回放
                async for event_str in _generate_paced_playback(cached, request.claim):
                    yield event_str
            else:
                # 缓存未命中：降级到实时流式计算
                # 复用现有流式端点逻辑（内联简化版）
                task_id = _task_queue.create_task_id()
                acquired = False
                try:
                    async for queue_snapshot in _task_queue.acquire(task_id):
                        queue_data = queue_snapshot.to_dict()
                        if queue_snapshot.state == "queued":
                            payload = {
                                "stage": "queued",
                                "message": (
                                    f"当前有 {queue_snapshot.running} 个核查任务正在运行，"
                                    f"{queue_snapshot.queued} 个任务排队；你前面还有 "
                                    f"{queue_snapshot.queued_ahead} 个任务。"
                                ),
                                "queue": queue_data,
                            }
                            yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                        else:
                            acquired = True
                            break

                    yield _build_progress_event("searching", "正在联网搜索证据...")
                    search_results = await search_evidence(request.claim)

                    if not search_results:
                        yield f'event: error\ndata: {{"message": "未找到相关搜索结果"}}\n\n'
                        return

                    yield _build_progress_event(
                        "found",
                        f"检索到 {len(search_results)} 个相关结果，正在筛选核心证据并分析...",
                    )

                    reasoning_results = _select_core_evidence(request.claim, search_results)
                    if not reasoning_results:
                        yield f'event: error\ndata: {{"message": "未找到可用于核查的高相关近期证据"}}\n\n'
                        return

                    prompt = build_llm_prompt(request.claim, reasoning_results)

                    yield _build_progress_event("thinking_start", "AI 开始深度思考...")

                    request_params = {
                        "model": config.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 6000,
                        "stream": True,
                    }

                    response = await _resolve_maybe_awaitable(
                        _llm_client.chat.completions.create(**request_params)
                    )

                    full_content = ""
                    thinking_content = ""

                    async for chunk in _iterate_llm_stream(response):
                        if chunk.choices and chunk.choices[0].delta:
                            delta = chunk.choices[0].delta

                            if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                                thinking_content += delta.reasoning_content
                                yield _build_thinking_event(delta.reasoning_content)

                            if hasattr(delta, "content") and delta.content:
                                full_content += delta.content
                                yield _build_content_event(delta.content)

                    if not full_content and thinking_content:
                        full_content = thinking_content

                    full_content = sanitize_model_preamble(
                        _normalize_core_evidence_count_text(full_content, len(reasoning_results))
                    )

                    yield _build_progress_event("processing", "正在生成证据链...")

                    # 生成证据链
                    evidence_chain_data = None
                    if request.enable_evidence_chain:
                        search_results_dicts = [
                            {"title": r.name, "url": r.url, "summary": r.summary, "date_published": r.date_published}
                            for r in reasoning_results
                        ]
                        all_search_results_dicts = [
                            {"title": r.name, "url": r.url, "domain": r.source or _extract_domain(r.url)}
                            for r in search_results
                        ]
                        evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                            claim=request.claim,
                            search_results=search_results_dicts,
                            enable_link_validation=request.enable_link_validation,
                            top_k=len(reasoning_results),
                            reasoning_text=full_content,
                            total_search_results=len(search_results),
                            all_search_results=all_search_results_dicts,
                        )
                        evidence_chain_data = {
                            "supporting_evidence": evidence_chain.supporting_evidence,
                            "opposing_evidence": evidence_chain.opposing_evidence,
                            "neutral_evidence": evidence_chain.neutral_evidence,
                            "total_evidence": evidence_chain.total_evidence,
                            "total_search_results": evidence_chain.total_search_results,
                            "reasoning_summary": evidence_chain.reasoning_summary,
                            "ai_summary": evidence_chain.ai_summary,
                            "all_search_results": getattr(evidence_chain, "all_search_results", []),
                        }

                    result_data = {
                        "verdict": evidence_chain.verdict if evidence_chain_data else "信息不足，无法判断",
                        "reasoning": full_content,
                        "assistant_reply": "",
                        "thinking_process": thinking_content,
                    }
                    if evidence_chain_data:
                        result_data["evidence_chain"] = evidence_chain_data

                    yield f"event: done\ndata: {json.dumps(result_data, ensure_ascii=False)}\n\n"

                except SearchServiceError as e:
                    logger.error(f"搜索服务不可用: {e}")
                    yield f'event: error\ndata: {json.dumps({"message": str(e)}, ensure_ascii=False)}\n\n'
                except Exception as e:
                    logger.error(f"实时核查失败: {e}", exc_info=True)
                    yield f'event: error\ndata: {{"message": "{str(e)}"}}\n\n'
                finally:
                    if acquired:
                        await _task_queue.release(task_id)

        except Exception as e:
            logger.error(f"回放核查失败: {e}", exc_info=True)
            yield f'event: error\ndata: {{"message": "{str(e)}"}}\n\n'

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 预计算端点（管理员用） ====================

from pydantic import BaseModel as _PydanticBaseModel, Field as _Field


class PrecomputeItem(_PydanticBaseModel):
    news_id: int = _Field(ge=1, description="新闻编号 1-6")
    claim: str = _Field(min_length=1, max_length=2000, description="待核查的说法文本（用于 LLM 分析）")
    title: str = _Field(default="", max_length=500, description="新闻标题（用于模糊匹配）")
    body: str = _Field(default="", max_length=2000, description="新闻正文（用于模糊匹配）")


class PrecomputeRequest(_PydanticBaseModel):
    items: List[PrecomputeItem] = _Field(min_length=1, max_length=20)


class PrecomputeItemResult(_PydanticBaseModel):
    news_id: int
    status: str  # "success" | "failed"
    elapsed_seconds: float
    search_count: int = 0
    core_count: int = 0
    error: str = ""


class PrecomputeResponse(_PydanticBaseModel):
    total_seconds: float
    results: List[PrecomputeItemResult]


@router.post("/api/v1/admin/precompute", response_model=PrecomputeResponse)
async def admin_precompute(payload: PrecomputeRequest):
    """预计算端点：对指定新闻列表执行完整核查 pipeline 并缓存结果。

    实验前一次性调用，将 6 条新闻的核查结果全部预计算好。
    """
    import time as _time

    overall_start = _time.monotonic()
    results: List[PrecomputeItemResult] = []

    for item in payload.items:
        item_start = _time.monotonic()
        try:
            logger.info(f"预计算开始 news_id={item.news_id}: {item.claim[:80]}...")

            # Step 1: 搜索
            search_results = await search_evidence(item.claim)
            if not search_results:
                raise ValueError("未找到相关搜索结果")

            # Step 2: 核心证据筛选
            reasoning_results = _select_core_evidence(item.claim, search_results)
            if not reasoning_results:
                raise ValueError("未找到可用于核查的高相关近期证据")

            # Step 3: 构造 Prompt（A组用结构化 prompt）
            prompt = build_llm_prompt(item.claim, reasoning_results)

            # Step 4: LLM 调用（非流式，启用思考）
            request_params = {
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 6000,
                "stream": False,
            }

            response = await _resolve_maybe_awaitable(
                _llm_client.chat.completions.create(**request_params)
            )

            message = response.choices[0].message
            full_content = message.content or ""
            thinking_content = getattr(message, "reasoning_content", None) or ""

            if not full_content and thinking_content:
                full_content = thinking_content

            full_content = sanitize_model_preamble(
                _normalize_core_evidence_count_text(full_content, len(reasoning_results))
            )

            # Step 5: 证据链生成
            search_results_dicts = [
                {"title": r.name, "url": r.url, "summary": r.summary, "date_published": r.date_published}
                for r in reasoning_results
            ]
            all_search_results_dicts = [
                {"title": r.name, "url": r.url, "domain": r.source or _extract_domain(r.url)}
                for r in search_results
            ]

            evidence_chain = await _evidence_chain_generator.generate_evidence_chain(
                claim=item.claim,
                search_results=search_results_dicts,
                enable_link_validation=False,
                top_k=len(reasoning_results),
                reasoning_text=full_content,
                total_search_results=len(search_results),
                all_search_results=all_search_results_dicts,
            )

            # Step 6: 组装缓存数据
            cache_data = {
                "news_id": item.news_id,
                "claim": item.claim,
                "title": item.title or "",
                "body": item.body or "",
                "claim_fingerprint": _build_claim_fingerprint(item.claim),
                "title_fingerprint": _build_claim_fingerprint(item.title) if item.title else "",
                "body_fingerprint": _build_claim_fingerprint(item.body) if item.body else "",
                "precomputed_at": datetime.now(dt_timezone.utc).isoformat(),
                "search_count": len(search_results),
                "core_count": len(reasoning_results),
                "thinking_content": thinking_content,
                "full_content": full_content,
                "assistant_reply": "",
                "evidence_chain": {
                    "verdict": evidence_chain.verdict,
                    "supporting_evidence": evidence_chain.supporting_evidence,
                    "opposing_evidence": evidence_chain.opposing_evidence,
                    "neutral_evidence": evidence_chain.neutral_evidence,
                    "total_evidence": evidence_chain.total_evidence,
                    "total_search_results": evidence_chain.total_search_results,
                    "reasoning_summary": evidence_chain.reasoning_summary,
                    "ai_summary": evidence_chain.ai_summary,
                    "all_search_results": getattr(evidence_chain, "all_search_results", []),
                },
            }

            _save_cache(item.news_id, cache_data)

            elapsed = _time.monotonic() - item_start
            results.append(PrecomputeItemResult(
                news_id=item.news_id,
                status="success",
                elapsed_seconds=round(elapsed, 1),
                search_count=len(search_results),
                core_count=len(reasoning_results),
            ))
            logger.info(f"预计算完成 news_id={item.news_id}, 耗时 {elapsed:.1f}s")

        except Exception as e:
            elapsed = _time.monotonic() - item_start
            logger.error(f"预计算失败 news_id={item.news_id}: {e}", exc_info=True)
            results.append(PrecomputeItemResult(
                news_id=item.news_id,
                status="failed",
                elapsed_seconds=round(elapsed, 1),
                error=str(e),
            ))

    total_elapsed = _time.monotonic() - overall_start
    logger.info(f"全部预计算完成，总耗时 {total_elapsed:.1f}s，成功 {sum(1 for r in results if r.status == 'success')}/{len(results)}")

    return PrecomputeResponse(total_seconds=round(total_elapsed, 1), results=results)
