"""Agente de Informações Internas (RAG sobre políticas e procedimentos).

1. Recupera os trechos mais relevantes (BM25 + embeddings, ver app/rag.py).
2. Com LLM: gera a resposta SOMENTE a partir dos trechos, citando o arquivo-fonte.
3. Sem LLM (ou se o LLM falhar): responde com o item de FAQ correspondente ou com o trecho do documento.
"""
from __future__ import annotations

import logging

from app.agents.base import AgentResult
from app.config import settings
from app.llm import LLMError, get_llm
from app.rag import Hit, get_index

log = logging.getLogger("aurora.interno")

# Abaixo deste escore BM25 consideramos que nenhum documento trata do assunto
MIN_LEXICAL = 1.5
MIN_HYBRID = 0.35

_SYSTEM = """Você é o assistente de informações internas da Aurora Serviços Digitais S.A. (empresa fictícia).
Responda em português do Brasil, de forma objetiva, usando EXCLUSIVAMENTE os trechos de documentos fornecidos.
Regras:
- Não invente regras, prazos, valores, e-mails ou canais que não estejam nos trechos.
- Cite o(s) arquivo(s)-fonte no final no formato: Fonte: nome_do_arquivo.md
- Se os trechos não responderem à pergunta, diga claramente que a informação não consta na documentação
  disponível e oriente procurar o canal indicado nos trechos (RH, TI, Financeiro), sem inventar.
- Não confirme dados individuais (saldo de férias, holerite, elegibilidade pessoal) nem revele dados de
  outras pessoas ou credenciais; oriente o canal oficial descrito nos documentos.
- Respeite os "limites do agente" descritos nos documentos."""


def _context(hits: list[Hit]) -> str:
    blocos = []
    for h in hits:
        versao = f" (versão {h.version})" if h.version else ""
        blocos.append(f"[{h.source}{versao}] {h.title}\n{h.content}")
    return "\n\n---\n\n".join(blocos)


def _relevant(hits: list[Hit]) -> list[Hit]:
    if not hits:
        return []
    top = hits[0]
    if top.lexical < MIN_LEXICAL and (top.semantic is None or top.score < MIN_HYBRID):
        return []
    return [h for h in hits if h.score >= 0.45 * top.score]


def _sources(hits: list[Hit]) -> list[str]:
    out: list[str] = []
    for h in hits:
        if h.source not in out:
            out.append(h.source)
    return out


def _fallback_answer(hits: list[Hit]) -> str:
    top = hits[0]
    if top.is_faq:
        doc = next((h for h in hits if not h.is_faq and h.source == top.source), None)
        resposta = f"{top.content}\n\nFonte: {top.source}"
        if doc:
            resposta += f"\n\nTrecho do documento ({doc.title}):\n{doc.content}"
        return resposta
    return f"Trecho relevante — {top.title}:\n\n{top.content}\n\nFonte: {top.source}"


def answer(question: str) -> AgentResult:
    hits = get_index().search(question, k=settings.rag_top_k)
    relevant = _relevant(hits)
    ids = [h.id for h in relevant]
    detalhes = {"recuperados": [{"id": h.id, "score": round(h.score, 3), "bm25": round(h.lexical, 3),
                                 "cosseno": None if h.semantic is None else round(h.semantic, 3)} for h in hits]}

    if not relevant:
        return AgentResult(
            "Não encontrei essa informação na documentação interna disponível (políticas de férias, reembolso, "
            "compras, segurança, acessos, home office, incidentes, RH, privacidade e fechamento financeiro). "
            "Para casos não cobertos, procure o RH (rh@aurora.example) ou abra um chamado no portal de TI.",
            [], ids, status="nao_encontrado", detalhes=detalhes)

    llm = get_llm()
    if llm.enabled:
        try:
            user = f"Pergunta: {question}\n\nTrechos dos documentos:\n\n{_context(relevant)}"
            texto = llm.text_chat(_SYSTEM, user)
            if texto:
                cited = [s for s in _sources(relevant) if s in texto]
                return AgentResult(texto, cited or _sources(relevant)[:1], ids, llm_usado=True,
                                   detalhes={**detalhes, "geracao": "llm"})
        except LLMError as exc:
            log.warning("Geração via LLM falhou (%s); usando resposta extrativa.", exc)
            detalhes["erro_llm"] = str(exc)

    return AgentResult(_fallback_answer(relevant), [relevant[0].source], ids,
                       detalhes={**detalhes, "geracao": "extrativa"})
