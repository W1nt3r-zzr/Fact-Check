"""
Web search via Zhipu AI + Tavily (parallel multi-engine).
"""
import asyncio
import re
from datetime import datetime, date
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from config import config, logger
from models import SearchResult


@dataclass(frozen=True)
class SearchPlanItem:
    query: str
    recency_filter: Optional[str] = None


@dataclass(frozen=True)
class SearchFetchResult:
    items: List[SearchResult]
    estimated_total: Optional[int] = None


@dataclass(frozen=True)
class SearchRunResult:
    items: List[SearchResult]
    auth_failures: int = 0
    other_failures: int = 0


class SearchProviderError(Exception):
    """Raised when a search provider fails before returning usable results."""

    def __init__(self, provider: str, message: str, status_code: Optional[int] = None, auth_error: bool = False):
        self.provider = provider
        self.status_code = status_code
        self.auth_error = auth_error
        super().__init__(message)


class SearchServiceError(Exception):
    """Raised when all configured search providers are unavailable."""


def _log_query_diagnostics(
    source: str,
    query: str,
    recency_filter: Optional[str],
    estimated_total: Optional[int],
    raw_count: int,
    dedup_count: int,
    filtered_count: int,
    cumulative_count: int,
):
    logger.info(
        "search_diagnostics "
        f"source={source} "
        f"query={query[:80]} "
        f"recency={recency_filter or 'none'} "
        f"estimated_total={estimated_total if estimated_total is not None else 'unknown'} "
        f"raw={raw_count} "
        f"dedup={dedup_count} "
        f"filtered={filtered_count} "
        f"cumulative={cumulative_count}"
    )


from utils.text import STOP_WORDS, FRAME_WORDS
from utils.url import extract_source_from_url

# ==================== 查询提炼 ====================


def _extract_core_query(claim: str) -> str:
    """
    从待核查说法中提炼搜索关键词：
    - 移除框架词（"是真的吗""据说"等）
    - 提取核心实体（人名/机构/数字/事件词）
    - 长句截取核心片段，保持精简
    """
    text = claim.strip()

    # 0. 移除搜索后缀噪声（用户从搜索结果页选中文本时带入）
    text = re.sub(r'\s*[-–—]\s*搜索\s*$', '', text)
    text = re.sub(r'\s*[-–—]\s*必应\s*$', '', text)
    text = re.sub(r'\s*[-–—]\s*(百度|Google|Bing)\s*$', '', text)
    text = re.sub(r'\s*[_|]\s*(搜索|Search).*$', '', text, flags=re.IGNORECASE)
    text = text.strip()

    # 1. 移除事实核查框架词
    for fw in sorted(FRAME_WORDS, key=len, reverse=True):
        text = text.replace(fw, '')
    text = text.strip()

    # 1.5 去掉会降低召回的时效包裹词和句尾语气词
    text = re.sub(r'^(今天|今日|昨天|昨日|刚刚|目前|现在)', '', text).strip()
    text = re.sub(r'(了吗|吗|呢|吧|啊|呀|了)$', '', text).strip()

    # 2. 如果提炼后足够短（<=20字），直接用
    clean_len = len(text.replace('，', '').replace('。', '').replace('？', '').replace('！', ''))
    if clean_len <= 20:
        return text

    # 3. 长句：提取高价值片段
    # 3a. 提取数字+单位组合（保留原样，如"7.7级""万亿""2026年4月"）
    number_entities = re.findall(r'\d+\.?\d*[万亿千百%％指数点级倍年月日人次]*[一-鿿]?', text)

    # 3b. 提取中文关键词（2-6字，去停用词）
    chinese_segments = re.findall(r'[一-鿿A-Za-z0-9]{2,10}', text)
    keywords = [seg for seg in chinese_segments if seg not in STOP_WORDS and len(seg) >= 2]

    # 3c. 按标点分割，取信息密度最高的片段
    clauses = re.split(r'[，,。.！!？?；;：:、\s]+', text)
    clauses = [c.strip() for c in clauses if len(c.strip()) >= 3 and c.strip() not in STOP_WORDS]
    # 按信息密度排序（含数字/专有名词的优先）
    def clause_score(c):
        score = 0
        if re.search(r'\d', c): score += 3  # 含数字
        if re.search(r'[一-鿿]{2,}', c): score += 2  # 含中文实体
        if len(c) >= 4: score += 1  # 足够长
        return score
    clauses.sort(key=clause_score, reverse=True)

    # 3d. 组合：取信息密度最高的片段 + 关键数字实体
    parts = []
    for c in clauses[:2]:  # 最多2个核心片段
        if c not in parts:
            parts.append(c)

    for ne in number_entities:
        if ne and not any(ne in p for p in parts):
            parts.append(ne)
            break  # 只补一个数字实体

    result = ' '.join(parts) if parts else text[:30]

    logger.info(f"提炼搜索查询: '{claim}' -> '{result}'")
    return result


def _is_recent_claim(claim: str) -> bool:
    explicit_recency = [
        '今天', '今日', '昨天', '昨日', '前天',
        '近两日', '近两天', '这两天', '最近', '最新',
        '本周', '上周', '本月', '上个月',
        '刚刚', '刚刚发生', '刚刚公布', '今年', '本年度',
    ]
    if any(kw in claim for kw in explicit_recency):
        return True
    return (
        bool(re.search(r'[近这][几两三四五][日天周月]', claim))
        or _is_event_claim(claim)
        or _is_time_sensitive_claim(claim)
    )


def _is_event_claim(claim: str) -> bool:
    """识别新闻/监管/动态事实类说法，即使没有显式时间词也应优先近期证据。"""
    event_terms = [
        '被约谈', '约谈', '通报', '处罚', '罚款', '立案', '调查', '召回',
        '下架', '整改', '封禁', '回应', '辟谣', '发生',
        '爆发', '起火', '爆炸', '事故', '涨价', '降价', '停产', '停业',
        '闭园', '停运', '破产', '收购', '上市', '退市', '曝光',
        '起诉', '公诉', '开庭', '宣判', '判决', '判刑', '被判', '裁定',
        '终审', '定谳', '上诉', '驳回', '不起诉', '无罪', '获刑', '缓刑',
    ]
    if any(term in claim for term in event_terms):
        return True

    # "宣布/发布" 类动词：仅当其后跟随的内容是正在发生或刚刚发生的变化（而非
    # 已存在的稳定制度/政策/安排）时才标记为事件。避免把"国务院宣布放假安排"
    # 这类政策公告误判为需要 freshness 优先的突发新闻，导致官方原始公告因超
    # 45 天时间窗口被 stale 过滤掉。
    if _contains_dynamic_announcement(claim):
        return True

    # 未命中显式事件词也非动态宣告的 claim：默认按新闻性判断，但排除
    # 含"宣布/发布"的正式公告类（它们已在 _contains_dynamic_announcement
    # 的白名单中被排除），避免"国务院宣布放假"被 stale 过滤。
    if _has_formal_announcement_verb(claim):
        return False

    return not _is_stable_science_or_common_claim(claim)


