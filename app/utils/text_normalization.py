from __future__ import annotations

import re
from difflib import SequenceMatcher


STOPWORDS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "i",
    "need",
    "still",
    "the",
    "to",
    "will",
}


def normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def significant_tokens(value: str) -> set[str]:
    return {token for token in normalize_text(value).split() if token not in STOPWORDS}


def similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    left_tokens = significant_tokens(left_norm)
    right_tokens = significant_tokens(right_norm)
    if left_tokens and right_tokens:
        overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    else:
        overlap = 0.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    return max(overlap, sequence)
