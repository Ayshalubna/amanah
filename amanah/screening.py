"""Sanctions / PEP screening with bilingual fuzzy matching.

A name score alone creates floods of false positives on common Arabic
names, so every hit is corroborated with date of birth and nationality
before a disposition is proposed. The investigator always makes the call.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .names import name_similarity

DATA_DIR = Path(__file__).parent / "data"

NAME_THRESHOLD = 85.0      # below this, not considered a hit at all
STRONG_THRESHOLD = 92.0


@dataclass
class Hit:
    watchlist_id: str
    list_name: str
    listed_name: str
    listed_name_ar: str
    matched_on: str
    name_score: float
    dob_match: bool | None
    nationality_match: bool | None
    confidence: float
    reason: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@lru_cache(maxsize=1)
def load_watchlist(path: str | None = None) -> list[dict]:
    """Synthetic list by default; set AMANAH_WATCHLIST to use e.g. the real UN list."""
    path = path or os.getenv("AMANAH_WATCHLIST")
    if not path:
        from .synth import ensure_data

        ensure_data()
    p = Path(path) if path else DATA_DIR / "watchlist.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _confidence(name_score: float, dob_match: bool | None, nat_match: bool | None) -> float:
    """Blend name similarity with corroborating identifiers into 0-1."""
    conf = (name_score - NAME_THRESHOLD) / (100 - NAME_THRESHOLD) * 0.6 + 0.2
    if dob_match is True:
        conf += 0.35
    elif dob_match is False:
        conf -= 0.25
    if nat_match is True:
        conf += 0.1
    elif nat_match is False:
        conf -= 0.05
    return round(min(max(conf, 0.0), 1.0), 3)


def screen(name_en: str, name_ar: str = "", dob: str | None = None,
           nationality: str | None = None, watchlist: list[dict] | None = None,
           top_k: int = 5) -> list[Hit]:
    watchlist = watchlist if watchlist is not None else load_watchlist()
    hits: list[Hit] = []
    for entry in watchlist:
        candidates = [("name_en", entry["name_en"]), ("name_ar", entry.get("name_ar", ""))]
        candidates += [("alias", a) for a in entry.get("aliases", [])]
        best_score, best_on = 0.0, ""
        for field, listed in candidates:
            if not listed:
                continue
            for query in (name_en, name_ar):
                if not query:
                    continue
                s = name_similarity(query, listed)
                if s > best_score:
                    best_score, best_on = s, f"{field}: {listed}"
        if best_score < NAME_THRESHOLD:
            continue
        listed_dob = entry.get("dob") or ""
        # official lists often give only a birth year
        dob_match = None if not (dob and listed_dob) else (dob[:4] == listed_dob if len(listed_dob) == 4 else dob == listed_dob)
        nat_match = None if not (nationality and entry.get("nationality")) else nationality == entry["nationality"]
        conf = _confidence(best_score, dob_match, nat_match)
        why = [f"name similarity {best_score:.0f}/100 on {best_on}"]
        if dob_match is not None:
            why.append("date of birth matches" if dob_match else "date of birth differs")
        if nat_match is not None:
            why.append("nationality matches" if nat_match else "nationality differs")
        hits.append(Hit(entry["id"], entry["list_name"], entry["name_en"], entry.get("name_ar", ""),
                        best_on, best_score, dob_match, nat_match, conf, "; ".join(why)))
    hits.sort(key=lambda h: h.confidence, reverse=True)
    return hits[:top_k]


def disposition(hits: list[Hit]) -> str:
    """Proposed disposition. 'likely_match' blocks onboarding until reviewed."""
    if not hits:
        return "no_match"
    top = hits[0]
    if top.confidence >= 0.75:
        return "likely_match"
    if top.confidence >= 0.35:
        return "possible_match"
    return "no_match"
