"""Bilingual policy retrieval with citations.

Default retriever: character n-gram TF-IDF, which handles Arabic and English
without downloading any model. If `sentence-transformers` is installed, a
multilingual embedding model is blended in (hybrid search) so an English
question can find the Arabic policy and vice versa.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

POLICY_DIR = Path(__file__).parent / "data" / "policies"
EMBED_MODEL = os.getenv("AMANAH_EMBED_MODEL", "intfloat/multilingual-e5-small")


@dataclass
class Passage:
    doc: str
    section: str
    text: str
    lang: str

    @property
    def citation(self) -> str:
        return f"{self.doc} §{self.section}"


def load_passages(policy_dir: Path = POLICY_DIR) -> list[Passage]:
    passages = []
    for path in sorted(policy_dir.glob("*.md")):
        lang = "ar" if path.stem.endswith("_ar") else "en"
        for block in re.split(r"\n(?=## )", path.read_text(encoding="utf-8")):
            m = re.match(r"## ([^\n]+)\n(.*)", block, re.S)
            if m:
                passages.append(Passage(path.stem, m.group(1).strip(), m.group(2).strip(), lang))
    return passages


class Retriever:
    def __init__(self, passages: list[Passage] | None = None, use_embeddings: bool | None = None):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.passages = passages or load_passages()
        corpus = [f"{p.section} {p.text}" for p in self.passages]
        self.tfidf = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.tfidf.fit_transform(corpus)
        self.encoder = None
        self.embeddings = None
        if use_embeddings is None:
            use_embeddings = os.getenv("AMANAH_EMBEDDINGS", "auto") != "off"
        if use_embeddings:
            try:
                from sentence_transformers import SentenceTransformer

                self.encoder = SentenceTransformer(EMBED_MODEL)
                self.embeddings = self.encoder.encode([f"passage: {c}" for c in corpus], normalize_embeddings=True)
            except Exception:  # not installed or no network: TF-IDF only
                self.encoder = None

    @property
    def mode(self) -> str:
        return "hybrid (tf-idf + multilingual embeddings)" if self.encoder else "tf-idf (char n-grams)"

    def search(self, query: str, k: int = 3, lang: str | None = None) -> list[tuple[Passage, float]]:
        lexical = (self.matrix @ self.tfidf.transform([query]).T).toarray().ravel()
        scores = lexical / (lexical.max() or 1)
        if self.encoder is not None:
            q = self.encoder.encode([f"query: {query}"], normalize_embeddings=True)[0]
            dense = self.embeddings @ q
            scores = 0.4 * scores + 0.6 * (dense / (dense.max() or 1))
        order = np.argsort(-scores)
        results = [(self.passages[i], float(scores[i])) for i in order if lang is None or self.passages[i].lang == lang]
        return results[:k]


@lru_cache(maxsize=1)
def get_retriever() -> Retriever:
    return Retriever()
