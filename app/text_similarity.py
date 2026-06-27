"""
Yengil matn o'xshashligi (embeddingsiz) — dublikat yangiliklarni aniqlash uchun.

Usul: so'z to'plamlari (token set) ustida JACCARD o'xshashligi.
  Jaccard(A, B) = |A ∩ B| / |A ∪ B|   →  0.0 (umuman boshqa) ... 1.0 (bir xil)

Nega Jaccard (SimHash emas): so'z tartibiga sezgir emas, natijasi tushunarli
(0..1 oralig'ida), va yaqin-dublikat yangiliklar uchun aniq ajratadi.
Embedding/model talab qilmaydi — tez va arzon.
"""
from __future__ import annotations

import re

_URL_RE = re.compile(r"https?://\S+")
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")

# Tahlilga ta'sir qilmaydigan eng keng tarqalgan to'xtatuv so'zlar
_STOPWORDS = {
    "va", "ham", "bu", "uchun", "bilan", "yoki", "lekin", "ammo", "esa",
    "deb", "edi", "the", "and", "for", "что", "это", "как", "так",
}

# Bir story uchun saqlanadigan maksimal kalit so'zlar soni
_MAX_KEYWORDS = 60


def tokenize(text: str) -> set[str]:
    """Matndan ma'noli so'zlar to'plamini ajratadi."""
    text = (text or "").lower()
    text = _URL_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text)
    return {
        w for w in text.split()
        if len(w) >= 3 and not w.isdigit() and w not in _STOPWORDS
    }


def keywords_str(text: str) -> str:
    """Saqlash uchun: tartiblangan, takrorlanmas kalit so'zlar (bo'sh joy bilan)."""
    tokens = sorted(tokenize(text))[:_MAX_KEYWORDS]
    return " ".join(tokens)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_similar(a_keywords: str, b_keywords: str, threshold: float) -> bool:
    """Ikki kalit so'zlar to'plami threshold (0..1) bo'yicha o'xshashmi?"""
    return jaccard(set(a_keywords.split()), set(b_keywords.split())) >= threshold
