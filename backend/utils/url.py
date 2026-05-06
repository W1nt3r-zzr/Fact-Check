"""
Shared URL / domain utilities: media-name mapping, domain extraction, tier detection.
"""
import re
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Domain → media name mapping
# ---------------------------------------------------------------------------

_DOMAIN_MEDIA_MAP: dict[str, str] = {
    # 综合新闻
    'sina.com.cn': '新浪新闻', 'news.sina.com.cn': '新浪新闻',
    'sohu.com': '搜狐新闻', 'news.sohu.com': '搜狐新闻',
    'qq.com': '腾讯新闻', 'new.qq.com': '腾讯新闻',
    '163.com': '网易新闻', 'news.163.com': '网易新闻',
    'people.com.cn': '人民网', 'news.people.com.cn': '人民网',
    'xinhuanet.com': '新华网', 'news.cn': '新华网',
    'chinanews.com.cn': '中国新闻网', 'chinanews.com': '中国新闻网',
    'cctv.com': '央视新闻', 'news.cctv.com': '央视新闻',
    'thepaper.cn': '澎湃新闻', 'paper.cn': '澎湃新闻',
    'bjnews.com.cn': '新京报', 'bjnews.com': '新京报',
    'caixin.com': '财新网', 'caixin.com.cn': '财新网',
    'yicai.com': '第一财经', 'yicai.com.cn': '第一财经',
    'jiemian.com': '界面新闻',
    'thecover.cn': '封面新闻',
    'redstarnews.com': '红星新闻',
    'cbnweek.com': '第一财经周刊',
    '36kr.com': '36氪', '36kr.com.cn': '36氪',
    'ifeng.com': '凤凰新闻', 'news.ifeng.com': '凤凰新闻',
    'huanqiu.com': '环球网',
    'cctv.cn': '央视网',
    'china.com.cn': '中国网',
    'china.com': '中华网',
    'takungpao.com': '大公网',
    'wenhui.news': '文汇报',
    # 财经
    'finance.sina.com.cn': '新浪财经',
    'finance.qq.com': '腾讯财经',
    'eastmoney.com': '东方财富', 'finance.eastmoney.com': '东方财富',
    'stcn.com': '证券时报',
    'cs.com.cn': '中国证券报',
    '21jingji.com': '21世纪经济报道',
    'ce.cn': '中国经济网',
    # 科技
    'ithome.com': 'IT之家',
    'cnbeta.com': 'cnBeta',
    'tech.sina.com.cn': '新浪科技',
    'tech.qq.com': '腾讯科技',
    '36kr.com': '36氪',
    'leiphone.com': '雷锋网',
    'm.yicai.com': '第一财经',
    # 地方媒体
    'southcn.com': '南方网',
    'nanhaiplus.com': '南都',
    'oeeee.com': '南方都市报',
    'nandu.com': '南方都市报',
    'bjd.com.cn': '北京日报',
    'shobserver.com': '上观新闻',
    'paper.xinmin.cn': '新民晚报',
    'jfdaily.com': '解放日报',
    'gd.sina.com.cn': '广东新浪',
    'sc.sina.com.cn': '四川新浪',
    # 政府/官方
    'gov.cn': '中国政府网',
    'npc.gov.cn': '中国人大网',
    'samr.gov.cn': '市场监管总局',
    'cnipa.gov.cn': '国家知识产权局',
    'mofcom.gov.cn': '商务部',
    'miit.gov.cn': '工信部',
    'moe.gov.cn': '教育部',
    'nhc.gov.cn': '国家卫健委',
    # 知识平台
    'zhihu.com': '知乎',
    'baike.baidu.com': '百度百科',
    'baijiahao.baidu.com': '百家号',
    'toutiao.com': '今日头条',
    'weibo.com': '微博', 'weibo.cn': '微博',
    # 视频
    'bilibili.com': '哔哩哔哩', 'b23.cn': '哔哩哔哩',
    'douyin.com': '抖音',
    'ixigua.com': '西瓜视频',
}

# ---------------------------------------------------------------------------
# Tier classification (used by both search and evidence ranking)
# ---------------------------------------------------------------------------

_TIER1_DOMAINS = {
    'gov.cn', 'gkxx.gov.cn', 'people.com.cn', 'xinhuanet.com',
    'cnki.net', 'wanfangdata.com.cn', 'cqvip.com',
    'nature.com', 'science.org', 'ieee.org', 'acm.org',
    'thepaper.cn', 'caixin.com', 'caijing.com.cn', 'finance.sina.com.cn',
    'who.int', 'un.org', 'worldbank.org',
}

_TIER2_DOMAINS = {
    'baike.baidu.com', 'zh.wikipedia.org', 'zhihu.com',
    'sohu.com', 'qq.com', '163.com', 'sina.com.cn',
    'ifeng.com', 'toutiao.com',
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_domain(url: str) -> str:
    """Extract the domain (netloc) from *url*, stripping the ``www.`` prefix."""
    if not url:
        return ''
    try:
        domain = urlparse(url).netloc.lower()
        return re.sub(r'^www\.', '', domain)
    except Exception:
        return ''


def extract_source_from_url(url: str) -> str:
    """Map a URL to its Chinese media name, falling back to '媒体报道'."""
    if not url:
        return '媒体报道'

    domain = extract_domain(url)
    if not domain:
        return '媒体报道'

    # Exact match
    if domain in _DOMAIN_MEDIA_MAP:
        return _DOMAIN_MEDIA_MAP[domain]

    # Parent-domain match (e.g. news.sina.com.cn → sina.com.cn)
    parts = domain.split('.')
    for i in range(len(parts)):
        parent = '.'.join(parts[i:])
        if parent in _DOMAIN_MEDIA_MAP:
            return _DOMAIN_MEDIA_MAP[parent]

    return '媒体报道'


def get_authority_score(url: str) -> float:
    """
    Return an authority score (0-100) based on the URL's domain.

    Used by the evidence ranker so that official sources score higher.
    """
    domain = extract_domain(url)
    if not domain:
        return 50.0

    if any(t1 in domain for t1 in _TIER1_DOMAINS):
        return 95.0
    if any(t2 in domain for t2 in _TIER2_DOMAINS):
        return 80.0
    if '.edu.' in domain or '.ac.' in domain:
        return 85.0
    if '.org.' in domain:
        return 75.0
    if domain.endswith('.com'):
        return 60.0
    if domain.endswith('.cn'):
        return 65.0
    return 50.0


def get_domain_tier(url: str) -> str:
    """Return 'Tier 1', 'Tier 2', or 'Tier 3' based on the URL's domain."""
    score = get_authority_score(url)
    if score >= 90:
        return 'Tier 1'
    if score >= 70:
        return 'Tier 2'
    return 'Tier 3'
