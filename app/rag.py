"""Recuperação híbrida sobre os documentos internos: BM25 (lexical) + similaridade de embeddings.

O corpus tem ~20 chunks, então o índice fica em memória; os embeddings ficam persistidos no
PostgreSQL (tabela rag_chunks) para não serem recalculados a cada inicialização.
"""
from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass

import numpy as np

from app import db
from app.llm import LLMError, get_llm
from app.textutils import terms

log = logging.getLogger("aurora.rag")

# Termos genéricos (radicais) que aparecem em quase todo documento e não ajudam a decidir relevância
GENERIC_TERMS = {"politi", "proced", "regra", "norma", "manual", "empres", "aurora", "intern", "docume",
                 "inform", "aplica", "deve", "devem"}


@dataclass
class Hit:
    id: str
    source: str
    version: str | None
    title: str
    content: str
    score: float
    lexical: float
    semantic: float | None

    @property
    def is_faq(self) -> bool:
        return self.id.startswith("faq_interno.json#")


class HybridIndex:
    k1 = 1.5
    b = 0.75

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.docs = [terms(f"{r['title']} {r['title']} {r['content']}") for r in rows]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = (sum(len(d) for d in self.docs) / len(self.docs)) if self.docs else 0.0
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

        embs = [r.get("embedding") for r in rows]
        self.has_embeddings = bool(rows) and all(e is not None for e in embs)
        if self.has_embeddings:
            m = np.array(embs, dtype=np.float32)
            self.emb = m / np.linalg.norm(m, axis=1, keepdims=True)
            self.embedding_model = rows[0].get("embedding_model")
        else:
            self.emb = None
            self.embedding_model = None

    def _bm25(self, query_terms: list[str]) -> np.ndarray:
        scores = np.zeros(len(self.docs), dtype=np.float32)
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            for t in set(query_terms):
                if t not in tf:
                    continue
                f = tf[t]
                scores[i] += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return scores

    def search(self, query: str, k: int = 4) -> list[Hit]:
        if not self.rows:
            return []
        lex = self._bm25([t for t in terms(query) if t not in GENERIC_TERMS])
        lex_norm = lex / lex.max() if lex.max() > 0 else lex

        sem = None
        llm = get_llm()
        if self.has_embeddings and llm.enabled:
            try:
                q = np.array(llm.embed([query])[0], dtype=np.float32)
                sem = self.emb @ (q / np.linalg.norm(q))
            except LLMError as exc:
                log.warning("Embedding da consulta falhou, usando só BM25: %s", exc)

        if sem is not None:
            # cosseno de embeddings OpenAI costuma ficar entre ~0.1 e ~0.7: reescala para 0..1
            sem_norm = np.clip((sem - 0.15) / 0.5, 0, 1)
            score = 0.5 * lex_norm + 0.5 * sem_norm
        else:
            score = lex_norm

        order = np.argsort(-score)[:k]
        hits = []
        for i in order:
            r = self.rows[i]
            hits.append(Hit(r["id"], r["source"], r["document_version"], r["title"], r["content"],
                            float(score[i]), float(lex[i]), float(sem[i]) if sem is not None else None))
        return hits


_index: HybridIndex | None = None


def load_index() -> HybridIndex:
    global _index
    rows = db.fetch_all(
        "SELECT id, source, document_version, title, content, embedding, embedding_model "
        "FROM rag_chunks WHERE domain = 'informacoes_internas' ORDER BY id"
    )
    _index = HybridIndex(rows)
    log.info("Índice RAG carregado: %d chunks (embeddings: %s)", len(rows), _index.has_embeddings)
    return _index


def get_index() -> HybridIndex:
    return _index if _index is not None else load_index()
