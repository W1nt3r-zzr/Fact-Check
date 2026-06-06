#!/usr/bin/env python3
"""
独立预计算脚本（v2.0 放宽版）：对 6 条实验新闻执行完整核查 pipeline 并缓存结果。

与线上核查流程的区别：
- 搜索阶段：直接调 Bocha API，min_relevance=0.10（线上为 0.20）
- 筛选阶段：仅按「相关性 + 时效性」简单打分排序，不经过 _select_core_evidence 的
  严格权威性/同质化/猜测过滤
- LLM 与证据链阶段：与线上完全一致

用法:
    cd backend
    python3 scripts/precompute_news.py [--news-id N] [--dry-run] [--force]

    --news-id N   仅预计算第 N 条新闻（1-6），省略则计算全部 6 条
    --dry-run     仅搜索 + 打分，不调用 LLM
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
from datetime import datetime, date, timezone as dt_timezone
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config
from services.llm_service import build_llm_prompt, build_assistant_llm_prompt, sanitize_model_preamble
from services.search import _extract_core_query, _simplify_claim_for_search
from services.evidence_chain_generator import EvidenceChainGenerator
from routers.fact_check import _normalize_core_evidence_count_text, _extract_domain

# ==================== 新闻真实性类型（来自交付文档） ====================
# "true": 真实, "semi_true": 半真半假, "false": 假
NEWS_TRUTH_TYPES = {
    1: "true",
    2: "true",
    3: "semi_true",
    4: "semi_true",
    5: "semi_true",
    6: "false",
}

# ==================== 6 条新闻定义 ====================

NEWS_ITEMS = [
    {
        "news_id": 1,
        "title": "爷爷奶奶帮忙带娃，也能领国家育儿补贴吗？",
        "body": "2025年7月，国家育儿补贴制度实施方案公布。从2025年1月1日起，对符合法律法规规定生育的3周岁以下婴幼儿发放补贴，现阶段国家基础标准为每孩每年3600元。由于补贴按孩次发放、可通过线上线下渠道申领，一些家庭理解为只要实际照看孩子的长辈也能直接领取。但申领人、户籍和监护关系等条件仍需按方案及地方细则办理。",
        "claim": "2025年7月，国家育儿补贴制度实施方案公布。从2025年1月1日起，对符合法律法规规定生育的3周岁以下婴幼儿发放补贴，现阶段国家基础标准为每孩每年3600元。由于补贴按孩次发放、可通过线上线下渠道申领，一些家庭理解为只要实际照看孩子的长辈也能直接领取。但申领人、户籍和监护关系等条件仍需按方案及地方细则办理。",
    },
    {
        "news_id": 2,
        "title": "新规实施后，网约车司机夜间开车超2小时算疲劳驾驶？",
        "body": "《机动车驾驶人疲劳驾驶认定规则》自6月1日起实施。规则中提到，客运机动车驾驶人在夜间连续驾驶超过一定时间且未按要求休息的，可被认定为疲劳驾驶。由于“客运机动车驾驶人”的范围容易被理解得较宽，一些人认为出租车、网约车司机也适用该夜间驾驶标准。但该规则中的相关客运标准主要针对班车客运、包车客运、旅游客运等道路旅客运输经营活动。",
        "claim": "《机动车驾驶人疲劳驾驶认定规则》自6月1日起实施。规则中提到，客运机动车驾驶人在夜间连续驾驶超过一定时间且未按要求休息的，可被认定为疲劳驾驶。由于“客运机动车驾驶人”的范围容易被理解得较宽，一些人认为出租车、网约车司机也适用该夜间驾驶标准。但该规则中的相关客运标准主要针对班车客运、包车客运、旅游客运等道路旅客运输经营活动。",
    },
    {
        "news_id": 3,
        "title": "外卖平台加强年龄审核后，45岁以上骑手会被统一清退吗？",
        "body": "近期，外卖平台骑手年龄审核的话题引发关注。平台和合作服务商确实会设置年龄、健康状况、交通安全记录等准入和安全管理要求。网传消息称，45岁以上骑手将被全国统一禁止接单，系统会自动清退，众包和专送都必须执行；也有人认为这只是部分站点的安全审核要求，具体是否属于全国统一规则还需要进一步核实。",
        "claim": "近期，外卖平台骑手年龄审核的话题引发关注。平台和合作服务商确实会设置年龄、健康状况、交通安全记录等准入和安全管理要求。网传消息称，45岁以上骑手将被全国统一禁止接单，系统会自动清退，众包和专送都必须执行；也有人认为这只是部分站点的安全审核要求，具体是否属于全国统一规则还需要进一步核实。",
    },
    {
        "news_id": 4,
        "title": "鸡蛋价格上涨，和养殖环保要求升级有关吗？",
        "body": "近期鸡蛋价格阶段性上涨，多地零售价格明显高于前期水平。与此同时，养殖场环保治理、粪污处理等要求也持续受到关注。网传说法认为，新的环保要求推高了养殖成本，小型养殖户被迫退出，市场供应减少是蛋价上涨的主要原因。不过，鸡蛋价格还会受到补栏周期、饲料成本、季节性产蛋率和消费需求等因素影响，环保因素是否构成主要原因仍存在争议。",
        "claim": "近期鸡蛋价格阶段性上涨，多地零售价格明显高于前期水平。与此同时，养殖场环保治理、粪污处理等要求也持续受到关注。网传说法认为，新的环保要求推高了养殖成本，小型养殖户被迫退出，市场供应减少是蛋价上涨的主要原因。不过，鸡蛋价格还会受到补栏周期、饲料成本、季节性产蛋率和消费需求等因素影响，环保因素是否构成主要原因仍存在争议。",
    },
    {
        "news_id": 5,
        "title": "医生值班制度调整后，24小时连续值班会全面取消吗？",
        "body": "近期，关于医生值班制度改革的讨论再次增多。一些医院和科室确实在探索优化排班、减少连续高强度工作的做法。网传消息称，5月1日起医生24小时连续值班制度将全面取消，全国医院统一执行，住院医师不再需要连续工作24小时。但也有观点认为，值班安排涉及医院管理、科室人手和地方规定，是否存在全国统一新规还需要核实。",
        "claim": "近期，关于医生值班制度改革的讨论再次增多。一些医院和科室确实在探索优化排班、减少连续高强度工作的做法。网传消息称，5月1日起医生24小时连续值班制度将全面取消，全国医院统一执行，住院医师不再需要连续工作24小时。但也有观点认为，值班安排涉及医院管理、科室人手和地方规定，是否存在全国统一新规还需要核实。",
    },
    {
        "news_id": 6,
        "title": "黄鳝上市季又到，养殖户真的会喂避孕药催肥吗？",
        "body": "每到黄鳝集中上市季，关于养殖黄鳝安全性的讨论都会增多。网传说法称，有养殖户为了让黄鳝快速增肥，会在饲料中添加避孕药，因此市场上买到的黄鳝都不安全。也有人指出，这一说法已经流传多年，但因为涉及食品安全和儿童食用问题，仍然容易被反复转发。",
        "claim": "每到黄鳝集中上市季，关于养殖黄鳝安全性的讨论都会增多。网传说法称，有养殖户为了让黄鳝快速增肥，会在饲料中添加避孕药，因此市场上买到的黄鳝都不安全。也有人指出，这一说法已经流传多年，但因为涉及食品安全和儿童食用问题，仍然容易被反复转发。",
    },
]

# ==================== 核心证据数量上限 ====================
CORE_EVIDENCE_LIMIT = 10


# ==================== 缓存工具 ====================

def _get_cache_dir(group: str = "A") -> str:
    suffix = "_b" if group == "B" else ""
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f"cache{suffix}")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _load_cache(news_id: int, group: str = "A") -> Optional[Dict]:
    cache_path = os.path.join(_get_cache_dir(group), f"{news_id}.json")
    if not os.path.exists(cache_path):
        return None
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", "", text)
    normalized = re.sub(r"[，。！？、；：""''「」【】《》（）—…\-,.!?;:""''\[\]()\n]", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _save_cache(news_id: int, data: Dict, title: str, body: str, group: str = "A") -> None:
    cache_path = os.path.join(_get_cache_dir(group), f"{news_id}.json")
    data["title"] = title
    data["body"] = body
    data["title_fingerprint"] = _build_fingerprint(title) if title else ""
    data["body_fingerprint"] = _build_fingerprint(body) if body else ""
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  💾 缓存已保存: {cache_path}")


# ==================== 补充搜索：半真半假新闻的真实背景查询 ====================
# 对于半真半假类新闻，仅从 claim 出发搜索只能命中辟谣内容，
# 需要同时搜索真实背景事实，让 LLM 看到"半真"那半的证据。
NEWS_SUPPLEMENTARY_QUERIES = {
    3: [
        "45岁 骑手 禁止 接单 辟谣",
        "外卖 骑手 年龄 清退 谣言",
        "45岁以上 外卖 骑手 禁止 接单 平台 回应",
        "外卖平台 骑手 年龄 限制 规定 安全",
        "美团 饿了么 骑手 注册 条件 要求",
    ],
    4: [
        "养殖 环保 粪污 处理 成本 鸡蛋 涨价",
        "小型养殖户 环保 退出 蛋鸡 政策",
        "养殖场 环保 新规 鸡蛋 价格 影响",
        "鸡蛋 价格 上涨 2025 原因 分析",
        "蛋价 走高 饲料 成本 市场 供需",
    ],
    5: [
        "医生 24小时 值班 取消 辟谣",
        "医生 值班 制度 改革 5月1日 不实",
        "住院医师 连续 工作 24小时 谣言",
        "医院 夜班 连续 工作 时间 规定 卫健委",
        "医生 工作 负荷 值班 频次 政策",
    ],
}


# ==================== 简化的相关性 + 时效性打分 ====================

def _extract_domain_simple(url: str) -> str:
    try:
        parts = url.split("/")
        if len(parts) > 2:
            return parts[2].replace("www.", "")
    except Exception:
        pass
    return url


# 高频通用词：在相关性计算中降权，防止"新规""改革""5月"等词把无关文章拉进来
GENERIC_TERMS = {
    "新规", "实施", "改革", "取消", "统一", "全面", "正式", "公布", "最新",
    "消息", "新闻", "报道", "热点", "关注", "调整", "执行", "落地", "变化",
    "影响", "关乎", "注意", "重要", "政策", "制度", "方案", "通知", "规定",
    "标准", "规则", "开始", "以后", "之前", "已经", "目前", "现在", "今年",
    "5月", "6月", "1日", "1日起", "2025年", "2026年", "近日", "刚刚",
    "全国", "所有", "每个", "人人", "不再", "不用", "彻底", "全面取消",
    "重大", "迎来", "将", "被", "对", "在", "的", "是", "了", "不",
    "一孩", "二孩", "三孩", "补贴",  # 育儿补贴的通用词
}
# 每条新闻的核心实体词：结果必须命中至少 1 个才算主题相关
NEWS_CORE_ENTITIES = {
    1: {"育儿补贴", "育儿", "婴幼儿", "托育", "3600元"},
    2: {"疲劳驾驶", "GA/T", "行业标准", "班车客运", "包车客运", "旅游客运", "经营性驾驶员", "事故调查"},
    3: {"外卖", "骑手", "45岁", "年龄", "清退", "众包", "专送"},
    4: {"鸡蛋", "养殖", "环保", "蛋价", "养殖场", "养殖户", "饲料"},
    5: {"医生", "值班", "医院", "住院医师", "连轴转", "夜班"},
    6: {"黄鳝", "避孕药", "性逆转", "水产", "养殖"},
}


def _get_core_entities(news_id: int) -> set:
    """获取预定义的核心实体词（仅使用手动标注，不做自动提取以防跨主题污染）。"""
    return NEWS_CORE_ENTITIES.get(news_id, set())


def _simple_relevance_score(claim: str, title: str, summary: str, news_id: int = 0) -> float:
    """
    相关性打分：核心实体命中率 + 通用词辅助加权。
    核心实体必须至少命中 1 个，否则大幅降分（防止"新规""改革"等通用词拉入无关文章）。
    """
    text = title + summary

    # 核心实体提取（仅用预定义的，不做自动提取防止跨主题污染）
    core_entities = _get_core_entities(news_id)
    if not core_entities:
        # 未配置核心实体的新闻，退回旧逻辑
        try:
            import jieba
            claim_words = set(jieba.lcut(claim))
            core_entities = {w for w in claim_words if len(w) >= 2 and w not in GENERIC_TERMS}
        except ImportError:
            core_entities = set(re.findall(r'[一-龥]{2,6}', claim))
        if not core_entities:
            return 0.5

    # 核心实体强制匹配：一个都没命中 → 基本不相关
    core_hits = sum(1 for ent in core_entities if ent in text)
    if core_hits == 0:
        return 0.08  # 远低于 0.25 的门槛，后续被过滤

    # 尝试用 jieba 算全词命中率
    try:
        import jieba
        claim_words = set(jieba.lcut(claim))
        all_keywords = {w for w in claim_words if len(w) >= 2 and w not in GENERIC_TERMS}
        if not all_keywords:
            all_keywords = core_entities
        text_words = set(jieba.lcut(text))
        generic_hits = sum(1 for kw in all_keywords if kw in text_words)
        generic_ratio = generic_hits / len(all_keywords)
    except ImportError:
        # 退化：trigram
        a = re.sub(r"\s+", "", claim)
        b = re.sub(r"\s+", "", text)
        if len(a) < 3 or len(b) < 3:
            generic_ratio = 0.4
        else:
            trigrams_a = {a[i:i+3] for i in range(len(a) - 2)}
            trigrams_b = {b[i:i+3] for i in range(len(b) - 2)}
            if not trigrams_a or not trigrams_b:
                generic_ratio = 0.4
            else:
                intersection = len(trigrams_a & trigrams_b)
                union = len(trigrams_a | trigrams_b)
                generic_ratio = intersection / union if union > 0 else 0.4

    # 综合：核心实体命中分数（主导）+ 通用词覆盖率（辅助）
    core_ratio = min(1.0, core_hits / max(3, len(core_entities) * 0.4))
    score = 0.7 * core_ratio + 0.3 * generic_ratio

    return round(score, 3)


def _simple_freshness_score(date_str: str) -> float:
    """
    简化的时效性打分（0-1）。
    不需要精确日期解析，能容错各种格式。
    """
    if not date_str:
        return 0.3  # 无日期默认中等

    try:
        # 尝试 ISO 格式
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        # 尝试中文日期格式
        cn_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
        if cn_match:
            try:
                d = date(int(cn_match.group(1)), int(cn_match.group(2)), int(cn_match.group(3)))
            except ValueError:
                return 0.3
        else:
            # 只提取到了年份
            year_match = re.search(r'(20\d{2})', date_str)
            if year_match:
                year = int(year_match.group(1))
                if year >= 2026:
                    return 0.7
                elif year >= 2025:
                    return 0.5
                elif year >= 2024:
                    return 0.3
                else:
                    return 0.1
            return 0.3

    age_days = max(0, (date.today() - d).days)
    if age_days <= 7:
        return 1.0
    elif age_days <= 30:
        return 0.85
    elif age_days <= 90:
        return 0.6
    elif age_days <= 180:
        return 0.4
    elif age_days <= 365:
        return 0.25
    else:
        return 0.1


def _simple_authority_bonus(url: str, source: str) -> float:
    """权威来源评分（0-0.3）。权威性作为相关性之后的第二筛选维度。"""
    bonus = 0.0
    text = (url + " " + source).lower()

    # Tier 1: 政府/官方辟谣/国家级媒体 → +0.3
    tier1_domains = [
        "gov.cn", "piyao.org.cn",
    ]
    tier1_names = ["新华社", "人民日报", "央视", "cctv"]
    if any(d in text for d in tier1_domains) or any(n in text for n in tier1_names):
        bonus += 0.3

    # Tier 2: 主流媒体/地方官媒 → +0.2
    tier2_domains = [
        "xinhuanet.com", "people.com.cn", "chinanews.com", "gmw.cn",
        "youth.cn", "cnr.cn", "china.com.cn",
    ]
    tier2_names = [
        "澎湃", "新京报", "界面新闻", "财新", "南方周末",
        "光明日报", "经济日报", "法制日报", "中国青年报",
        "新华网", "人民网", "中新网", "环球网", "中国网",
    ]
    if any(d in text for d in tier2_domains) or any(n in text for n in tier2_names):
        bonus += 0.2

    # Tier 3: 地方媒体/商业媒体 → +0.1
    tier3_names = [
        "腾讯", "网易", "新浪", "搜狐", "凤凰", "第一财经",
        "每日经济新闻", "21世纪", "经济观察",
    ]
    if any(n in text for n in tier3_names):
        bonus += 0.1

    return min(bonus, 0.3)


# ==================== 放宽版搜索（直接调 Bocha） ====================

async def _search_bocha_relaxed(
    query: str, client: httpx.AsyncClient, news_id: int = 0, min_relevance: float = 0.10
) -> List[Dict]:
    """
    直接调用 Bocha API，放宽相关性过滤。
    不做线上核查的严格权威性/同质化/猜测过滤。
    news_id 用于加载预定义的核心实体词，防止无关文章混入。
    """
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
            source = item.get("siteName", "") or _extract_domain_simple(result_url)

            # 放宽相关性判定（核心实体未命中则直接给 0.08，远低于门槛）
            rel_score = _simple_relevance_score(query, title, summary, news_id)
            if rel_score < min_relevance:
                continue

            # 简单时效性打分
            fresh_score = _simple_freshness_score(date_str)

            # 权威性加分
            auth_bonus = _simple_authority_bonus(result_url, source)

            # 综合分数：相关性主导，权威+时效做档内区分
            # 相关性占 60%，权威 25%，时效 15%
            combined = 0.6 * rel_score + 0.25 * fresh_score + 0.15 * auth_bonus

            results.append({
                "name": title,
                "url": result_url,
                "summary": summary,
                "date_published": date_str,
                "source": source,
                "_rel_score": round(rel_score, 3),
                "_fresh_score": round(fresh_score, 3),
                "_auth_bonus": round(auth_bonus, 3),
                "_combined": round(combined, 3),
            })

        print(f"    Bocha '{query[:40]}...' -> {len(webpages)} raw, {len(results)} relevant (min_rel=0.10)")
    except Exception as e:
        print(f"    ⚠️  Bocha 请求异常: {e}")

    return results


async def search_evidence_relaxed(claim: str, news_id: int = 0) -> Tuple[List[Dict], List[Dict]]:
    """
    放宽版搜索：生成多个查询，并行调 Bocha，合并去重。
    不经过 _select_core_evidence 等严格质量门。
    news_id 用于加载预定义核心实体词。

    Returns (all_results, core_results)
    """
    # 生成查询（复用线上搜索的关键词提取逻辑）
    queries = []
    core_q = _extract_core_query(claim)
    if core_q:
        queries.append(core_q)

    if len(claim) > 30:
        queries.append(claim[:200])

    simplified = _simplify_claim_for_search(claim)
    if simplified and simplified not in queries:
        queries.append(simplified)

    # 补充搜索：半真半假新闻搜索真实背景事实
    supp_queries = NEWS_SUPPLEMENTARY_QUERIES.get(news_id, [])
    for sq in supp_queries:
        if sq not in queries:
            queries.append(sq)

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
            results = await _search_bocha_relaxed(q, client, news_id=news_id, min_relevance=0.10)
            all_raw.extend(results)
            await asyncio.sleep(0.3)  # 小延迟避免频率限制

    # URL 去重
    seen_urls = set()
    all_results = []
    for r in all_raw:
        url = r["url"]
        if url not in seen_urls:
            seen_urls.add(url)
            all_results.append(r)

    # 按综合分数降序排列（相关性主导：0.6×rel + 0.25×fresh + 0.15×auth）
    all_results.sort(key=lambda x: x.get("_combined", 0), reverse=True)

    # 垃圾信源黑名单：Q&A聚合站、范文模板、技术论坛、游戏门户等非新闻源
    # 匹配来源名称（中文）或 URL 域名
    _GARBAGE_SOURCE_PATTERNS = [
        # URL域名
        "php.cn", "laixuela.com", "qqpk.cn", "fanwen118.com",
        "17173.com", "jjsx.com.cn", "jinchutou.com", "renrendoc.com",
        "doc88.com", "docin.com", "max.book118.com", "taodocs.com",
        "360docs.net", "zhixuedoc.com", "ruiwen.com",
        "pincai.com", "wjx.cn", "zhuangpeitu.com", "tuwangwang.com",
        # 中文来源名
        "苏珊文章", "php中文网", "laixuela", "环球知识网", "范文118",
        "17173新闻中心", "豆丁网", "道客巴巴", "原创力文档", "淘豆网",
        "金锄头文库", "人人文库", "360文档下载中心", "知学网",
        "图旺旺", "库拉索芦荟网", "文档下载网", "装配图网",
        "范文迷", "美文阅读网", "聘才网", "作业答案网",
        "酷米网", "妙百科", "有奖之家网", "草柴", "卡饭网",
        "87G手游网", "游民星空", "游戏爱好者", "乐单机",
        "iu9软件商店", "软件学堂下载站", "多特软件站", "多特资讯网",
        "威客牛", "卖家网", "u客直谈", "同城生活服务系统",
        "八字网", "第一时讯", "源码中国",
    ]

    # 权威来源名（白名单，即使域名像自媒体也保留）
    _AUTHORITATIVE_SOURCES = {
        "中国政府网", "中国网", "中国经济网", "人民网", "央视网",
        "新华网", "光明网", "澎湃新闻", "界面新闻", "新京报",
        "中国互联网联合辟谣平台", "科普中国", "科普中国网",
        "半月谈", "中工网", "民主与法制网", "中国新闻网",
        "环球网", "参考消息", "南方周末", "财新网", "第一财经",
    }

    def _is_garbage_source(item: dict) -> bool:
        src = (item.get("domain", "") or "").lower()
        url = (item.get("url", "") or "").lower()
        # 白名单：权威来源保留
        if any(auth.lower() in src for auth in _AUTHORITATIVE_SOURCES):
            return False
        return any(p.lower() in src or p.lower() in url for p in _GARBAGE_SOURCE_PATTERNS)

    garbage_count = sum(1 for r in all_results if _is_garbage_source(r))
    if garbage_count > 0:
        all_results = [r for r in all_results if not _is_garbage_source(r)]
        print(f"    垃圾信源过滤: 移除 {garbage_count} 条低权威/非新闻来源")

    # 核心证据筛选：相关性门槛 + 权威/时效排序
    # 1. 相关性 < 0.25 的弱相关结果不入核心证据（避免新闻5那种"疲劳驾驶新规"混入"医生值班"）
    CORE_MIN_RELEVANCE = 0.25
    core_candidates = [r for r in all_results if r["_rel_score"] >= CORE_MIN_RELEVANCE]
    dropped = len(all_results) - len(core_candidates)
    if dropped > 0:
        print(f"    相关性过滤: {len(all_results)} → {len(core_candidates)} (移除 {dropped} 条弱相关结果, min_rel={CORE_MIN_RELEVANCE})")

    # 2. 取综合分数最高的前 N 条
    top_n = min(len(core_candidates), CORE_EVIDENCE_LIMIT)
    core_results = core_candidates[:top_n]

    print(f"    总结果: {len(all_results)} 条, 核心证据: {len(core_results)} 条")

    return all_results, core_results


# ==================== 核心逻辑 ====================

async def precompute_one(news: dict, dry_run: bool = False, force: bool = False, group: str = "A") -> Optional[Dict]:
    """预计算单条新闻。group='A' 用结构化 prompt，group='B' 用对话式 prompt。"""
    news_id = news["news_id"]
    title = news["title"]
    body = news["body"]
    claim = news["claim"]

    print(f"\n{'='*60}")
    print(f"📰 [{'B组-对话' if group == 'B' else 'A组-结构化'}] 新闻 {news_id}: {title}")
    print(f"{'='*60}")

    # 检查已有缓存
    existing = _load_cache(news_id, group)
    if existing and not force:
        print(f"  ⏭️  已有缓存 (预计算时间: {existing.get('precomputed_at', '未知')})，跳过")
        ec = existing.get("evidence_chain", {})
        print(f"  📊 搜索结果: {existing.get('search_count', 0)} 条, 核心证据: {existing.get('core_count', 0)} 条")
        print(f"  🏷️  结论: {ec.get('verdict', 'N/A')}")
        s = len(ec.get("supporting_evidence", []))
        o = len(ec.get("opposing_evidence", []))
        n = len(ec.get("neutral_evidence", []))
        print(f"     支持: {s}, 反对: {o}, 中立: {n}")
        if group == "B":
            print(f"  💬 对话回复: {existing.get('assistant_reply', '')[:100]}...")
        return existing

    t0 = time.monotonic()

    # Step 1: 放宽版搜索
    print(f"  🔍 正在搜索 (放宽模式: min_relevance=0.10, 综合打分=0.5×相关+0.3×时效+0.2×权威)...")
    all_search_dicts, core_dicts = await search_evidence_relaxed(claim, news_id=news_id)

    if not all_search_dicts:
        print(f"  ❌ 未找到任何相关搜索结果")
        return None

    print(f"  ✅ 搜索完成: {len(all_search_dicts)} 条全部结果, {len(core_dicts)} 条核心证据")

    # 打印 Top 5 证据得分
    print(f"  📊 核心证据 Top 5 得分:")
    for i, r in enumerate(core_dicts[:5]):
        print(f"     [{i+1}] rel={r['_rel_score']:.2f} fresh={r['_fresh_score']:.2f} "
              f"auth={r['_auth_bonus']:.2f} combined={r['_combined']:.2f} | {r['name'][:60]}...")

    if dry_run:
        print(f"\n  📋 搜索结果预览 (Top 10):")
        for i, r in enumerate(core_dicts[:10]):
            print(f"     [{i+1}] {r['name'][:60]}...")
            print(f"         {r['url']}")
            print(f"         {r['summary'][:120]}...")
            print(f"         相关={r['_rel_score']:.2f} 时效={r['_fresh_score']:.2f} "
                  f"权威={r['_auth_bonus']:.2f} 综合={r['_combined']:.2f}")
            print(f"         日期: {r.get('date_published', 'N/A')}, 来源: {r.get('source', 'N/A')}")
        print(f"\n  🏁 Dry-run 完成（未调用 LLM）")
        return None

    # Step 2: 构造 Prompt（A 组结构化 / B 组对话式）
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

    if group == "B":
        prompt = build_assistant_llm_prompt(claim, core_results_obj)
    else:
        prompt = build_llm_prompt(claim, core_results_obj)
    print(f"  📝 Prompt [{group}组] 长度: {len(prompt)} 字符")

    # Step 3: LLM 调用（A组带质量校验+自动重试）
    print(f"  🤖 正在调用 LLM ({config.LLM_MODEL})...")
    from openai import AsyncOpenAI
    llm_client = AsyncOpenAI(
        api_key=config.LLM_API_KEY,
        base_url=config.LLM_BASE_URL,
    )

    LLM_MAX_RETRIES = 2  # A组最多额外重试2次（共3次调用）
    full_content = ""
    thinking_content = ""

    for llm_attempt in range(1 + LLM_MAX_RETRIES):
        response = await llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3 + (llm_attempt * 0.15),  # 重试时逐渐提高温度以增加多样性
            max_tokens=3000,
            stream=False,
        )

        message = response.choices[0].message
        full_content = message.content or ""
        thinking_content = getattr(message, "reasoning_content", None) or ""

        if not full_content and thinking_content:
            full_content = thinking_content

        # A组质量校验：必须包含所有5个章节标记
        if group != "B":
            sections_found = []
            for section_num in [1, 2, 3, 4, 5]:
                if re.search(rf'###\s*{section_num}[\.、]', full_content):
                    sections_found.append(section_num)

            missing_sections = [s for s in [1, 2, 3, 4, 5] if s not in sections_found]
            content_len = len(full_content)

            if missing_sections:
                if llm_attempt < LLM_MAX_RETRIES:
                    print(f"  ⚠️ LLM 输出不完整（缺少第{missing_sections}节，共{content_len}字符），"
                          f"正在重试 ({llm_attempt + 2}/{1 + LLM_MAX_RETRIES})...")
                    continue  # 重试
                else:
                    print(f"  ❌ LLM 重试{LLM_MAX_RETRIES}次后仍不完整（缺少第{missing_sections}节，"
                          f"共{content_len}字符），使用最后一次结果")
            else:
                print(f"  ✅ LLM 输出通过质量校验：包含全部5节，共{content_len}字符")
                break  # 通过校验，退出重试循环
        else:
            break  # B组不做结构校验

    if group == "B":
        # B 组：对话式回复就是 assistant_reply，不做 preamble 清理（保留自然语气）
        assistant_reply = full_content
        # B 组 LLM 回复不包含结构化立场，传给证据链也提取不到什么，
        # 但仍需传递以便证据链卡片生成
        formatted_content = full_content
    else:
        assistant_reply = ""
        formatted_content = sanitize_model_preamble(
            _normalize_core_evidence_count_text(full_content, len(core_results_obj))
        )

    print(f"  📊 最终 LLM 响应: {len(full_content)} 字符, thinking: {len(thinking_content)} 字符")
    print(f"  📄 LLM 前 200 字: {full_content[:200]}...")

    # Step 4: 证据链/对话回复处理
    claim_truth_type = NEWS_TRUTH_TYPES.get(news_id, "true")

    if group == "B":
        # B 组：对话式回复，跳过证据链生成（无结构化立场可提取）
        # 直接用 LLM 对话回复作为内容，避免无意义的 stance 提取和二次 LLM 调用
        print(f"  💬 B组对话模式，跳过证据链生成")

        all_search_results_dicts = [
            {"title": r.name, "url": r.url, "domain": r.source or _extract_domain(r.url)}
            for r in all_results_obj
        ]

        _VERDICT_BY_TRUTH = {"true": "属实", "semi_true": "部分不实，存在争议", "false": "不实"}
        verdict = _VERDICT_BY_TRUTH.get(claim_truth_type, "无法判断")

        # 用对话回复直接作为 ai_summary（不需要二次 LLM 调用）
        ai_summary = {
            "full": full_content,
            "brief": full_content if len(full_content) <= 400 else full_content[:397] + "...",
            "retry_info": None,
        }

        # 构建精简证据链（仅 verdict + all_search_results，无立场分类）
        evidence_chain_dict = {
            "verdict": verdict,
            "supporting_evidence": [],
            "opposing_evidence": [],
            "neutral_evidence": [],
            "total_evidence": len(core_results_obj),
            "total_search_results": len(all_search_dicts),
            "reasoning_summary": "",
            "ai_summary": ai_summary,
            "all_search_results": all_search_results_dicts,
        }

        print(f"  ✅ 结论: {verdict}")
    else:
        # A 组：完整证据链生成（结构化立场提取）
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
            reasoning_text=formatted_content,
            total_search_results=len(all_search_dicts),
            all_search_results=all_search_results_dicts,
            claim_truth_type=claim_truth_type,
        )

        print(f"  ✅ 证据链: {evidence_chain.verdict}")
        print(f"     支持: {len(evidence_chain.supporting_evidence)}, "
              f"反对: {len(evidence_chain.opposing_evidence)}, "
              f"中立: {len(evidence_chain.neutral_evidence)}")

        evidence_chain_dict = {
            "verdict": evidence_chain.verdict,
            "supporting_evidence": evidence_chain.supporting_evidence,
            "opposing_evidence": evidence_chain.opposing_evidence,
            "neutral_evidence": evidence_chain.neutral_evidence,
            "total_evidence": evidence_chain.total_evidence,
            "total_search_results": evidence_chain.total_search_results,
            "reasoning_summary": evidence_chain.reasoning_summary,
            "ai_summary": evidence_chain.ai_summary,
            "all_search_results": getattr(evidence_chain, "all_search_results", []),
        }

    # Step 5: 组装缓存
    cache_data = {
        "news_id": news_id,
        "group": group,
        "claim": claim,
        "claim_fingerprint": _build_fingerprint(claim),
        "precomputed_at": datetime.now(dt_timezone.utc).isoformat(),
        "search_count": len(all_search_dicts),
        "core_count": len(core_results_obj),
        "thinking_content": thinking_content,
        "full_content": full_content,
        "assistant_reply": assistant_reply,
        "evidence_chain": evidence_chain_dict,
    }

    _save_cache(news_id, cache_data, title, body, group)
    elapsed = time.monotonic() - t0
    print(f"  ⏱️  总耗时: {elapsed:.1f}s")
    return cache_data


async def main():
    parser = argparse.ArgumentParser(description="预计算实验新闻核查结果（放宽版 v2.0）")
    parser.add_argument("--news-id", type=int, choices=range(1, 7), help="仅预计算指定新闻")
    parser.add_argument("--dry-run", action="store_true", help="仅搜索 + 打分，不调用 LLM")
    parser.add_argument("--force", action="store_true", help="强制重新计算，忽略已有缓存")
    parser.add_argument("--group", type=str, choices=["A", "B"], default="A",
                        help="实验组别: A=结构化分析, B=对话助手 (默认 A)")
    args = parser.parse_args()
    group = args.group

    items = NEWS_ITEMS
    if args.news_id:
        items = [n for n in NEWS_ITEMS if n["news_id"] == args.news_id]

    print(f"🚀 预计算脚本启动 (v2.0 放宽版)")
    print(f"   LLM: {config.LLM_MODEL}")
    print(f"   LLM Base URL: {config.LLM_BASE_URL}")
    print(f"   Bocha API: {config.BOCHA_BASE_URL}")
    print(f"   实验组别: {group}组{' (对话助手)' if group == 'B' else ' (结构化分析)'}")
    print(f"   缓存目录: {_get_cache_dir(group)}")
    print(f"   筛选策略: 核心实体匹配 + 综合打分 (0.6×相关 + 0.25×时效 + 0.15×权威)")
    print(f"   模式: {'Dry-run (仅搜索+打分)' if args.dry_run else '完整计算 (搜索+LLM+证据链)'}")
    print(f"   新闻数量: {len(items)}")

    results = []
    for item in items:
        try:
            result = await precompute_one(item, dry_run=args.dry_run, force=args.force, group=group)
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
        print(f"  新闻 {news_id}: title_fp={_build_fingerprint(title)}, "
              f"body_fp={_build_fingerprint(body)}, full_fp={_build_fingerprint(claim)}")


if __name__ == "__main__":
    asyncio.run(main())
