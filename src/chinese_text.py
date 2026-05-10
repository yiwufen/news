"""Chinese text segmentation utilities for FTS5 indexing and query construction."""

from __future__ import annotations

import logging
import re
from functools import lru_cache

logger = logging.getLogger(__name__)

_CJK_RANGE = re.compile(r"[一-鿿]+")


def _get_jieba():
    """Lazy-load jieba to avoid startup overhead (~0.5s dictionary load)."""
    import jieba

    return jieba


def segment_chinese(text: str) -> str:
    """Segment Chinese text with jieba, return space-separated words.

    Non-CJK segments (English, numbers, punctuation) are preserved as-is.
    CJK segments are tokenized by jieba into individual words.
    """
    if not text or not text.strip():
        return text

    if not _CJK_RANGE.search(text):
        return text

    jieba = _get_jieba()
    parts: list[str] = []
    for segment in re.findall(r"[一-鿿]+|[^一-鿿]+", text):
        if _CJK_RANGE.fullmatch(segment):
            words = list(jieba.cut(segment, HMM=True))
            parts.extend(words)
        else:
            parts.append(segment)
    return " ".join(parts)


def contains_chinese(text: str) -> bool:
    """Check if text contains CJK characters."""
    return bool(_CJK_RANGE.search(text))


@lru_cache(maxsize=512)
def segment_query(text: str) -> list[str]:
    """Segment text and extract tokens suitable for FTS5 queries.

    Returns individual tokens (words), filtering out whitespace and
    single-character noise.
    """
    segmented = segment_chinese(text)
    tokens = re.findall(r"[A-Za-z0-9_.-]+|[一-鿿]+", segmented)
    return [t for t in tokens if len(t) >= 2]
