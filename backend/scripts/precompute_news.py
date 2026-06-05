#!/usr/bin/env python3
"""
独立预计算脚本：对 6 条实验新闻执行完整核查 pipeline 并缓存结果。

直接调用 Bocha API + DeepSeek LLM。搜索召回阶段可放宽时效限制，
但核心证据筛选必须复用后端线上质量门槛。

用法:
    cd backend
    python3 scripts/precompute_news.py [--news-id N] [--dry-run] [--force]

    --news-id N   仅预计算第 N 条新闻（1-6），省略则计算全部 6 条
    --dry-run     仅搜索 + 筛选核心证据，不调用 LLM
    --force       强制重新计算，忽略已有缓存
"""
import sys
import os
import argparse
import asyncio
import time
import json
import re
import hashlib
import httpx
from typing import List, Dict, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from services.llm_service import build_llm_prompt, sanitize_model_preamble
from services.search import (
    _extract_core_query,
    _simplify_claim_for_search,
    _filter_irrelevant_results as _search_filter_irrelevant,
    _is_time_sensitive_claim,
)
from services.evidence_chain_generator import EvidenceChainGenerator
from routers.fact_check import (
    _select_core_evidence,
    _normalize_core_evidence_count_text,
    _extract_domain,
    CORE_EVIDENCE_LIMIT,
)

# ==================== 6 条新闻定义 ====================

NEWS_ITEMS = [
    {
        "news_id": 1,
        "title": "国家育儿补贴制度实施方案正式公布",
        "body": "2025年7月，国家育儿补贴制度实施方案正式公布。根据方案，从2025年1月1日起，无论一孩、二孩、三孩，每个孩子每年均可领取3600元育儿补贴，直至年满3周岁。",
        "claim": "2025年7月，国家育儿补贴制度实施方案正式公布。根据方案，从2025年1月1日起，无论一孩、二孩、三孩，每个孩子每年均可领取3600元育儿补贴，直至年满3周岁。",
    },
    {
        "news_id": 2,
        "title": "6月1日起，《机动车驾驶人疲劳驾驶认定规则》正式实施",
        "body": "6月1日起，《机动车驾驶人疲劳驾驶认定规则》正式实施。该规则适用于道路交通事故调查处理环节中疲劳驾驶行为的认定。其中从事班车客运、包车客运、旅游客运的经营性驾驶员，适用该规则中关于客运机动车驾驶人的认定标准。规则属于国家公共安全行业标准（GA/T标准）。",
        "claim": "6月1日起，《机动车驾驶人疲劳驾驶认定规则》正式实施。该规则适用于道路交通事故调查处理环节中疲劳驾驶行为的认定。其中从事班车客运、包车客运、旅游客运的经营性驾驶员，适用该规则中关于客运机动车驾驶人的认定标准。规则属于国家公共安全行业标准（GA/T标准）。",
    },
    {
        "news_id": 3,
        "title": "外卖平台年龄新规：45岁以上骑手将禁止接单",
        "body": "外卖平台开始执行年龄新规：禁止45岁以上的骑手接单，系统会自动清退超龄骑手。平台称这是全国统一安全管理要求，众包骑手和专送骑手都必须执行。",
        "claim": "外卖平台开始执行年龄新规：禁止45岁以上的骑手接单，系统会自动清退超龄骑手。平台称这是全国统一安全管理要求，众包骑手和专送骑手都必须执行。",
    },
    {
        "news_id": 4,
        "title": "环保新规导致鸡蛋价格大幅上涨",
        "body": "环保新规导致养殖成本大幅增加，鸡蛋价格持续上涨，多地突破历史高位。新规对养殖场的环保要求全面提高，小型养殖户面临关停，市场供应减少推高价格。",
        "claim": "环保新规导致鸡蛋价格大幅上涨。环保新规导致养殖成本大幅增加，鸡蛋价格持续上涨，多地突破历史高位。新规对养殖场的环保要求全面提高，小型养殖户面临关停，市场供应减少推高价格。",
    },
    {
        "news_id": 5,
        "title": "5月1日起新规实施！医生全面取消24小时连续值班制度",
        "body": "5月1日起新规实施！医生全面取消24小时连续值班制度，全国医院统一执行。住院医师不用再连续工作24小时，医疗行业迎来重大改革。",
        "claim": "5月1日起新规实施！医生全面取消24小时连续值班制度，全国医院统一执行。住院医师不用再连续工作24小时，医疗行业迎来重大改革。",
    },
    {
        "news_id": 6,
        "title": "黄鳝养殖大量使用避孕药",
        "body": "黄鳝养殖大量使用避孕药，市场上买到的黄鳝都不安全。业内人士透露，养殖户为了让黄鳝快速增肥，会在饲料中添加避孕药。这种说法每年黄鳝上市季都会引起广泛关注。",
        "claim": "黄鳝养殖大量使用避孕药，市场上买到的黄鳝都不安全。业内人士透露，养殖户为了让黄鳝快速增肥，会在饲料中添加避孕药。这种说法每年黄鳝上市季都会引起广泛关注。",
    },
]


