"""
Shared text-processing utilities: stop-words, keyword extraction, date parsing.
"""
import re
from datetime import datetime
from typing import List, Optional

# ---------------------------------------------------------------------------
# Stop-words
# ---------------------------------------------------------------------------

STOP_WORDS: set[str] = set(
    '的了是在和与或但而等很也都就有被把让给向从到对为以之'
    '可以可能因为所以但是然而如果已经正在没有不是'
    '一个什么怎么如何通过进行关于包括其中对于目前'
    '根据显示表示认为指出说明报道来自其他这些那些'
    '他们我们你们之间以来需要能够应该必须虽然不过'
    '而且或者以及所有一些每个任何非常相当比较更加'
    '真的这个那个这里那里它他她我你您们'
    '然后之后之前同时因此于是还是'
    .split()
) | {
    '的', '了', '是', '在', '和', '与', '或', '但', '而', '等', '很', '也', '都', '就',
    '有', '被', '把', '让', '给', '向', '从', '到', '对', '为', '以', '之', '这', '那',
    '可以', '可能', '因为', '所以', '但是', '然而', '如果', '虽然', '而且', '或者', '以及',
    '已经', '正在', '没有', '不是', '一个', '什么', '怎么', '如何', '通过', '进行', '关于',
    '包括', '其中', '对于', '目前', '根据', '显示', '表示', '认为', '指出', '说明', '报道',
    '来自', '需要', '能够', '应该', '必须', '不过', '还是', '因此', '同时', '之后', '之前',
    '然后', '于是', '起来', '出来', '得到', '发生', '出现', '成为', '开始', '来说',
}

# Fact-check framing words that can be stripped without changing meaning.
FRAME_WORDS: set[str] = {
    '据了解', '据悉', '有消息称', '消息称', '网传', '传言', '听说',
    '据说', '有人说', '有人称', '有人认为', '有人说', '有观点认为',
    '是否真的', '是不是真的', '到底是不是', '真的是这样吗',
    '请问', '想知道', '想知道是否', '求证', '请核实', '核实一下',
    '是真的吗', '真的假的', '是不是', '是否属实', '是否正确', '对不对',
    '吗', '呢', '吧', '啊', '呀',
}

# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------


def extract_keywords(text: str, top_n: int = 20, min_len: int = 2, max_len: int = 4) -> List[str]:
    """
    Extract Chinese keywords from *text* using a simple regex-based approach.

    Parameters
    ----------
    text:
        Input text.
    top_n:
        Maximum number of keywords to return.
    min_len:
        Minimum keyword length (in characters).
    max_len:
        Maximum keyword length (in characters).

    Returns
    -------
    List of unique keywords sorted by length descending.
    """
    if not text:
        return []

    pattern = re.compile(r'[一-龥]{' + str(min_len) + r',' + str(max_len) + r'}')
    keywords = pattern.findall(text)
    keywords = [kw for kw in keywords if kw not in STOP_WORDS]
    return sorted(set(keywords), key=len, reverse=True)[:top_n]


def extract_keywords_with_freq(text: str, top_n: int = 20) -> List[str]:
    """
    Extract keywords and return them sorted by frequency descending.
    """
    if not text:
        return []

    words = re.findall(r'[一-龥]{2,}', text)
    words = [w for w in words if w not in STOP_WORDS and len(w) >= 2]

    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in sorted_words[:top_n]]


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    '%Y-%m-%d',
    '%Y年%m月%d日',
    '%Y/%m/%d',
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S',
]


def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse a date string into a *datetime* object.

    Supports the most common Chinese / ISO formats.
    Returns *None* when parsing fails.
    """
    if not date_str:
        return None

    # Strip time / timezone noise first
    cleaned = date_str.split('T')[0].split()[0]

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    return None


def parse_date_to_iso(date_str: str) -> Optional[str]:
    """Parse a date string and return an ISO ``YYYY-MM-DD`` string."""
    dt = parse_date(date_str)
    return dt.strftime('%Y-%m-%d') if dt else None
