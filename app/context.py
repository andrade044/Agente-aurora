"""Memória curta de conversa: transforma perguntas de continuação em perguntas completas.

Ex.: depois de "Quais são as aprovações para uma compra de R$ 12.000?", a mensagem "E se eu quiser de 6000?"
vira "Quais são as aprovações para uma compra de R$ 6.000?" antes de ir para o orquestrador.

- Com LLM: o modelo reescreve a pergunta usando as últimas trocas (saída JSON validada).
- Sem LLM (ou se o LLM falhar): a pergunta é concatenada à anterior e herda o domínio anterior quando não
  traz termos de outro domínio. É uma aproximação, registrada como limitação.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.llm import LLMError, get_llm
from app.textutils import normalize

log = logging.getLogger("aurora.context")

MAX_TURNOS = 3

_INICIO_CONTINUACAO = re.compile(
    r"^(e|mas|ou|entao|tambem|agora|e se|e quanto|e no|e na|e em|e para|e pra|e o|e a|e os|e as|e do|e da|"
    r"e esse|e essa|e isso|e aquele|e aquela|e ele|e ela|nesse caso|neste caso|no caso|e no caso)\b")
_REFERENCIA = re.compile(r"\b(isso|esse|essa|esses|essas|ele|ela|eles|elas|mesmo|mesma|anterior|acima|dele|dela|"
                         r"desse|dessa|nisso|aquilo|ultimo|ultima)\b")


@dataclass
class Turno:
    pergunta: str
    dominio: str | None = None
    resposta: str | None = None


@dataclass
class Contexto:
    pergunta_original: str
    pergunta: str                       # a que segue para o orquestrador
    continuacao: bool = False
    dominio_anterior: str | None = None
    metodo: str = "nenhum"              # nenhum | llm | concatenacao | llm_sem_mudanca
    erro_llm: str | None = None
    historico_usado: list[dict] = field(default_factory=list)


def parece_continuacao(pergunta: str, historico: list[Turno]) -> bool:
    if not historico:
        return False
    from app.router import keyword_scores  # import tardio: router não depende deste módulo

    t = normalize(pergunta).strip(" ?!.")
    if _INICIO_CONTINUACAO.match(t) or _REFERENCIA.search(t):
        return True
    # pergunta curta sem nenhum termo de domínio ("de 6000?", "fevereiro?"); "Como solicito férias?" não entra
    return len(t.split()) <= 4 and not any(keyword_scores(pergunta).values()) and not re.search(r"\b(ouv|fin)-?\d", t)


_SYSTEM = """Você reescreve mensagens de um chat corporativo para que possam ser entendidas sem o histórico.
Recebe as últimas trocas (pergunta do usuário, domínio e início da resposta) e a nova mensagem.
Se a nova mensagem depender do histórico (ex.: "e se for de 6000?", "e em fevereiro?", "e o protocolo seguinte?",
"mas eu queria saber da regra"), reescreva-a como UMA pergunta completa e autossuficiente em português,
trocando referências implícitas pelos valores do histórico e mantendo exatamente a intenção do usuário.
Não responda a pergunta, não acrescente informação que não esteja no histórico ou na mensagem.
Se a mensagem já for autossuficiente, devolva-a sem mudanças.
Responda SOMENTE em JSON: {"continuacao": true|false, "pergunta": "..."}"""


def _historico_texto(historico: list[Turno]) -> str:
    linhas = []
    for i, t in enumerate(historico, 1):
        resp = (t.resposta or "").replace("\n", " ")[:300]
        linhas.append(f"{i}. Usuário: {t.pergunta}\n   Domínio: {t.dominio or '?'}\n   Resposta (início): {resp}")
    return "\n".join(linhas)


def contextualizar(pergunta: str, historico: list[Turno] | None) -> Contexto:
    historico = [t for t in (historico or []) if t.pergunta.strip()][-MAX_TURNOS:]
    ctx = Contexto(pergunta, pergunta, historico_usado=[t.__dict__ for t in historico])
    if not parece_continuacao(pergunta, historico):
        return ctx

    anterior = historico[-1]
    ctx.dominio_anterior = anterior.dominio
    llm = get_llm()
    if llm.enabled:
        try:
            raw = llm.json_chat(_SYSTEM, f"Histórico:\n{_historico_texto(historico)}\n\nNova mensagem: {pergunta}")
            nova = str(raw.get("pergunta") or "").strip()
            if not nova or len(nova) > 600:
                raise LLMError("reescrita vazia ou longa demais")
            ctx.continuacao = bool(raw.get("continuacao")) and nova != pergunta
            ctx.pergunta = nova if ctx.continuacao else pergunta
            ctx.metodo = "llm" if ctx.continuacao else "llm_sem_mudanca"
            return ctx
        except (LLMError, ValueError, TypeError) as exc:
            log.warning("Reescrita via LLM falhou (%s); usando concatenação.", exc)
            ctx.erro_llm = str(exc)

    ctx.continuacao = True
    ctx.pergunta = f"{anterior.pergunta.rstrip()} {pergunta}"
    ctx.metodo = "concatenacao"
    return ctx
