"""Classificação da pergunta (orquestrador).

Ordem de decisão:
1. Guarda de segurança (regex): pedidos de credenciais ou dados pessoais de terceiros => "seguranca".
2. Identificadores exatos: OUV-NNNN => ouvidoria; FIN-NNNN => financeiro.
3. Pontuação por palavras-chave. Se for inequívoca (confiança >= 0.85), decide sem chamar o LLM.
4. Caso contrário, LLM com saída JSON (domínio + confiança). Sem LLM, usa a pontuação.
5. Confiança abaixo do limiar => "ambigua" (o agente pede esclarecimento em vez de chutar).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from app.config import settings
from app.llm import LLMError, get_llm
from app.textutils import normalize

log = logging.getLogger("aurora.router")

DOMINIOS = ("financeiro", "informacoes_internas", "ouvidoria")
TODOS = DOMINIOS + ("seguranca", "fora_de_escopo", "ambigua")
RULE_SHORTCUT = 0.85


@dataclass
class RouteDecision:
    dominio: str
    confianca: float
    metodo: str
    justificativa: str
    pontuacao: dict[str, float] = field(default_factory=dict)
    candidatos: list[str] = field(default_factory=list)
    erro_llm: str | None = None


# --------------------------------------------------------------------------- guarda de segurança

_SENSIVEL = r"(senhas?|password|credencia(l|is)|tokens?|chaves? de api|api keys?|login e senha|acesso de)"
_PESSOAL = r"(holerites?|salarios?|contracheques?|saldo de ferias|cpf|rg|endereco|telefone|dados pessoais|e-?mail pessoal)"
_TERCEIRO = (r"(outr[oa]s?|colegas?|alguem|terceir[oa]s?|del[ea]s?|do (meu )?(chefe|gestor|gerente|diretor)|"
             r"da (minha )?(chefe|gestora|gerente|diretora)|de (um|uma|todos os|todas as) (colaborador|funcionari|cliente|pessoa)|"
             r"d[oa]s? (colaborador|funcionari|cliente|usuari)[a-z]*|do administrador|do admin)")
_PEDIDO = r"(diga|informe|passe|mostre|revele|envie|qual (e|eh)|me (de|da|passa|fala|conta)|preciso d[ae]|quero|descobrir|consultar|ver)"

SEC_PATTERNS = [
    re.compile(rf"\b{_SENSIVEL}\b.*\b{_TERCEIRO}"),
    re.compile(rf"\b{_TERCEIRO}\b.*\b{_SENSIVEL}\b"),
    re.compile(rf"\b{_PEDIDO}\b.*\b{_PESSOAL}\b.*\b{_TERCEIRO}"),
    re.compile(r"\b(burlar|contornar|desativar|quebrar)\b.*\b(mfa|autenticacao|seguranca|senha)"),
]


def security_check(question: str) -> bool:
    t = normalize(question)
    return any(p.search(t) for p in SEC_PATTERNS)


# --------------------------------------------------------------------------- palavras-chave

KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "financeiro": [
        (r"receitas?|faturamento|faturou", 1.5), (r"despesas?", 1.5),
        (r"gastos?|gastou|gastamos|gasto com", 1.2), (r"custos?", 0.8),
        (r"orcamentos?|orcad[oa]|orcamentari[oa]", 1.5), (r"lancamentos?", 1.5),
        (r"inadimplencia|inadimplente", 2), (r"centros? de custo|cc\d{3}", 1.5),
        (r"valor total|soma|somatorio|total gasto|quanto (foi|custou|gastamos|faturamos|saiu|deu)", 1),
        (r"pag[oa]s|pendentes|atrasad[oa]s|vencid[oa]s", 0.6), (r"contrapartes?|fornecedor(es)?", 0.6),
        (r"fin-\d+", 3), (r"execucao orcamentaria", 2), (r"fluxo de caixa|contas a (pagar|receber)", 1.5),
    ],
    "informacoes_internas": [
        (r"politicas?|procedimentos?|normas?|manual|regras? (de|para|da|do)", 1.2),
        (r"ferias", 2), (r"reembols(o|ar)", 1.2), (r"compras?|alcadas?", 1),
        (r"aprovac(ao|oes)|aprovar|aprova", 0.8), (r"phishing", 2.5), (r"seguranca da informacao", 2),
        (r"incidentes?", 1.5), (r"acessos?|perfil de acesso|portal de ti|chamado", 1),
        (r"home office|trabalho remoto|remoto|hibrido|trabalhar de casa", 2), (r"rh|recursos humanos|beneficios?", 1),
        (r"holerite|contracheque", 1.5), (r"privacidade|lgpd|titular(es)? de dados", 1.2),
        (r"fechamento|conciliacao", 1.5), (r"mfa|autenticacao multifator|senha|credencia", 1),
        (r"como (solicito|solicitar|peco|pedir|faco|fazer|reporto|reportar|abro|abrir|atualizo|atualizar)", 1),
        (r"prazo (para|de|do|da)", 0.6), (r"dados cadastrais|cadastro", 1),
    ],
    "ouvidoria": [
        (r"ouvidoria", 3), (r"manifestac(ao|oes)", 2.5), (r"reclamac(ao|oes)|reclamar", 2),
        (r"protocolos?", 2), (r"ouv-?\d+", 4), (r"denuncias?", 1.5), (r"elogios?", 1.5),
        (r"sugest(ao|oes)", 1), (r"cancelamentos?", 0.8), (r"prioridade (critica|alta|media|baixa)", 1),
        (r"em analise|aguardando area|area responsavel", 1.5), (r"canal de entrada", 1.5),
        (r"tempo (medio )?de resposta", 1),
    ],
}


def keyword_scores(question: str) -> dict[str, float]:
    t = normalize(question)
    return {dom: sum(w for pat, w in pats if re.search(rf"\b(?:{pat})\b", t)) for dom, pats in KEYWORDS.items()}


def classify_rules(question: str) -> RouteDecision:
    if security_check(question):
        return RouteDecision("seguranca", 0.95, "regra:seguranca",
                             "Pedido de credenciais ou dados pessoais de terceiros.")
    t = normalize(question)
    if re.search(r"\bouv-?\d+\b", t):
        return RouteDecision("ouvidoria", 0.99, "regra:protocolo", "Contém número de protocolo OUV-NNNN.")
    if re.search(r"\bfin-\d+\b", t):
        return RouteDecision("financeiro", 0.99, "regra:id_lancamento", "Contém ID de lançamento FIN-NNNN.")

    scores = keyword_scores(question)
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (d1, s1), (d2, s2) = ordered[0], ordered[1]
    if s1 == 0:
        return RouteDecision("fora_de_escopo", 0.6, "palavras-chave", "Nenhum termo dos três domínios.",
                             pontuacao=scores)
    if s2 == 0:
        conf = min(0.97, 0.7 + 0.1 * s1)  # um único termo fraco não basta para pular o LLM
    else:
        conf = 0.5 + 0.45 * (s1 - s2) / s1
    candidatos = [d for d, s in ordered if s > 0 and s >= 0.6 * s1]
    return RouteDecision(d1, round(conf, 3), "palavras-chave",
                         f"Pontuação por palavras-chave: {scores}", pontuacao=scores, candidatos=candidatos)


# --------------------------------------------------------------------------- LLM

_SYSTEM = """Você é o orquestrador de um assistente corporativo da Aurora Serviços Digitais S.A. (fictícia).
Classifique a pergunta do usuário em UM domínio:
- "financeiro": valores, somas, totais, rankings ou indicadores calculados sobre lançamentos financeiros
  (receitas, despesas, status Pago/Pendente/Atrasado, departamentos, categorias, centros de custo) ou sobre o
  orçamento mensal; inadimplência; execução orçamentária; IDs FIN-NNNN.