def _has_formal_announcement_verb(claim: str) -> bool:
    """检查 claim 是否包含"宣布/发布"且不构成动态事件。
    与 _contains_dynamic_announcement 互补：后者检查是否为动态事件，
    本函数检查是否为正式公告（应排除的）。"""
    announcement_verbs = {'宣布', '发布'}
    return any(verb in claim for verb in announcement_verbs)


def _contains_dynamic_announcement(claim: str) -> bool:
    """判断 claim 中"宣布/发布"是否为动态事件（如"宣布取消航班"、"发布
    辟谣声明"），而非制度/政策/产品类的正式公告（如"国务院宣布放假安排"、
    "苹果发布新手机"）。

    区分逻辑：如果"宣布/发布"后出现表示稳定状态、长期制度或产品名词的标志
    词，则视为正式公告而非动态事件。正式公告的核心价值在于其内容本身，而非
    动作发生的时点，因此不应享受 freshness 优先级。
    """
    announcement_verbs = {'宣布', '发布'}
    if not any(verb in claim for verb in announcement_verbs):
        return False

    # 制度/政策/安排/产品类静态名词：公告后长期有效，不因时间流逝而失效
    static_subject_nouns = {
        '安排', '方案', '政策', '规定', '通知', '公告', '计划', '规划',
        '目标', '标准', '条例', '办法', '法规', '法律', '制度', '规则',
        '假期', '节假日', '放假', '调休', '作息', '假期安排', '节假日安排',
        '养老金', '税率', '利率', '汇率', '补贴', '救助',
        '产品', '新机', '手机', '发布会', '版', '款',
        '考试', '招生', '分数线', '录取', '名额',
        '预算', '投资', '贷款', '融资',
        '配方', '成分', '标准号', '国标', '行标',
        '任命', '任免', '换届', '当选',
    }
    for noun in static_subject_nouns:
        if noun in claim:
            return False

    # 政府/企业主体 + 宣布/发布 → 大概率是正式公告
    # 这些模式也作为白名单匹配，表示公告性质而非突发事件
    formal_publisher_patterns = [
        r'国务院宣布', r'国务院发布',
        r'教育部宣布', r'教育部发布',
        r'工信部宣布', r'工信部发布',
        r'央行宣布', r'央行发布', r'人民银行宣布', r'人民银行发布',
        r'交通部宣布', r'交通部发布', r'交通运输部宣布', r'交通运输部发布',
        r'卫健委宣布', r'卫健委发布',
        r'人社部宣布', r'人社部发布',
        r'最高法宣布', r'最高法发布', r'最高法院宣布', r'最高法院发布',
        r'最高检宣布', r'最高检发布',
        r'外交部宣布', r'外交部发布',
        r'商务部宣布', r'商务部发布',
        r'财政部宣布', r'财政部发布',
        r'发改委宣布', r'发改委发布',
        r'证监会宣布', r'证监会发布',
        r'银保监会宣布', r'银保监会发布',
        r'税务总局宣布', r'税务总局发布',
        r'海关总署宣布', r'海关总署发布',
        r'市场监管总局宣布', r'市场监管总局发布',
        r'国家药监局宣布', r'国家药监局发布', r'药监局宣布', r'药监局发布',
        r'国家医保局宣布', r'国家医保局发布',
        r'自然资源部宣布', r'自然资源部发布',
        r'生态环境部宣布', r'生态环境部发布',
        r'农业农村部宣布', r'农业农村部发布',
        r'文化和旅游部宣布', r'文化和旅游部发布',
        r'网信办宣布', r'网信办发布', r'中央网信办宣布', r'中央网信办发布',
        r'省(?:政府|卫健委|教育厅)宣布', r'省(?:政府|卫健委|教育厅)发布',
        r'市(?:政府|卫健委|教育局)宣布', r'市(?:政府|卫健委|教育局)发布',
        r'官方宣布', r'官方发布',
        r'新闻联播宣布', r'新闻联播发布',
        r'央视宣布', r'央视发布', r'中央电视台宣布', r'中央电视台发布',
        r'经国务院批准', r'经全国人大', r'经中央批准',
        r'苹果发布', r'华为发布', r'特斯拉发布', r'腾讯发布', r'阿里发布', r'字节发布',
    ]
    for pattern in formal_publisher_patterns:
        if re.search(pattern, claim):
            return False

    # 没有命中上述白名单的"宣布/发布"才视为动态事件
    return True


def _is_stable_science_or_common_claim(claim: str) -> bool:
    """识别不应默认套近期新闻窗口的权威科学、健康、法规解释或常识类问题。"""
    if _is_authority_claim(claim):
        return True

    common_terms = [
        '太阳', '月亮', '地球', '水', '冰', '结冰', '沸腾', '沸点', '蒸发',
        '光速', '重力', '引力', '温度', '密度', '声音', '光合作用',
    ]
    common_question_terms = ['为什么', '是什么', '原理', '会不会', '能不能', '能否', '是否', '吗', '呢']
    has_common_subject = any(term in claim for term in common_terms)
    has_common_question = any(term in claim for term in common_question_terms)
    return has_common_subject and has_common_question


def _is_time_sensitive_claim(claim: str) -> bool:
    """识别价格、收费、售卖状态等容易随时间变化的说法。"""
    price_terms = [
        '价格', '售价', '卖', '只卖', '售卖', '售', '收费', '票价', '门票',
        '涨价', '降价', '元', '块钱', '一瓶', '一杯', '一张',
    ]
    place_or_supply_terms = [
        '景区', '山顶', '店', '超市', '机场', '车站', '服务区', '摊位',
        '矿泉水', '饮料', '商品', '供应', '售罄', '缺货',
    ]
    has_price_signal = any(term in claim for term in price_terms) or bool(re.search(r'\d+\.?\d*\s*(元|块)', claim))
    has_context_signal = any(term in claim for term in place_or_supply_terms)
    return has_price_signal and has_context_signal