# ==================== 缓存工具 ====================

def _get_cache_dir():
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _load_cache(news_id):
    cache_path = os.path.join(_get_cache_dir(), f"{news_id}.json")
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_fingerprint(text):
    normalized = re.sub(r"\s+", "", text)
    normalized = re.sub(r"[，。！？、；：""''「」【】《》（）—…\-,.!?;:""''\[\]()\n]", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _save_cache(news_id, data, title, body):
    cache_path = os.path.join(_get_cache_dir(), f"{news_id}.json")
    data["title"] = title
    data["body"] = body
    data["title_fingerprint"] = _build_fingerprint(title) if title else ""
    data["body_fingerprint"] = _build_fingerprint(body) if body else ""
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  💾 缓存已保存: {cache_path}")


# ==================== 放宽版搜索 ====================

def _extract_domain_simple(url: str) -> str:
    try:
        parts = url.split("/")
        if len(parts) > 2:
            return parts[2].replace("www.", "")
    except Exception:
        pass
    return url


def _extract_keywords(text: str) -> List[str]:
    """从文本中提取关键词用于相关性打分。"""
    import jieba
    # 去掉停用词性质的高频单字
    words = jieba.lcut(text)
    # 保留长度 >= 2 的词
    keywords = [w for w in words if len(w) >= 2]
    return keywords


def _simple_relevance_score(claim: str, title: str, summary: str) -> float:
    """简化的相关性打分：关键词命中率，不做时效性判断。"""
    try:
        import jieba
        claim_words = set(jieba.lcut(claim))
    except ImportError:
        # 无 jieba 时退化为字符级 trigram
        return _char_trigram_similarity(claim, title + summary)

    claim_keywords = {w for w in claim_words if len(w) >= 2}
    if not claim_keywords:
        return 0.5

    text = title + summary
    text_words = set(jieba.lcut(text))

    hits = sum(1 for kw in claim_keywords if kw in text_words)
    return hits / len(claim_keywords)


def _char_trigram_similarity(a: str, b: str) -> float:
    """字符 trigram 相似度（无需分词）。"""
    a = re.sub(r"\s+", "", a)
    b = re.sub(r"\s+", "", b)
    if len(a) < 3 or len(b) < 3:
        return 0.3  # 默认中等
    trigrams_a = {a[i:i+3] for i in range(len(a) - 2)}
    trigrams_b = {b[i:i+3] for i in range(len(b) - 2)}
    if not trigrams_a or not trigrams_b:
        return 0.3
    intersection = len(trigrams_a & trigrams_b)
    union = len(trigrams_a | trigrams_b)
    return intersection / union if union > 0 else 0.3


async def _search_bocha_relaxed(query: str, client: httpx.AsyncClient, min_relevance: float = 0.15) -> List[Dict]:
    """直接调用 Bocha API，放宽相关性过滤，不做时效性判断。"""
    results = []
    url = config.BOCHA_BASE_URL
    headers = {
        "Authorization": f"Bearer {config.BOCHA_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "summary": True,
        "count": 50,
        # 不设 freshness 限制
    }

    try:
        response = await client.post(url, json=payload, headers=headers, timeout=30.0)
        if response.status_code != 200:
            print(f"    ⚠️  Bocha 查询失败 [{response.status_code}]: {response.text[:200]}")
            return results

        data = response.json()
        webpages = data.get("data", {}).get("webPages", {}).get("value", [])

        for item in webpages:
            title = item.get("name", "")
            result_url = item.get("url", "")
            summary = item.get("summary", "") or item.get("snippet", "")
            date_str = item.get("datePublished", "") or item.get("dateLastCrawled", "")

            # 放宽相关性判定
            rel_score = _simple_relevance_score(query, title, summary)
            if rel_score < min_relevance:
                continue

            results.append({
                "name": title,
                "url": result_url,
                "summary": summary,
                "date_published": date_str,
                "source": _extract_domain_simple(result_url),
                "_rel_score": rel_score,
            })

        print(f"    Bocha '{query[:40]}...' -> {len(webpages)} raw, {len(results)} relevant")
    except Exception as e:
        print(f"    ⚠️  Bocha 请求异常: {e}")

    return results


async def search_evidence_relaxed(claim: str) -> Tuple[List[Dict], List[Dict]]:
    """
    放宽版搜索：生成多个查询，并行调 Bocha，合并去重。
    不做时效性过滤，以相关性为主要标准。

    Returns (all_results, core_results)
    """
    # 生成查询
    queries = []
    core_q = _extract_core_query(claim)
    if core_q:
        queries.append(core_q)

    # 原始 claim（截断）
    if len(claim) > 30:
        queries.append(claim[:200])

    # 简化查询
    simplified = _simplify_claim_for_search(claim)
    if simplified and simplified not in queries:
        queries.append(simplified)

    # 去重
    seen = set()
    unique_queries = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_queries.append(q)

    # 并行搜索
    async with httpx.AsyncClient() as client:
        all_raw = []
        for q in unique_queries:
            results = await _search_bocha_relaxed(q, client, min_relevance=0.1)
            all_raw.extend(results)
            # 小延迟避免触发频率限制
            await asyncio.sleep(0.3)

    # URL 去重
    seen_urls = set()
    all_results = []
    for r in all_raw:
        url = r["url"]
        if url not in seen_urls:
            seen_urls.add(url)
            all_results.append(r)

    # 按相关性排序
    all_results.sort(key=lambda x: x.get("_rel_score", 0), reverse=True)

    # 转换为 SearchResult-like dicts
    print(f"    总结果: {len(all_results)} 条 (去重后)")

    # 构建两个列表: all_results (dict list), core_results (top N dict list)
    # 这里 all_results 就是全部, core_results 我们会用 _select_core_evidence 筛选
    # 但 _select_core_evidence 需要 SearchResult 对象...
    # 我们用简化的核心证据筛选
    top_n = min(len(all_results), CORE_EVIDENCE_LIMIT)
    core_results = all_results[:top_n]

    return all_results, core_results


# ==================== 简化版核心证据筛选 ====================

def _simple_core_filter(claim: str, all_results: List[Dict], limit: int = 18) -> List[Dict]:
    """
    核心证据筛选包装器。

    预计算缓存必须复用线上核查的严格质量门槛，避免高相关但低可信、
    陈旧或同质转载的结果进入实验材料。
    """
    from models import SearchResult

    result_objects = [
        SearchResult(
            name=r.get("name", ""),
            url=r.get("url", ""),
            summary=r.get("summary", ""),
            date_published=r.get("date_published") or "",
            source=r.get("source", ""),
        )
        for r in all_results
    ]
    selected_objects = _select_core_evidence(claim, result_objects)[:limit]

    by_url = {r.get("url", ""): r for r in all_results}
    selected = []
    for item in selected_objects:
        if item.url in by_url:
            selected.append(by_url[item.url])

    return selected


# ==================== 核心逻辑 ====================


async def precompute_one(news: dict, dry_run: bool = False, force: bool = False):
    """预计算单条新闻。"""
    news_id = news["news_id"]
    title = news["title"]
    body = news["body"]
    claim = news["claim"]

    print(f"\n{'='*60}")
    print(f"📰 新闻 {news_id}: {title}")
    print(f"{'='*60}")

    # 检查已有缓存
    existing = _load_cache(news_id)
    if existing and not force:
        print(f"  ⏭️  已有缓存 (预计算时间: {existing.get('precomputed_at', '未知')})，跳过")
        print(f"  📊 搜索结果: {existing.get('search_count', 0)} 条, 核心证据: {existing.get('core_count', 0)} 条")
        print(f"  🏷️  结论: {existing.get('evidence_chain', {}).get('verdict', 'N/A')}")
        return existing

    t0 = time.monotonic()

    # Step 1: 放宽版搜索
    print(f"  🔍 正在搜索 (放宽模式)...")
    all_search_dicts, _ = await search_evidence_relaxed(claim)

    if not all_search_dicts:
        print(f"  ❌ 未找到任何相关搜索结果")
        return None

    # Step 2: 严格核心证据筛选
    print(f"  🎯 正在筛选核心证据...")
    core_dicts = _simple_core_filter(claim, all_search_dicts)
    print(f"  ✅ 核心证据: {len(core_dicts)} 条 (从 {len(all_search_dicts)} 条中筛选)")

    if dry_run:
        print(f"\n  📋 搜索结果预览 (Top 10):")
        for i, r in enumerate(core_dicts[:10]):
            print(f"     [{i+1}] {r['name'][:60]}...")
            print(f"         {r['url']}")
            print(f"         {r['summary'][:120]}...")
            print(f"         日期: {r.get('date_published', 'N/A')}, 来源: {r.get('source', 'N/A')}")
        print(f"\n  🏁 Dry-run 完成（未调用 LLM）")
        return None

    # Step 3: 构造 Prompt
    # 需要转换为 build_llm_prompt 可用的格式
    from models import SearchResult
    core_results_obj = [
        SearchResult(
            name=r["name"],
            url=r["url"],
            summary=r["summary"],
            date_published=r.get("date_published") or "",
            source=r.get("source", ""),
        )
        for r in core_dicts
    ]
    all_results_obj = [
        SearchResult(
            name=r["name"],
            url=r["url"],
            summary=r["summary"],
            date_published=r.get("date_published") or "",
            source=r.get("source", ""),
        )
        for r in all_search_dicts
    ]

    prompt = build_llm_prompt(claim, core_results_obj)
    print(f"  📝 Prompt 长度: {len(prompt)} 字符")

    # Step 4: LLM 调用
    print(f"  🤖 正在调用 LLM ({config.LLM_MODEL})...")
    from openai import AsyncOpenAI
    llm_client = AsyncOpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
    )

    response = await llm_client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=6000,
        stream=False,
    )

    message = response.choices[0].message
    full_content = message.content or ""
    thinking_content = getattr(message, "reasoning_content", None) or ""

    if not full_content and thinking_content:
        full_content = thinking_content

    full_content = sanitize_model_preamble(
        _normalize_core_evidence_count_text(full_content, len(core_results_obj))
    )
    print(f"  ✅ LLM 响应: {len(full_content)} 字符, thinking: {len(thinking_content)} 字符")
    print(f"  📄 LLM 前200字: {full_content[:200]}...")

    # Step 5: 证据链生成
    print(f"  🔗 正在生成证据链...")
    search_results_dicts = [
        {"title": r.name, "url": r.url, "summary": r.summary, "date_published": r.date_published}
        for r in core_results_obj
    ]
    all_search_results_dicts = [
        {"title": r.name, "url": r.url, "domain": r.source or _extract_domain(r.url)}
        for r in all_results_obj
    ]

    evidence_generator = EvidenceChainGenerator(
        glm_client=llm_client,
        model_name=config.LLM_MODEL,
    )

    evidence_chain = await evidence_generator.generate_evidence_chain(
        claim=claim,
        search_results=search_results_dicts,
        enable_link_validation=False,
        top_k=len(core_results_obj),
        reasoning_text=full_content,
        total_search_results=len(all_search_dicts),
        all_search_results=all_search_results_dicts,
    )

    print(f"  ✅ 证据链: {evidence_chain.verdict}")
    print(f"     支持: {len(evidence_chain.supporting_evidence)}, 反对: {len(evidence_chain.opposing_evidence)}, 中立: {len(evidence_chain.neutral_evidence)}")

    # Step 6: 组装缓存
    cache_data = {
        "news_id": news_id,
        "claim": claim,
        "claim_fingerprint": _build_fingerprint(claim),
        "precomputed_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "search_count": len(all_search_dicts),
        "core_count": len(core_results_obj),
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

    _save_cache(news_id, cache_data, title, body)
    elapsed = time.monotonic() - t0
    print(f"  ⏱️  总耗时: {elapsed:.1f}s")
    return cache_data


async def main():
    parser = argparse.ArgumentParser(description="预计算实验新闻核查结果")
    parser.add_argument("--news-id", type=int, choices=range(1, 7), help="仅预计算指定新闻")
    parser.add_argument("--dry-run", action="store_true", help="仅搜索 + 筛选，不调用 LLM")
    parser.add_argument("--force", action="store_true", help="强制重新计算，忽略已有缓存")
    args = parser.parse_args()

    items = NEWS_ITEMS
    if args.news_id:
        items = [n for n in NEWS_ITEMS if n["news_id"] == args.news_id]

    print(f"🚀 预计算脚本启动")
    print(f"   LLM: {config.LLM_MODEL}")
    print(f"   Bocha API: {config.BOCHA_BASE_URL}")
    print(f"   缓存目录: {_get_cache_dir()}")
    print(f"   模式: {'Dry-run (仅搜索)' if args.dry_run else '完整计算 (搜索+LLM+证据链)'}")
    print(f"   新闻数量: {len(items)}")

    results = []
    for item in items:
        try:
            result = await precompute_one(item, dry_run=args.dry_run, force=args.force)
            status = "success" if result else ("dry-run" if args.dry_run else "skipped")
            results.append({"news_id": item["news_id"], "status": status})
        except Exception as e:
            print(f"  ❌ 预计算失败 news_id={item['news_id']}: {e}")
            import traceback
            traceback.print_exc()
            results.append({"news_id": item["news_id"], "status": "failed", "error": str(e)})

    print(f"\n{'='*60}")
    print(f"🏁 预计算完成")
    for r in results:
        print(f"  新闻 {r['news_id']}: {r['status']}")

    # 验证缓存指纹
    print(f"\n🔬 缓存指纹一览:")
    for item in items:
        news_id = item["news_id"]
        title = item["title"]
        body = item["body"]
        claim = item["claim"]
        print(f"  新闻 {news_id}: title_fp={_build_fingerprint(title)}, body_fp={_build_fingerprint(body)}, full_fp={_build_fingerprint(claim)}")


if __name__ == "__main__":
    asyncio.run(main())