- "informacoes_internas": políticas e procedimentos internos (férias, reembolso, aprovação de compras e alçadas,
  segurança da informação, phishing, acessos a sistemas, home office, incidentes, FAQ de RH, privacidade,
  procedimento de fechamento financeiro). Perguntas de "como fazer", prazos e regras da empresa.
- "ouvidoria": manifestações, reclamações, elogios, sugestões, protocolos OUV-NNNN, status e categorias de
  manifestações, prazos e respostas da ouvidoria.
- "seguranca": pedidos de senhas, tokens, credenciais ou dados pessoais de outras pessoas, ou de burlar controles.
- "fora_de_escopo": nada a ver com os domínios acima.
- "ambigua": a pergunta pode pertencer a mais de um domínio e não dá para decidir sem esclarecimento.
Atenção: uma pergunta sobre a REGRA ou o PROCESSO (ex.: "qual o prazo para pedir reembolso", "quem aprova compra
de R$ 12.000") é informacoes_internas, mesmo citando dinheiro. Pergunta sobre VALORES REGISTRADOS é financeiro.
Responda SOMENTE em JSON: {"dominio": "...", "confianca": 0.0-1.0, "justificativa": "curta",
"candidatos": ["dominios plausíveis quando ambígua"]}"""


def classify_llm(question: str) -> RouteDecision:
    raw = get_llm().json_chat(_SYSTEM, question)
    dominio = str(raw.get("dominio", "")).strip()
    if dominio not in TODOS:
        raise LLMError(f"domínio inválido do LLM: {dominio}")
    conf = float(raw.get("confianca", 0.0))
    candidatos = [c for c in raw.get("candidatos") or [] if c in DOMINIOS]
    return RouteDecision(dominio, max(0.0, min(conf, 1.0)), "llm", str(raw.get("justificativa", ""))[:300],
                         candidatos=candidatos)


def route(question: str) -> RouteDecision:
    rules = classify_rules(question)
    if rules.metodo.startswith("regra:") or (rules.dominio in DOMINIOS and rules.confianca >= RULE_SHORTCUT):
        return rules

    decision = rules
    llm = get_llm()
    if llm.enabled:
        try:
            decision = classify_llm(question)
            decision.pontuacao = rules.pontuacao
            if decision.dominio == "ambigua" and not decision.candidatos:
                decision.candidatos = rules.candidatos
        except (LLMError, ValueError, TypeError) as exc:
            log.warning("Classificação via LLM falhou (%s); usando palavras-chave.", exc)
            decision = rules
            decision.metodo = "palavras-chave (fallback)"
            decision.erro_llm = str(exc)

    if decision.dominio in DOMINIOS and decision.confianca < settings.router_min_confidence:
        candidatos = decision.candidatos or rules.candidatos or [decision.dominio]
        if decision.dominio not in candidatos:
            candidatos = [decision.dominio] + candidatos
        return RouteDecision("ambigua", decision.confianca, decision.metodo,
                             f"Confiança {decision.confianca:.2f} abaixo do limiar "
                             f"{settings.router_min_confidence:.2f}. {decision.justificativa}",
                             pontuacao=decision.pontuacao, candidatos=candidatos, erro_llm=decision.erro_llm)
    return decision