BACKGROUND_EVENT_TEMPLATE_QUERIES = {
    "disclosure_case": [
        "重案解密 {base}",
        "{base} 披露",
        "{base} 案情回顾",
        "{base} 旧案",
    ],
    "case_progress": [
        "{base} 最新进展",
        "{base} 案情回顾",
        "{base} 时间线",
    ],
    "rumor_response": [
        "{base} 官方回应",
        "网传 {base}",
        "{base} 传闻 来源",
    ],
    "old_news_resurface": [
        "{base} 旧闻新传",
        "{base} 辟谣",
        "{base} 原始报道",
    ],
}


def _detect_background_event_template(claim: str) -> Optional[str]:
    """识别新闻点和背景事实分属不同时间层的事件模板。"""
    text = claim or ''
    if _is_disclosure_case_claim(text):
        return "disclosure_case"

    case_terms = ['案', '案件', '命案', '凶案', '事故', '事件']
    progress_terms = ['最新进展', '新进展', '有进展', '进展', '后续', '进展如何', '时间线']
    if any(term in text for term in case_terms) and any(term in text for term in progress_terms):
        return "case_progress"

    response_terms = ['回应', '辟谣', '澄清', '否认', '证实', '通报']
    rumor_terms = ['传闻', '网传', '谣言', '传言', '消息称', '爆料']
    if any(term in text for term in response_terms) and any(term in text for term in rumor_terms):
        return "rumor_response"

    old_news_terms = ['旧闻新传', '旧闻', '旧消息', '翻炒', '重新流传', '又传', '再传']
    if any(term in text for term in old_news_terms):
        return "old_news_resurface"

    return None


def _is_disclosure_case_claim(claim: str) -> bool:
    """识别“近期披露/解密旧案”类说法，需同时召回近期披露和旧案背景。"""
    text = claim or ''
    disclosure_terms = [
        '解密', '揭秘', '披露', '公开', '曝光', '出版', '新书', '档案',
        '回顾', '还原', '纪实', '首次披露', '重案解密',
    ]
    case_terms = ['案', '案件', '旧案', '冷案', '重案', '命案', '凶案', '双尸']
    return any(term in text for term in disclosure_terms) and any(term in text for term in case_terms)


def _strip_background_event_terms(text: str) -> str:
    """去掉新闻动作词，保留被报道的背景事实实体用于补召回。"""
    stripped = text or ''
    stripped = re.sub(
        r'(警方|警察|警队|警務處|警务处|官方|新书|出版|首次|首次披露|重案解密|'
        r'解密|揭秘|披露|公开|曝光|档案|回顾|还原|纪实|有最新进展|最新进展|新进展|'
        r'有进展|进展如何|进展|后续|时间线|回应|辟谣|澄清|否认|证实|通报|'
        r'网传|消息称|爆料|为|系|旧闻新传|旧闻|旧消息|'
        r'翻炒|重新流传|又传|再传)',
        '',
        stripped,
    )
    return re.sub(r'\s+', ' ', stripped).strip()


def _build_background_event_queries(claim: str, query: str) -> List[str]:
    """为需要背景层证据的近期事件补充常见标题变体。"""
    template = _detect_background_event_template(claim)
    if not template:
        return []

    base = _strip_background_event_terms(query) or _strip_background_event_terms(claim)
    if not base:
        return []

    candidates = [
        pattern.format(base=base)
        for pattern in BACKGROUND_EVENT_TEMPLATE_QUERIES.get(template, [])
    ]

    # 港澳台及都市新闻常用“豪宅双尸案”等场景化标题，原claim可能只写地名+双尸案。
    compact_base = re.sub(r'\s+', '', base)
    match = re.match(r'(?P<place>[一-龥]{2,8})双尸案$', compact_base)
    if match:
        candidates.append(f"{match.group('place')}豪宅双尸案 解密")

    return [re.sub(r'\s+', ' ', candidate).strip() for candidate in candidates if candidate.strip()]


def _has_background_event_coverage(claim: str, result: SearchResult) -> bool:
    """判断旧结果是否可作为背景层证据，而不是无关旧闻。"""
    template = _detect_background_event_template(claim)
    if not template:
        return False

    base = _strip_background_event_terms(claim)
    if not base:
        return False
    if template == "rumor_response":
        base = re.sub(r'(传闻|谣言|传言)$', '', base).strip() or base

    text = re.sub(r'\s+', '', f"{result.name} {result.summary}")
    compact_base = re.sub(r'\s+', '', base)
    if compact_base and compact_base in text:
        return True

    terms = [
        term for term in re.findall(r'[一-龥A-Za-z0-9]{2,8}', compact_base)
        if term not in STOP_WORDS and term not in ('警方', '解密', '披露', '案件')
    ]
    if not terms:
        return False

    hits = sum(1 for term in set(terms) if term in text)
    if hits >= max(1, min(2, len(set(terms)))):
        return True

    if '双尸案' in compact_base and '双尸案' in text:
        place = compact_base.replace('双尸案', '')
        return bool(place and place in text)

    return False


def _is_bizarre_video_origin_claim(claim: str) -> bool:
    """识别疑似短视频/旧素材换地点传播的离奇事件说法。"""
    text = re.sub(r'\s+', '', claim or '')
    if not text:
        return False

    body_or_scene_terms = ['耳朵', '耳道', '耳内', '嘴里', '鼻子', '身体', '游泳', '浮潜', '海边', '海里']
    animal_or_object_terms = ['螃蟹', '蟹', '虫', '蛇', '鱼', '章鱼', '水母', '异物']
    action_terms = ['爬出', '钻出', '出来', '取出', '进入', '钻进', '掉进']

    return (
        any(term in text for term in body_or_scene_terms)
        and any(term in text for term in animal_or_object_terms)
        and any(term in text for term in action_terms)
    )


