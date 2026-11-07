"""Agente orquestrador: classifica, encaminha ao agente especializado, mede e registra."""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict
from typing import Any

from app.agents import financeiro, interno, ouvidoria
from app.agents.base import AgentResult
from app.context import Contexto, Turno, contextualizar
from app.interaction_log import log_interaction
from app.router import DOMINIOS, RouteDecision, route

log = logging.getLogger("aurora.orchestrator")

AGENTES = {
    "financeiro": ("agente_financeiro", financeiro.answer),
    "informacoes_internas": ("agente_informacoes_internas", interno.answer),
    "ouvidoria": ("agente_ouvidoria", ouvidoria.answer),
}
NOMES = {"financeiro": "Financeiro", "informacoes_internas": "Informações internas", "ouvidoria": "Ouvidoria"}


def _seguranca() -> AgentResult:
    return AgentResult(
        "Não posso fornecer senhas, tokens, credenciais ou dados pessoais de outras pessoas. Pela política de "
        "segurança, credenciais nunca devem ser compartilhadas por e-mail ou chat, e cada pessoa deve acessar apenas "
        "os dados necessários à sua função.\n\n"
        "Canais autorizados:\n"
        "- Acesso a sistemas: abra um chamado no portal de TI (aprovação da liderança e do proprietário do sistema).\n"
        "- Suspeita de incidente ou phishing: seguranca@aurora.example.\n"
        "- Solicitações sobre dados pessoais: privacidade@aurora.example.",
        ["04_seguranca_da_informacao.md", "09_politica_privacidade.md", "05_manual_de_acessos.md"],
        status="recusado")


def _fora_de_escopo() -> AgentResult:
    return AgentResult(
        "Essa pergunta está fora do que eu consigo responder. Atendo apenas três domínios da Aurora:\n"
        "- **Financeiro**: lançamentos, receitas, despesas, orçamento e indicadores.\n"
        "- **Informações internas**: políticas e procedimentos (férias, reembolso, compras, segurança, acessos, RH...).\n"
        "- **Ouvidoria**: manifestações, protocolos OUV-NNNN, status e categorias.\n\n"
        "Pode reformular dentro de um desses temas?", status="fora_de_escopo")


def _esclarecimento(decision: RouteDecision) -> AgentResult:
    candidatos = [c for c in decision.candidatos if c in DOMINIOS] or list(DOMINIOS)
    nomes = ", ".join(NOMES[c] for c in candidatos)
    return AgentResult(
        f"Não tenho certeza de qual área sua pergunta trata (possíveis: {nomes}). Pode escolher o domínio "
        "abaixo ou reformular com mais detalhes (por exemplo, período, número de protocolo ou nome da política)?",
        status="esclarecimento",
        opcoes=[{"dominio": c, "rotulo": NOMES[c]} for c in candidatos])


def handle(question: str, dominio_forcado: str | None = None,
           historico: list[Turno] | None = None) -> dict[str, Any]:
    question = (question or "").strip()
    start = time.perf_counter()
    entry_id = str(uuid.uuid4())
    decision: RouteDecision | None = None
    agente = None
    erro = None
    ctx = Contexto(question, question)

    try:
        ctx = contextualizar(question, historico)
        pergunta = ctx.pergunta
        if dominio_forcado in DOMINIOS:
            decision = RouteDecision(dominio_forcado, 1.0, "escolha_do_usuario",
                                     "Domínio escolhido pelo usuário após pedido de esclarecimento.")
        else:
            decision = route(pergunta)

        if decision.dominio in AGENTES:
            agente, fn = AGENTES[decision.dominio]
            result = fn(pergunta)
        elif decision.dominio == "seguranca":
            agente, result = "guarda_seguranca", _seguranca()
        elif decision.dominio == "ambigua":
            agente, result = "orquestrador", _esclarecimento(decision)
        else:
            agente, result = "orquestrador", _fora_de_escopo()
    except Exception as exc:  # noqa: BLE001
        log.exception("Erro ao responder")
        erro = f"{type(exc).__name__}: {exc}"
        result = AgentResult("Ocorreu um erro interno ao processar a pergunta. O problema foi registrado no log; "
                             "tente novamente em instantes.", status="erro")

    latencia_ms = round((time.perf_counter() - start) * 1000)
    roteamento = asdict(decision) if decision else None
    contexto = {"continuacao": ctx.continuacao, "metodo": ctx.metodo, "pergunta_interpretada": ctx.pergunta,
                "historico": ctx.historico_usado, "erro_llm": ctx.erro_llm}
    detalhes = {"contexto": contexto, "roteamento": roteamento, **result.detalhes}
    llm_usado = result.llm_usado or bool(decision and decision.metodo == "llm") or ctx.metodo.startswith("llm")
    interpretada = ctx.pergunta if ctx.continuacao else None

    log_interaction({
        "id": entry_id, "pergunta": question, "pergunta_interpretada": interpretada, "resposta": result.resposta,
        "dominio_previsto": decision.dominio if decision else None,
        "confianca": decision.confianca if decision else None,
        "metodo_classificacao": decision.metodo if decision else None,
        "agente": agente, "fontes": result.fontes, "ids_consultados": result.ids_consultados,
        "latencia_ms": latencia_ms, "status": result.status,
        "erro": erro or result.detalhes.get("erro_llm") or ctx.erro_llm,
        "llm_usado": llm_usado, "detalhes": detalhes,
    })

    return {
        "id": entry_id,
        "pergunta": question,
        "pergunta_interpretada": interpretada,
        "resposta": result.resposta,
        "dominio": decision.dominio if decision else None,
        "confianca": decision.confianca if decision else None,
        "metodo_classificacao": decision.metodo if decision else None,
        "agente": agente,
        "fontes": result.fontes,
        "ids_consultados": result.ids_consultados,
        "status": result.status,
        "latencia_ms": latencia_ms,
        "llm_usado": llm_usado,
        "tabela": result.tabela,
        "opcoes": result.opcoes,
        "detalhes": detalhes,
    }
