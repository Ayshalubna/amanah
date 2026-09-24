"""Arabic / English name normalisation for sanctions and PEP screening.

The same person can appear as "محمد عبد الله", "Mohammed Abdullah",
"Muhammad Abd Allah" or "Mohamad Abdalla". Screening only works if all of
these collapse to something comparable, so every name is reduced to a
canonical Latin key before fuzzy matching.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# --- Arabic script ---------------------------------------------------------

_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # diacritics + tatweel

_AR_NORMALISE = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي",
})

# Simple, deterministic Arabic -> Latin mapping (tuned for names, not a full
# romanisation standard). Long vowels map to a/u/i; short vowels are absent
# in unvocalised Arabic, which is why the Latin side is also collapsed below.
_AR_TO_LAT = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s",
    "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q",
    "ك": "k", "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "u", "ي": "i",
    "ء": "", " ": " ",
}

_ARABIC_CHARS = re.compile(r"[؀-ۿ]")


def has_arabic(text: str) -> bool:
    return bool(_ARABIC_CHARS.search(text or ""))


@lru_cache(maxsize=65536)
def normalise_arabic(text: str) -> str:
    text = _TASHKEEL.sub("", text or "")
    text = text.translate(_AR_NORMALISE)
    # "عبد الله" and "عبدالله" are the same name
    text = re.sub(r"عبد\s+ال", "عبدال", text)
    return re.sub(r"\s+", " ", text).strip()


def transliterate_arabic(text: str) -> str:
    text = normalise_arabic(text)
    return "".join(_AR_TO_LAT.get(ch, ch) for ch in text)


# --- Latin script ----------------------------------------------------------

# Common spelling families collapsed to one canonical form.
_VARIANTS = {
    r"\b(mohammed|mohammad|mohamed|mohamad|muhammed|muhamad|mohd|md|mhd|muhammad)\b": "muhammad",
    r"\b(ahmed|ahmad|ahmet)\b": "ahmad",
    r"\b(abdul|abdel|abdal|abd al|abd el|abd ul|abdu)\s*": "abd",
    r"\b(al|el|ul)[\s-]+": "al",
    r"\b(hussein|husain|hussain|husein|hosein)\b": "husayn",
    r"\b(hassan|hasan)\b": "hasan",
    r"\b(yousef|yousuf|yusuf|youssef|yusef)\b": "yusuf",
    r"\b(osman|othman|uthman|usman)\b": "uthman",
    r"\b(omar|umar)\b": "umar",
    r"\b(ali|aly)\b": "ali",
    r"\b(khalid|khaled)\b": "khalid",
    r"\b(fatima|fatimah|fatma)\b": "fatima",
    r"\b(aisha|ayesha|aysha|aicha)\b": "aisha",
    r"\b(ibrahim|ebrahim)\b": "ibrahim",
    r"\bbin\b|\bben\b|\bibn\b": "bin",
    r"\bbint\b": "bint",
}

_HONORIFICS = re.compile(r"\b(mr|mrs|ms|dr|sheikh|shaikh|sh|haji|hajji|eng|sayed|syed)\.?\s+")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _collapse_vowels(token: str) -> str:
    """Drop vowels and squash repeated letters.

    Unvocalised Arabic carries no short vowels, so 'Abdalla' / 'Abdullah' /
    'عبدالله' and 'Umar' / 'عمر' only agree once vowels leave the key.
    Very short names keep their vowels so 'Ali' does not collapse to 'l'.
    """
    key = re.sub(r"[aeiouy]", "", token)
    key = re.sub(r"(.)\1+", r"\1", key)
    return key if len(key) >= 2 else token


@lru_cache(maxsize=65536)
def canonical(name: str) -> str:
    """Canonical Latin form used for display-level matching."""
    if has_arabic(name):
        name = transliterate_arabic(name)
    name = _strip_accents(name).lower()
    name = re.sub(r"[^a-z\s-]", " ", name)
    name = _HONORIFICS.sub("", name + " ").strip()
    for pattern, repl in _VARIANTS.items():
        name = re.sub(pattern, repl, name)
    name = name.replace("-", " ")
    return re.sub(r"\s+", " ", name).strip()


@lru_cache(maxsize=65536)
def phonetic_key(name: str) -> str:
    """Vowel-insensitive key: robust to transliteration differences."""
    tokens = canonical(name).split()
    return " ".join(_collapse_vowels(t) for t in tokens if t)


def name_similarity(a: str, b: str) -> float:
    """0-100 similarity combining spelling, word order and sound."""
    from rapidfuzz import fuzz

    ca, cb = canonical(a), canonical(b)
    pa, pb = phonetic_key(a), phonetic_key(b)
    scores = [
        fuzz.token_sort_ratio(ca, cb),
        fuzz.token_sort_ratio(pa, pb),
        fuzz.token_set_ratio(pa, pb) * 0.92,  # subset matches ("Ali Hasan" vs "Ali Hasan Qasim") slightly discounted
    ]
    if has_arabic(a) and has_arabic(b):
        scores.append(fuzz.token_sort_ratio(normalise_arabic(a), normalise_arabic(b)))
    return round(max(scores), 1)