def _build_bizarre_video_origin_queries(claim: str, query: str) -> List[str]:
    """为疑似旧视频/跨语种传播的离奇事件补充原始来源查询。"""
    if not _is_bizarre_video_origin_claim(claim):
        return []

    compact = re.sub(r'\s+', '', claim or query or '')
    candidates: List[str] = []

    if '三亚' in compact and '游泳' in compact and ('耳朵' in compact or '耳道' in compact) and ('螃蟹' in compact or '蟹' in compact):
        candidates.extend([
            '三亚 游泳 耳朵 螃蟹',
            '耳朵 螃蟹 游泳 原视频',
            '螃蟹 耳朵 浮潜',
            '厚礼蟹 原视频',
            'crab ear snorkeling',
            'crab crawls out of ear',
            'San Juan Puerto Rico crab ear',
        ])
    else:
        terms = []
        for term in ['耳朵', '耳道', '游泳', '浮潜', '螃蟹', '蟹', '原视频', '旧视频']:
            if term in compact and term not in terms:
                terms.append(term)
        if terms:
            candidates.append(' '.join(terms))
            candidates.append(' '.join([term for term in terms if term not in {'原视频', '旧视频'}] + ['原视频']))

    return [re.sub(r'\s+', ' ', candidate).strip() for candidate in candidates if candidate.strip()]


def _has_bizarre_video_origin_coverage(claim: str, result: SearchResult) -> bool:
    """判断旧来源是否覆盖离奇视频 claim 的原始素材背景。"""
    if not _is_bizarre_video_origin_claim(claim):
        return False

    text = re.sub(r'\s+', ' ', f"{result.name} {result.summary}".lower())
    compact = re.sub(r'\s+', '', f"{result.name} {result.summary}")

    if ('螃蟹' in claim or '蟹' in claim) and ('耳朵' in claim or '耳道' in claim):
        chinese_core = ('螃蟹' in compact or '蟹' in compact) and ('耳朵' in compact or '耳道' in compact)
        english_core = 'crab' in text and 'ear' in text
        origin_context = any(term in compact for term in ['原视频', '旧视频', '波多黎各', '圣胡安', '浮潜']) or any(
            term in text for term in ['snorkel', 'snorkeling', 'swim', 'swimming', 'puerto rico', 'san juan', 'original video']
        )
        return (chinese_core or english_core) and origin_context

    return False


def _extract_price_signals(text: str) -> set[str]:
    """提取价格信号，统一去掉空格便于匹配。"""
    compact = re.sub(r'\s+', '', text)
    return set(re.findall(r'\d+\.?\d*(?:元|块钱|块)', compact))


def _extract_time_sensitive_product_terms(claim: str) -> set[str]:
    product_terms = [
        '矿泉水', '饮料', '门票', '票价', '商品', '餐食', '盒饭',
        '咖啡', '奶茶', '水', '票',
    ]
    return {term for term in product_terms if term in claim}


def _extract_time_sensitive_location_terms(claim: str) -> set[str]:
    """从价格状态类claim中提取地点要素，优先保留较具体的地名片段。"""
    suffixes = ('景区', '机场', '车站', '公园', '服务区', '超市', '山顶', '山', '湖', '泉', '城', '店')
    generic_terms = {'山顶', '景区', '机场', '车站', '公园', '服务区', '超市', '门店'}
    candidates: set[str] = set()
    chinese = re.sub(r'[^一-龥]', '', claim)

    for start in range(len(chinese)):
        for end in range(start + 2, min(len(chinese), start + 8) + 1):
            piece = chinese[start:end]
            if piece.endswith(suffixes) and not any(term in piece for term in ('矿泉水', '饮料', '门票', '票价', '商品')):
                candidates.add(piece)

    specific = {term for term in candidates if len(term) >= 3 and term not in generic_terms}

    # 地名常位于具体景点名前，例如“敦煌鸣沙山”中的“敦煌”。
    if not specific and '敦煌' in claim:
        specific.add('敦煌')

    return specific


def _has_time_sensitive_core_coverage(claim: str, result: SearchResult) -> bool:
    """
    价格/售卖状态类证据必须覆盖核心要素：价格、商品、地点。

    软相关性容易让“同一景区但不同收费”或“同一价格但不同地点”的内容混入；
    这类claim如果缺任一核心要素，通常不能作为直接核查证据。
    """
    if not _is_time_sensitive_claim(claim):
        return True

    text = re.sub(r'\s+', '', f"{result.name} {result.summary}")

    price_signals = _extract_price_signals(claim)
    if price_signals and not any(signal in text for signal in price_signals):
        return False

    product_terms = _extract_time_sensitive_product_terms(claim)
    if product_terms and not any(term in text for term in product_terms):
        return False

    location_terms = _extract_time_sensitive_location_terms(claim)
    if location_terms and not any(term in text for term in location_terms):
        return False

    return True


def _is_authority_claim(claim: str) -> bool:
    """识别更依赖权威来源的主题。"""
    authority_terms = [
        '癌', '癌症', '细胞', '疾病', '药', '疫苗', '治疗', '医院', '医生',
        '感染', '病毒', '食品安全', '营养', '保健', '政策', '法规', '法律',
        '标准', '规定', '监管', '许可', '认证',
    ]
    return any(term in claim for term in authority_terms)


def _is_legal_dynamic_claim(claim: str) -> bool:
    """识别案件进展、裁判结果、执法处罚等需要近期司法事实的法律类说法。"""
    legal_subject_terms = [
        '法院', '法庭', '检方', '检察', '检察官', '检察院', '警方', '警局',
        '案件', '案', '判决', '裁定', '审判', '诉讼', '公诉', '起诉',
        '上诉', '终审', '一审', '二审', '定谳', '定讞',
    ]
    legal_action_terms = [
        '起诉', '公诉', '开庭', '宣判', '判决', '判刑', '被判', '裁定',
        '终审', '定谳', '定讞', '上诉', '驳回', '駁回', '维持原判', '維持原判',
        '不起诉', '不起訴', '无罪', '無罪', '获刑', '獲刑', '缓刑', '緩刑',
        '羁押', '羈押', '保释', '保釋', '逮捕', '拘留', '立案', '侦查', '偵查',
    ]
    text = claim or ''
    return any(term in text for term in legal_action_terms) or (
        any(term in text for term in legal_subject_terms) and any(term in text for term in ('结果', '進展', '进展', '最新'))
    )


def _has_legal_resolution_focus(claim: str) -> bool:
    """终局裁判类claim需要结果锚点，不能只用案情回顾作核心证据。"""
    finality_terms = [
        '终审', '定谳', '定讞', '最终判决', '最終判決', '判决确定', '判決確定',
        '全案确定', '全案確定', '驳回上诉', '駁回上訴', '维持原判', '維持原判',
        '最高法院', '不得上诉', '不得上訴',
    ]
    return any(term in (claim or '') for term in finality_terms)


def _has_legal_core_coverage(claim: str, result: SearchResult) -> bool:
    """法律动态证据必须覆盖对应司法动作，避免近期转载的历史背景挤占核心证据。"""
    if not _is_legal_dynamic_claim(claim):
        return True

    text = re.sub(r'\s+', '', f"{result.name} {result.summary}")
    legal_markers = [
        '法院', '法庭', '检方', '檢方', '检察', '檢察', '警方', '警局',
        '起诉', '起訴', '公诉', '公訴', '开庭', '開庭', '宣判', '判决', '判決',
        '判刑', '被判', '裁定', '审理', '審理', '上诉', '上訴', '驳回', '駁回',
        '终审', '終審', '定谳', '定讞', '获刑', '獲刑', '缓刑', '緩刑',
        '不起诉', '不起訴', '无罪', '無罪', '羁押', '羈押', '保释', '保釋',
        '逮捕', '拘留', '立案', '侦查', '偵查',
    ]
    if not any(marker in text for marker in legal_markers):
        return False

    if not _has_legal_resolution_focus(claim):
        return True

    resolution_markers = [
        '最高法院', '终审', '終審', '定谳', '定讞', '最终判决', '最終判決',
        '判决确定', '判決確定', '全案确定', '全案確定', '驳回上诉', '駁回上訴',
        '驳回检方上诉', '駁回檢方上訴', '维持原判', '維持原判',
        '确定', '確定', '不得上诉', '不得上訴',
    ]
    if any(marker in text for marker in resolution_markers):
        return True

    age_days = _age_days(result.date_published)
    return age_days is not None and age_days <= 45


def _detect_search_preference(claim: str) -> str:
    """
    自动判断检索偏好：
    - freshness: 新闻/监管/突发事件，优先近期证据
    - authority: 医学、政策、法律等，优先权威来源
    - relevance: 默认相关性优先
    """
    if _is_event_claim(claim) or _is_recent_claim_without_event(claim) or _is_time_sensitive_claim(claim):
        return "freshness"
    if _is_authority_claim(claim):
        return "authority"
    return "relevance"


def _is_recent_claim_without_event(claim: str) -> bool:
    explicit_recency = [
        '今天', '今日', '昨天', '昨日', '前天',
        '近两日', '近两天', '这两天', '最近', '最新',
        '本周', '上周', '本月', '上个月',
        '刚刚', '刚刚发生', '刚刚公布', '今年', '本年度',
    ]
    if any(kw in claim for kw in explicit_recency):
        return True
    return bool(re.search(r'[近这][几两三四五][日天周月]', claim))


def _build_search_plan(claim: str) -> List[SearchPlanItem]:
    """为单条claim生成多组召回查询，兼顾广召回和精确匹配。"""
    query = _extract_core_query(claim)
    simplified = _simplify_claim_for_search(claim)
    recent = _is_recent_claim(claim)
    month_str = datetime.now().strftime('%Y年%m月')

    plan: List[SearchPlanItem] = []
    seen: set[tuple[str, Optional[str]]] = set()

    def add(query_text: str, recency_filter: Optional[str] = None):
        normalized = query_text.strip()
        if not normalized:
            return
        key = (normalized, recency_filter)
        if key in seen:
            return
        seen.add(key)
        plan.append(SearchPlanItem(query=normalized, recency_filter=recency_filter))

    # 主查询优先宽召回，不默认加引号，也不默认带时间过滤
    add(query)

    # 长句原文常含更多限定条件，作为补充召回
    if len(claim) > 40 and claim.strip() != query:
        add(claim.strip())

    # 简化后的实体查询适合补召回
    if simplified and simplified != query:
        add(simplified)

    # 短句精确匹配保留，但降为补充查询，避免一上来把召回压窄
    clean_len = len(query.replace('，', '').replace('。', '').replace('？', '').replace('！', '').replace(' ', ''))
    if clean_len <= 20:
        add(f'"{query}"')

    # 时效性话题单独追加月级过滤，不再全局强制 year
    if recent:
        add(f"{query} {month_str} 最新消息", "month")
        if simplified and simplified != query:
            add(f"{simplified} {month_str}", "month")

    for background_query in _build_background_event_queries(claim, query):
        add(background_query)
        add(f"{background_query} {month_str}", "month")

    for origin_query in _build_bizarre_video_origin_queries(claim, query):
        add(origin_query)

    if _is_legal_dynamic_claim(claim):
        for legal_query in _build_legal_dynamic_queries(claim, query):
            add(legal_query)
            add(f"{legal_query} {month_str}", "month")

    return plan


def _build_legal_dynamic_queries(claim: str, query: str) -> List[str]:
    """为法律动态说法补充司法报道常用表述，提升跨媒体召回。"""
    base = re.sub(
        r'(终审|終審|定谳|定讞|最终判决|最終判決|判决确定|判決確定|全案确定|全案確定|驳回上诉|駁回上訴|最高法院|三审|第三审|起诉|起訴|公诉|公訴|开庭|開庭|宣判|判决|判決|判刑|被判|裁定|二审|二審|一审|一審|改判|缓刑|緩刑|获刑|獲刑)',
        '',
        query or ''
    )
    base = re.sub(r'\s+', ' ', base).strip()
    if not base:
        base = query.strip()

    text = claim or ''
    candidates = []

    if any(term in text for term in ('起诉', '起訴', '公诉', '公訴')):
        candidates.extend([
            f"{base} 检方 起诉",
            f"{base} 公诉 法院",
            f"{base} 检察 起诉",
        ])

    if any(term in text for term in ('开庭', '開庭', '宣判', '判决', '判決', '判刑', '被判', '裁定', '一审', '一審', '二审', '二審', '改判', '缓刑', '緩刑', '获刑', '獲刑')):
        candidates.extend([
            f"{base} 高院 判决",
            f"{base} 高等法院 宣判",
            f"{base} 判刑 缓刑 上诉",
        ])

    if _has_legal_resolution_focus(claim):
        candidates.extend([
            f"{base} 最高法院 驳回 上诉",
            f"{base} 终审 定谳",
            f"{base} 三审 定讞",
        ])

    return [re.sub(r'\s+', ' ', candidate).strip() for candidate in candidates if candidate.strip()]


def _simplify_claim_for_search(claim: str) -> str:
    """从 claim 中提取核心实体，生成补充搜索查询"""
    text = claim.strip()

    # 清洗搜索后缀噪声
    text = re.sub(r'\s*[-–—]\s*搜索\s*$', '', text)
    text = re.sub(r'\s*[-–—]\s*(必应|百度|Google|Bing)\s*$', '', text)
    text = text.strip()

    # 提取数字实体（如"185万""0糖""2026年"）
    numbers = re.findall(r'\d+\.?\d*[万亿千百%％]*[年月日]?', text)

    # 按标点分段，取最长的2个非停用词片段
    segments = re.split(r'[，,。.！!？?；;：:、\s\n]+', text)
    segments = [s for s in segments if len(s) >= 2 and s not in STOP_WORDS and s not in FRAME_WORDS]

    parts = segments[:2]
    for num in numbers:
        if num and not any(num in p for p in parts):
            parts.append(num)
            break

    if not parts:
        return ''

    simplified = ' '.join(parts)
    return simplified


def _compute_relevance(claim: str, result: SearchResult) -> float:
    """计算搜索结果与待核查内容的相关性得分（0-1）"""
    title = result.name or ''
    summary = result.summary or ''
    text = (title + ' ' + summary).lower()
    claim_lower = claim.lower()

    # 1. 精确短语匹配（最高权重）
    if claim_lower in text:
        return 1.0

    # 2. 从 claim 中提取关键词
    segments = re.split(r'[，,。.！!？?；;：:、\s\n\r\t「」""''【】\[\]()（）\-—…·]+', claim_lower)
    keywords = [seg for seg in segments if len(seg) >= 2 and seg not in STOP_WORDS]

    # 额外提取2字滑动窗口
    clean = re.sub(r'[^一-鿿a-z0-9]', '', claim_lower)
    for i in range(len(clean) - 1):
        seg = clean[i:i+2]
        if seg not in STOP_WORDS and len(seg) == 2:
            keywords.append(seg)

    # 3. 提取数字实体（如"185万""7.7级""2026年"），这些是强相关信号
    claim_numbers = set(re.findall(r'\d+\.?\d*[万亿千百%％]*[年月日]?', claim_lower))
    result_numbers = set(re.findall(r'\d+\.?\d*[万亿千百%％]*[年月日]?', text))

    # 数字不匹配的惩罚
    number_mismatch = 0
    if claim_numbers:
        significant_nums = {n for n in claim_numbers if len(n) >= 2 and re.search(r'\d', n)}
        if significant_nums:
            overlap = significant_nums & result_numbers
            if not overlap:
                number_mismatch = 0.3

    if not keywords:
        return 0.2

    # 计算关键词命中率
    unique_kw = set(keywords)
    hit = sum(1 for kw in unique_kw if kw in text)
    total = len(unique_kw)
    ratio = hit / total if total > 0 else 0

    # 关键短语连续命中加分
    bonus = 0
    for seg in segments:
        if len(seg) >= 3 and seg in text:
            bonus += 0.1
    bonus = min(bonus, 0.3)

    score = min(1.0, ratio * 0.7 + bonus) - number_mismatch

    # 4. 标题相关性门槛：标题与claim关键词几乎无关时大幅降分
    #    防止仅在"相关推荐"/侧边栏中提及claim的无关页面混入
    title_lower = title.lower()
    title_hits = sum(1 for kw in unique_kw if kw in title_lower)
    title_ratio = title_hits / total if total > 0 else 0
    if title_ratio < 0.15 and ratio < 0.5:
        # 标题几乎无关键词命中，且整体命中率也不高 → 大概率是推荐链接提及
        score *= 0.3
        logger.debug(f"标题低相关惩罚: [{title_ratio:.0%}] {title[:50]}")

    return max(0, score)


def _freshness_score(date_published: str) -> float:
    """根据发布日期估算新鲜度分数（0-1）。"""
    if not date_published:
        return 0.0
    try:
        published = datetime.strptime(date_published[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0.0

    age_days = max(0, (date.today() - published).days)
    if age_days <= 3:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 30:
        return 0.6
    if age_days <= 90:
        return 0.35
    if age_days <= 365:
        return 0.15
    return 0.05


def _age_days(date_published: str) -> Optional[int]:
    if not date_published:
        return None
    try:
        published = datetime.strptime(date_published[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return max(0, (date.today() - published).days)


def _extract_years_from_text(text: str) -> set[int]:
    years = set()
    for match in re.findall(r'(?<!\d)(20\d{2})(?=年|[-/.])?', text or ''):
        try:
            years.add(int(match))
        except ValueError:
            continue
    return years


def _is_stale_for_recent_claim(claim: str, result: SearchResult) -> bool:
    """
    对明显近期性、事件类或价格状态类claim，超过时间窗口的旧新闻直接降级处理。
    这些claim核查的是当前状态，统一使用45天窗口，避免把历史相似报道混进核心证据里。
    """
    is_event_or_explicit_recent = _is_recent_claim_without_event(claim) or _is_event_claim(claim)
    is_time_sensitive = _is_time_sensitive_claim(claim)
    if not (is_event_or_explicit_recent or is_time_sensitive):
        return False
    if _has_background_event_coverage(claim, result):
        return False
    if _has_bizarre_video_origin_coverage(claim, result):
        return False
    age_days = _age_days(result.date_published)
    if age_days is None:
        return is_event_or_explicit_recent or is_time_sensitive
    stale_window_days = 45
    text_years = _extract_years_from_text(f"{result.name} {result.summary}")
    current_year = date.today().year
    if text_years and max(text_years) < current_year:
        return True
    return age_days > stale_window_days


def _filter_irrelevant_results(claim: str, results: List[SearchResult], min_relevance: float = 0.2) -> List[SearchResult]:
    """过滤掉与待核查内容明显无关的搜索结果"""
    if not results:
        return results

    recent_claim = _is_recent_claim(claim)
    time_sensitive_claim = _is_time_sensitive_claim(claim)
    scored = []
    for r in results:
        if not _has_time_sensitive_core_coverage(claim, r):
            scored.append((r, 0.0, 0.0, -1.0, True))
            continue
        if not _has_legal_core_coverage(claim, r):
            scored.append((r, 0.0, 0.0, -1.0, True))
            continue
        relevance = _compute_relevance(claim, r)
        if _has_bizarre_video_origin_coverage(claim, r):
            relevance = max(relevance, min_relevance)
        freshness = _freshness_score(r.date_published) if recent_claim else 0.0
        stale_for_recent = _is_stale_for_recent_claim(claim, r)
        stale_penalty = 0.35 if stale_for_recent else 0.0
        total_score = relevance + freshness * 0.2 - stale_penalty
        scored.append((r, relevance, freshness, total_score, stale_for_recent))
    scored.sort(key=lambda x: x[3], reverse=True)

    # 保底：至少保留更多候选，避免召回在过滤阶段被过度截断
    filtered = [
        r for r, relevance, freshness, total_score, stale_for_recent in scored
        if relevance >= min_relevance and not stale_for_recent
    ]
    if not time_sensitive_claim and len(filtered) < 8:
        # 从剩余结果中补充，但排除得分接近0的完全无关结果
        for r, relevance, freshness, total_score, stale_for_recent in scored:
            if stale_for_recent:
                continue
            if r not in filtered and relevance >= 0.08:
                filtered.append(r)
            if len(filtered) >= 8:
                break

    # 如果全是旧新闻，仍保留最相关的少量结果，避免完全无证据可用
    if not filtered and recent_claim and not time_sensitive_claim:
        for r, relevance, freshness, total_score, stale_for_recent in scored:
            if relevance >= min_relevance:
                filtered.append(r)
            if len(filtered) >= 3:
                break

    dropped = len(results) - len(filtered)

    if dropped > 0:
        logger.info(f"相关性过滤：{len(results)} → {len(filtered)} 条（移除 {dropped} 条无关结果）")
        for r, relevance, freshness, total_score, stale_for_recent in scored:
            if (relevance < min_relevance or stale_for_recent) and r not in filtered:
                logger.debug(
                    f"  移除: [rel={relevance:.2f}, fresh={freshness:.2f}, stale={stale_for_recent}] {r.name[:60]}"
                )

    return filtered


def _map_bocha_freshness(recency_filter: Optional[str]) -> str:
    mapping = {
        "day": "oneDay",
        "week": "oneWeek",
        "month": "oneMonth",
        "year": "oneYear",
    }
    return mapping.get(recency_filter or "", "noLimit")


def _normalize_search_fetch_result(batch) -> SearchFetchResult:
    if isinstance(batch, SearchFetchResult):
        return batch
    return SearchFetchResult(items=batch or [], estimated_total=None)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


async def _do_search(
    search_query: str,
    _unused_client=None,
    recency_filter: Optional[str] = None
) -> SearchFetchResult:
    """执行单次搜索（Bocha Web Search API）"""
    if not config.BOCHA_API_KEY or config.BOCHA_API_KEY.startswith("your_"):
        raise SearchProviderError(
            provider="Bocha",
            message="BOCHA_API_KEY 未配置或仍是占位值",
            auth_error=True,
        )

    headers = {
        "Authorization": f"Bearer {config.BOCHA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "query": search_query,
        "freshness": _map_bocha_freshness(recency_filter),
        "summary": True,
        "count": 50,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(config.BOCHA_BASE_URL, headers=headers, json=payload)
        if response.status_code in (401, 403):
            raise SearchProviderError(
                provider="Bocha",
                message=f"Bocha 搜索鉴权失败 HTTP {response.status_code}",
                status_code=response.status_code,
                auth_error=True,
            )
        response.raise_for_status()
        result = response.json()

        search_results = []
        web_pages_data = result.get("data", {}).get("webPages", {})
        web_pages = web_pages_data.get("value", [])
        estimated_total = web_pages_data.get("totalEstimatedMatches")

        for item in web_pages:
            page_url = _as_text(item.get("url"))
            # Bocha直接提供siteName，比URL域名映射更准确
            site_name = _as_text(item.get("siteName"))
            if site_name:
                source = site_name
            elif page_url:
                source = extract_source_from_url(page_url)
            else:
                source = "媒体报道"

            # 优先summary（AI摘要），降级snippet（简短描述）
            summary = _as_text(item.get("summary") or item.get("snippet"))

            # 只使用真实发布时间。dateLastCrawled 是搜索引擎爬取时间，
            # 不能代表文章发布时间，否则旧内容会被误判为近期证据。
            date_pub = _as_text(item.get("datePublished"))
            # 清理时区格式
            if date_pub:
                date_pub = re.sub(r'[T ].*$', '', date_pub)

            search_results.append(SearchResult(
                name=_as_text(item.get("name")),
                url=page_url,
                summary=summary,
                date_published=date_pub,
                source=source
            ))

        logger.info(f"Bocha搜索 '{search_query[:40]}' 返回 {len(search_results)} 条")
        return SearchFetchResult(items=search_results, estimated_total=estimated_total)


async def _do_tavily_search(search_query: str) -> SearchFetchResult:
    """执行Tavily搜索（直接HTTP请求，避免同步SDK的线程问题）"""
    try:
        if not config.TAVILY_API_KEY or config.TAVILY_API_KEY.startswith("your_"):
            raise SearchProviderError(
                provider="Tavily",
                message="TAVILY_API_KEY 未配置或仍是占位值",
                auth_error=True,
            )

        url = "https://api.tavily.com/search"
        payload = {
            "api_key": config.TAVILY_API_KEY,
            "query": search_query,
            "max_results": 15,
            "topic": "news",
            "days": 30,
            "include_raw_content": False,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code in (401, 403):
                raise SearchProviderError(
                    provider="Tavily",
                    message=f"Tavily 搜索鉴权失败 HTTP {response.status_code}",
                    status_code=response.status_code,
                    auth_error=True,
                )
            response.raise_for_status()
            data = response.json()

        search_results = []
        for item in data.get("results", []):
            url = _as_text(item.get("url"))
            search_results.append(SearchResult(
                name=_as_text(item.get("title")),
                url=url,
                summary=_as_text(item.get("content")),
                date_published=_as_text(item.get("published_date")),
                source=extract_source_from_url(url)
            ))

        logger.info(f"Tavily搜索 '{search_query[:40]}' 返回 {len(search_results)} 条")
        return SearchFetchResult(items=search_results, estimated_total=len(search_results))
    except ImportError:
        logger.warning("tavily-python未安装，跳过Tavily搜索")
        return SearchFetchResult(items=[], estimated_total=0)
    except SearchProviderError:
        raise
    except Exception as e:
        logger.error(f"Tavily搜索异常: {e}")
        return SearchFetchResult(items=[], estimated_total=0)


def _normalize_url_for_dedup(url: str) -> str:
    """规范化 URL 用于去重：去掉查询参数、锚点，统一小写。"""
    if not url:
        return ""
    parsed = urlparse(url)
    return (parsed.scheme + "://" + parsed.netloc + parsed.path).rstrip("/").lower()


def _merge_dedup(main_results: List[SearchResult], extra_results: List[SearchResult]) -> int:
    """合并搜索结果并按规范化URL和标题去重，返回新增条数。"""
    seen_norm_urls = {_normalize_url_for_dedup(r.url) for r in main_results if r.url}
    seen_pairs = {(r.name.strip(), r.source.strip()) for r in main_results}
    seen_titles = {r.name.strip() for r in main_results if r.name.strip()}
    added = 0
    for r in extra_results:
        norm_url = _normalize_url_for_dedup(r.url)
        pair = (r.name.strip(), r.source.strip())
        title = r.name.strip()
        # 1. 规范化 URL 去重
        if norm_url and norm_url in seen_norm_urls:
            continue
        # 2. 标题完全匹配去重（忽略 source 差异，处理转载）
        if title and title in seen_titles:
            continue
        # 3. 原始 (name, source) 对去重
        if not r.url and pair in seen_pairs:
            continue
        if norm_url:
            seen_norm_urls.add(norm_url)
        if title:
            seen_titles.add(title)
        seen_pairs.add(pair)
        main_results.append(r)
        added += 1
    return added


async def _run_search_plan(plan: List[SearchPlanItem]) -> SearchRunResult:
    """执行Bocha搜索计划，按查询顺序合并去重。"""
    tasks = [
        _do_search(item.query, item.recency_filter)
        for item in plan
    ]
    batches = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[SearchResult] = []
    auth_failures = 0
    other_failures = 0
    for item, batch in zip(plan, batches):
        if isinstance(batch, Exception):
            if isinstance(batch, SearchProviderError) and batch.auth_error:
                auth_failures += 1
            else:
                other_failures += 1
            logger.error(f"查询 '{item.query[:30]}' 执行失败: {batch}")
            continue
        normalized = _normalize_search_fetch_result(batch)
        filtered_batch = _filter_irrelevant_results(item.query, normalized.items)
        added = _merge_dedup(results, filtered_batch)
        _log_query_diagnostics(
            source="bocha",
            query=item.query,
            recency_filter=item.recency_filter,
            estimated_total=normalized.estimated_total,
            raw_count=len(normalized.items),
            dedup_count=added,
            filtered_count=len(filtered_batch),
            cumulative_count=len(results),
        )

    return SearchRunResult(
        items=results,
        auth_failures=auth_failures,
        other_failures=other_failures,
    )


async def _run_tavily_fallback(plan: List[SearchPlanItem], claim: str) -> SearchRunResult:
    """当主搜索召回不足时，使用Tavily补充更多候选。"""
    fallback_queries: List[str] = []
    seen = set()
    for item in plan[:3]:
        query = item.query.strip('" ')
        if query and query not in seen:
            fallback_queries.append(query)
            seen.add(query)
    if claim not in seen:
        fallback_queries.append(claim)

    tasks = [_do_tavily_search(query) for query in fallback_queries[:3]]
    batches = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[SearchResult] = []
    auth_failures = 0
    other_failures = 0
    for query, batch in zip(fallback_queries[:3], batches):
        if isinstance(batch, Exception):
            if isinstance(batch, SearchProviderError) and batch.auth_error:
                auth_failures += 1
            else:
                other_failures += 1
            logger.error(f"Tavily补充查询 '{query[:30]}' 失败: {batch}")
            continue
        normalized = _normalize_search_fetch_result(batch)
        filtered_batch = _filter_irrelevant_results(query, normalized.items, min_relevance=0.16)
        added = _merge_dedup(results, filtered_batch)
        _log_query_diagnostics(
            source="tavily",
            query=query,
            recency_filter=None,
            estimated_total=normalized.estimated_total,
            raw_count=len(normalized.items),
            dedup_count=added,
            filtered_count=len(filtered_batch),
            cumulative_count=len(results),
        )

    return SearchRunResult(
        items=results,
        auth_failures=auth_failures,
        other_failures=other_failures,
    )


async def search_evidence(claim: str, _unused_client=None) -> List[SearchResult]:
    """搜索证据：Bocha主搜索 + Tavily补召回 + 相关性过滤。"""
    try:
        plan = _build_search_plan(claim)
        is_recent_claim = _is_recent_claim(claim)
        logger.info(f"搜索计划: {[{'query': item.query, 'recency': item.recency_filter} for item in plan]}")

        bocha_run = await _run_search_plan(plan)
        results = bocha_run.items

        logger.info(f"search_diagnostics stage=post_bocha_dedup total={len(results)}")
        primary_min_relevance = 0.24 if is_recent_claim else 0.2
        results = _filter_irrelevant_results(claim, results, min_relevance=primary_min_relevance)
        logger.info(f"search_diagnostics stage=post_bocha_filter total={len(results)}")

        tavily_run = SearchRunResult(items=[])
        if len(results) < 12:
            logger.info(f"Bocha召回仍偏少，仅 {len(results)} 条，启用 Tavily 补召回")
            tavily_run = await _run_tavily_fallback(plan, claim)
            if tavily_run.items:
                added = _merge_dedup(results, tavily_run.items)
                logger.info(f"search_diagnostics stage=post_tavily_dedup added={added} total={len(results)}")
                fallback_min_relevance = 0.2 if is_recent_claim else 0.16
                results = _filter_irrelevant_results(claim, results, min_relevance=fallback_min_relevance)
                logger.info(f"search_diagnostics stage=post_tavily_filter total={len(results)}")

        if not results and (bocha_run.auth_failures or tavily_run.auth_failures):
            raise SearchServiceError(
                "搜索服务鉴权失败：Bocha/Tavily API Key 无效、过期或未在 Railway Variables 中正确配置。"
            )

        logger.info(f"最终返回 {len(results)} 条证据")
        return results

    except SearchServiceError:
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"搜索API请求失败: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"搜索API调用异常: {e}")
        return []


async def search_with_zhipu(claim: str, _unused_client=None) -> List[SearchResult]:
    """兼容旧入口；实际搜索已切换为 Bocha 主搜索。"""
    return await search_evidence(claim, _unused_client)
