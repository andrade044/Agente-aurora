"""Agente Financeiro.

Princípio: o LLM (quando disponível) só EXTRAI parâmetros da pergunta. Todo cálculo é feito por
consultas SQL pré-definidas e parametrizadas no PostgreSQL, com valores NUMERIC/Decimal.
O modelo nunca escreve SQL nem estima números.
"""
from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app import db
from app.agents.base import AgentResult
from app.llm import LLMError, get_llm
from app.textutils import Period, br_date, brl, normalize, parse_period, pct, plural

log = logging.getLogger("aurora.financeiro")

FONTE_LANC = "lancamentos_financeiros.csv"
FONTE_ORC = "orcamento_mensal.csv"
FONTE_REGRAS = "indicadores_e_regras.json"

OPERACOES = {"total", "agrupar", "maiores_lancamentos", "orcamento", "execucao_orcamentaria",
             "inadimplencia", "lancamento", "nao_identificado"}
TIPOS = {"Receita", "Despesa"}
STATUS = {"Pago", "Pendente", "Atrasado"}
DIMENSOES = {
    "departamento": "departamento",
    "categoria": "categoria",
    "status": "status",
    "tipo": "tipo",
    "contraparte": "contraparte",
    "centro_custo": "centro_custo",
    "metodo_pagamento": "metodo_pagamento",
    "mes": None,  # depende do campo de data
}
CAMPOS_DATA = {"data_competencia", "data_vencimento"}

# Sinônimos -> valor canônico (texto normalizado, sem acento)
DEPT_ALIASES = {
    "tecnologia": "Tecnologia", "ti": "Tecnologia", "operacoes": "Operações", "operacao": "Operações",
    "comercial": "Comercial", "vendas": "Comercial", "marketing": "Marketing",
    "recursos humanos": "Recursos Humanos", "rh": "Recursos Humanos",
    "departamento financeiro": "Financeiro", "area financeira": "Financeiro",
    "departamento de financas": "Financeiro", "setor financeiro": "Financeiro",
}
CAT_ALIASES = {
    "impostos": "Impostos e taxas", "taxas": "Impostos e taxas", "tributos": "Impostos e taxas",
    "cloud": "Infraestrutura cloud", "nuvem": "Infraestrutura cloud", "infraestrutura": "Infraestrutura cloud",
    "material de escritorio": "Material de escritório", "escritorio": "Material de escritório",
    "suprimentos": "Material de escritório",
    "salarios": "Salários e encargos", "salario": "Salários e encargos", "encargos": "Salários e encargos",
    "folha": "Salários e encargos",
    "servicos profissionais": "Serviços profissionais", "consultoria": "Serviços profissionais",
    "software": "Software e licenças", "licencas": "Software e licenças", "licenca": "Software e licenças",
    "treinamento": "Treinamento", "treinamentos": "Treinamento", "capacitacao": "Treinamento",
    "viagens": "Viagens", "viagem": "Viagens", "hospedagem": "Viagens", "passagens": "Viagens",
    "receita de servicos": "Receita de serviços",
    "categoria marketing": "Marketing", "categoria de marketing": "Marketing",
}
CC_DEPT = {"CC100": "Tecnologia", "CC200": "Operações", "CC300": "Comercial", "CC400": "Marketing",
           "CC500": "Recursos Humanos", "CC600": "Financeiro"}


@dataclass
class FinParams:
    operacao: str = "total"
    tipo: str | None = None
    status: list[str] = field(default_factory=list)
    departamentos: list[str] = field(default_factory=list)
    categorias: list[str] = field(default_factory=list)
    centros_custo: list[str] = field(default_factory=list)
    data_inicio: date | None = None
    data_fim: date | None = None
    campo_data: str = "data_competencia"
    agrupar_por: str | None = None
    ordem: str = "desc"
    limite: int = 10
    ids: list[str] = field(default_factory=list)
    foco_contagem: bool = False

    @property
    def period(self) -> Period | None:
        if self.data_inicio and self.data_fim:
            return Period(self.data_inicio, self.data_fim)
        return None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["data_inicio"] = self.data_inicio.isoformat() if self.data_inicio else None
        d["data_fim"] = self.data_fim.isoformat() if self.data_fim else None
        return d


# =========================================================================== extração por regras

def _find_aliases(t: str, aliases: dict[str, str]) -> list[str]:
    found: list[str] = []
    for alias in sorted(aliases, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", t):
            value = aliases[alias]
            if value not in found:
                found.append(value)
            t = re.sub(rf"\b{re.escape(alias)}\b", " ", t)
    return found


def parse_rules(question: str) -> FinParams:
    t = normalize(question)
    p = FinParams()

    p.ids = [i.upper() for i in re.findall(r"\bfin-\d{4}\b", t)]
    if p.ids:
        p.operacao = "lancamento"
        return p

    # tipo
    if re.search(r"\b(receitas?|faturamento|faturou|recebimentos?|recebido|receber)\b", t):
        p.tipo = "Receita"
    elif re.search(r"\b(despesas?|gastos?|gastou|gastamos|gasto|custos?|pagamentos?|pagar)\b", t):
        p.tipo = "Despesa"

    # status
    if re.search(r"\b(pag[oa]s?|quitad[oa]s?|efetivamente pag)", t):
        p.status.append("Pago")
    if re.search(r"\b(pendentes?|em aberto|a pagar|a receber)\b", t):
        p.status.append("Pendente")
    if re.search(r"\b(atrasad[oa]s?|em atraso|vencid[oa]s?)\b", t):
        p.status.append("Atrasado")

    if re.search(r"\b(vencimento|vencem|vence|vencer)\b", t):
        p.campo_data = "data_vencimento"

    # categorias primeiro; os trechos já usados como categoria saem do texto antes de buscar departamentos
    # ("categoria marketing" é categoria; "marketing" sozinho é o departamento)
    p.categorias = _find_aliases(t, CAT_ALIASES)
    t_dept = t
    for alias in sorted(CAT_ALIASES, key=len, reverse=True):
        if CAT_ALIASES[alias] in p.categorias:
            t_dept = re.sub(rf"\b{re.escape(alias)}\b", " ", t_dept)
    p.departamentos = _find_aliases(t_dept, DEPT_ALIASES)
    if "Receita de serviços" in p.categorias:
        p.tipo = "Receita"
    p.centros_custo = sorted({c.upper() for c in re.findall(r"\bcc\d{3}\b", t)})

    period = parse_period(question)
    if period:
        p.data_inicio, p.data_fim = period.start, period.end

    m = re.search(r"\b(top|maiores|menores|principais)\s+(\d{1,2})\b", t) or re.search(r"\b(\d{1,2})\s+(maiores|menores|principais)\b", t)
    if m:
        p.limite = int(next(g for g in m.groups() if g.isdigit()))
    if re.search(r"\b(menor|menores|menos)\b", t):
        p.ordem = "asc"
    p.foco_contagem = bool(re.search(r"\b(quantos|quantas|quantidade|numero de)\b", t))

    # operação
    dim = None
    dim_patterns = [
        ("departamento", r"departamento|departamentos|area|areas|setor|setores"),
        ("categoria", r"categoria|categorias"),
        ("centro_custo", r"centro de custo|centros de custo"),
        ("contraparte", r"fornecedor|fornecedores|cliente|clientes|contraparte|contrapartes"),
        ("status", r"status"),
        ("metodo_pagamento", r"metodo de pagamento|metodos de pagamento|forma de pagamento|formas de pagamento"),
        ("mes", r"mes|meses|mensal|mensalmente|por mes|cada mes"),
    ]
    for name, pat in dim_patterns:
        if re.search(rf"\b(por|qual|quais|cada|entre os|entre as|ranking de|ranking dos|ranking das)\s+(o |a |os |as )?({pat})\b", t):
            dim = name
            break
    if dim is None and re.search(r"\b(mensal|mensalmente|mes a mes|evolucao)\b", t):
        dim = "mes"

    if re.search(r"inadimpl", t):
        p.operacao = "inadimplencia"
        p.tipo = "Receita"
    elif re.search(r"execucao orcamentaria|orcado (x|vs|versus|e) realizado|realizado (x|vs|versus) orcado|(percentual|porcentagem|%) do orcamento|estour", t):
        p.operacao = "execucao_orcamentaria"
    elif re.search(r"\borcament", t):
        p.operacao = "orcamento"
        p.agrupar_por = dim or ("departamento" if re.search(r"\b(maior|menor|mais|menos|ranking)\b", t) else None)
        p.tipo = None
    elif dim:
        p.operacao = "agrupar"
        p.agrupar_por = dim
    elif re.search(r"\b(maior|maiores|menor|menores)\s+(lancamentos?|despesas?|receitas?|gastos?|pagamentos?)\b", t):
        p.operacao = "maiores_lancamentos"
        if not m:
            p.limite = 5
    else:
        p.operacao = "total"
    return p


# =========================================================================== extração via LLM

_SYSTEM_EXTRACAO = """Você extrai parâmetros de perguntas sobre dados financeiros de uma empresa fictícia.
Responda SOMENTE com um objeto JSON com estas chaves:
- "operacao": uma de ["total","agrupar","maiores_lancamentos","orcamento","execucao_orcamentaria","inadimplencia","lancamento","nao_identificado"]
    total = soma/contagem de lançamentos; agrupar = totais por uma dimensão (ranking);
    maiores_lancamentos = lista dos maiores/menores lançamentos; orcamento = valores do orçamento mensal
    (use agrupar_por="departamento" para comparar departamentos); execucao_orcamentaria = despesas pagas / orçamento;
    inadimplencia = receitas atrasadas / receitas totais; lancamento = consulta de IDs FIN-NNNN;
    nao_identificado = a pergunta NÃO pede nenhum valor, total, ranking ou lançamento registrado (ex.: pergunta
    sobre regra/política, valor solto sem dizer o que medir, conversa). Na dúvida, use nao_identificado.
- "tipo": "Receita", "Despesa" ou null
- "status": lista com valores entre ["Pago","Pendente","Atrasado"] (vazia se a pergunta não restringe status;
    "pagas"/"efetivamente pagas" => ["Pago"])
- "departamentos": lista entre {departamentos}
- "categorias": lista entre {categorias}
- "centros_custo": lista entre {centros}
- "data_inicio", "data_fim": datas ISO (AAAA-MM-DD) do período pedido, ou null se não houver período
- "campo_data": "data_competencia" (padrão) ou "data_vencimento" (só se a pergunta falar de vencimento)
- "agrupar_por": uma de ["departamento","categoria","status","tipo","contraparte","centro_custo","metodo_pagamento","mes"] ou null
- "ordem": "desc" ou "asc"
- "limite": inteiro de 1 a 50 (padrão 10)
- "ids": lista de IDs FIN-NNNN citados
- "foco_contagem": true se a pergunta pede quantidade de lançamentos
Os dados cobrem 2025-01-01 a 2026-12-31. Não invente filtros que a pergunta não pede."""


def _canon(values: Any, allowed: set[str] | list[str]) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    by_norm = {normalize(a): a for a in allowed}
    out = []
    for v in values:
        c = by_norm.get(normalize(str(v)))
        if c is None:
            raise ValueError(f"valor fora do domínio: {v}")
        if c not in out:
            out.append(c)
    return out


def _vocab() -> dict[str, list[str]]:
    rows = db.fetch_all("SELECT DISTINCT departamento, categoria, centro_custo FROM lancamentos_financeiros")
    return {
        "departamentos": sorted({r["departamento"] for r in rows}),
        "categorias": sorted({r["categoria"] for r in rows}),
        "centros": sorted({r["centro_custo"] for r in rows}),
    }


def validate_llm_params(raw: dict[str, Any], vocab: dict[str, list[str]]) -> FinParams:
    op = raw.get("operacao")
    if op not in OPERACOES:
        raise ValueError(f"operação inválida: {op}")
    tipo = raw.get("tipo")
    if tipo is not None and tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo}")
    agrupar = raw.get("agrupar_por")
    if agrupar is not None and agrupar not in DIMENSOES:
        raise ValueError(f"agrupar_por inválido: {agrupar}")
    campo = raw.get("campo_data") or "data_competencia"
    if campo not in CAMPOS_DATA:
        raise ValueError(f"campo_data inválido: {campo}")
    di = date.fromisoformat(raw["data_inicio"]) if raw.get("data_inicio") else None
    df = date.fromisoformat(raw["data_fim"]) if raw.get("data_fim") else None
    if (di is None) != (df is None) or (di and df and di > df):
        raise ValueError("período inconsistente")
    limite = int(raw.get("limite") or 10)
    ids = [str(i).upper() for i in raw.get("ids") or []]
    if any(not re.fullmatch(r"FIN-\d{4}", i) for i in ids):
        raise ValueError("ID de lançamento inválido")
    return FinParams(
        operacao=op, tipo=tipo, status=_canon(raw.get("status"), STATUS),
        departamentos=_canon(raw.get("departamentos"), vocab["departamentos"]),
        categorias=_canon(raw.get("categorias"), vocab["categorias"]),
        centros_custo=_canon(raw.get("centros_custo"), vocab["centros"]),
        data_inicio=di, data_fim=df, campo_data=campo, agrupar_por=agrupar,
        ordem="asc" if raw.get("ordem") == "asc" else "desc", limite=max(1, min(limite, 50)),
        ids=ids, foco_contagem=bool(raw.get("foco_contagem")),
    )


def extract_params(question: str) -> tuple[FinParams, str, str | None]:
    """Retorna (parâmetros, método, erro_llm)."""
    rules = parse_rules(question)
    llm = get_llm()
    if not llm.enabled:
        return rules, "regras", None
    try:
        vocab = _vocab()
        system = _SYSTEM_EXTRACAO.format(**{k: ", ".join(v) for k, v in vocab.items()})
        params = validate_llm_params(llm.json_chat(system, question), vocab)
        # salvaguarda: se o LLM esqueceu um período que as regras encontraram com segurança, usa o das regras
        if params.period is None and rules.period is not None:
            params.data_inicio, params.data_fim = rules.data_inicio, rules.data_fim
        return params, "llm", None
    except (LLMError, ValueError, KeyError, TypeError) as exc:
        log.warning("Extração via LLM falhou (%s); usando regras.", exc)
        return rules, "regras (fallback)", str(exc)


# =========================================================================== SQL determinístico

def _where(p: FinParams, include_tipo: bool = True) -> tuple[str, list[Any]]:
    clauses, params = [], []
    if include_tipo and p.tipo:
        clauses.append("tipo = %s")
        params.append(p.tipo)
    if p.status:
        clauses.append("status = ANY(%s)")
        params.append(p.status)
    if p.departamentos:
        clauses.append("departamento = ANY(%s)")
        params.append(p.departamentos)
    if p.categorias:
        clauses.append("categoria = ANY(%s)")
        params.append(p.categorias)
    if p.centros_custo:
        clauses.append("centro_custo = ANY(%s)")
        params.append(p.centros_custo)
    if p.period:
        campo = p.campo_data if p.campo_data in CAMPOS_DATA else "data_competencia"
        clauses.append(f"{campo} BETWEEN %s AND %s")
        params.extend([p.data_inicio, p.data_fim])
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _criterio(p: FinParams, include_tipo: bool = True) -> str:
    partes = []
    if include_tipo:
        partes.append(f"tipo = {p.tipo}" if p.tipo else "todos os tipos")
    partes.append("status = " + "/".join(p.status) if p.status else "todos os status")
    if p.departamentos:
        partes.append("departamento = " + ", ".join(p.departamentos))
    if p.categorias:
        partes.append("categoria = " + ", ".join(p.categorias))
    if p.centros_custo:
        partes.append("centro de custo = " + ", ".join(p.centros_custo))
    campo = "data de vencimento" if p.campo_data == "data_vencimento" else "data de competência"
    partes.append(f"{campo} em {p.period.label()}" if p.period else "todo o período disponível (2025–2026)")
    return "; ".join(partes)


def _op_total(p: FinParams) -> AgentResult:
    where, params = _where(p)
    rows = db.fetch_all(
        f"SELECT tipo, status, COUNT(*) AS n, SUM(valor_brl) AS total FROM lancamentos_financeiros {where} "
        "GROUP BY tipo, status ORDER BY tipo, status", params)
    if not rows:
        return AgentResult(f"Nenhum lançamento encontrado com o critério: {_criterio(p)}.",
                           [FONTE_LANC], status="nao_encontrado")
    por_tipo: dict[str, dict[str, Any]] = {}
    for r in rows:
        agg = por_tipo.setdefault(r["tipo"], {"n": 0, "total": Decimal("0"), "status": {}})
        agg["n"] += r["n"]
        agg["total"] += r["total"]
        agg["status"][r["status"]] = (r["n"], r["total"])

    linhas = []
    for tipo, agg in por_tipo.items():
        rotulo = {"Receita": "receitas", "Despesa": "despesas"}[tipo]
        if p.foco_contagem:
            linhas.append(f"**{plural(agg['n'], 'lançamento')}** de {rotulo}, somando {brl(agg['total'])}.")
        else:
            linhas.append(f"Total de {rotulo}: **{brl(agg['total'])}** ({plural(agg['n'], 'lançamento')}).")
        if not p.status and len(agg["status"]) > 1:
            det = "; ".join(f"{s}: {brl(v[1])} ({v[0]})" for s, v in sorted(agg["status"].items()))
            linhas.append(f"Por status — {det}.")
    nota = ""
    if p.tipo == "Despesa" and not p.status:
        nota = ("\n\nObservação: considerei todos os status (despesas incorridas). Se a pergunta for sobre valores "
                "efetivamente pagos, o critério correto é status = Pago (regra de indicadores_e_regras.json).")
    resposta = "\n".join(linhas) + f"\n\nCritério: {_criterio(p)}." + nota
    tabela = [{"tipo": r["tipo"], "status": r["status"], "lançamentos": r["n"], "total": brl(r["total"])} for r in rows]
    return AgentResult(resposta, [FONTE_LANC, FONTE_REGRAS], tabela=tabela,
                       detalhes={"valores": {t: str(a["total"]) for t, a in por_tipo.items()}})


def _op_agrupar(p: FinParams) -> AgentResult:
    dim = p.agrupar_por or "departamento"
    expr = DIMENSOES.get(dim) or f"to_char({p.campo_data}, 'YYYY-MM')"
    where, params = _where(p)
    ordem = "ASC" if p.ordem == "asc" else "DESC"
    order_by = "grupo ASC" if dim == "mes" else f"total {ordem}"
    rows = db.fetch_all(
        f"SELECT {expr} AS grupo, COUNT(*) AS n, SUM(valor_brl) AS total FROM lancamentos_financeiros {where} "
        f"GROUP BY 1 ORDER BY {order_by} LIMIT %s", params + [p.limite if dim != "mes" else 100])
    if not rows:
        return AgentResult(f"Nenhum lançamento encontrado com o critério: {_criterio(p)}.",
                           [FONTE_LANC], status="nao_encontrado")
    nome_dim = {"departamento": "O departamento", "categoria": "A categoria", "status": "O status",
                "tipo": "O tipo", "contraparte": "A contraparte", "centro_custo": "O centro de custo",
                "metodo_pagamento": "O método de pagamento", "mes": "O mês"}[dim]
    if dim == "mes":
        destaque = max(rows, key=lambda r: r["total"]) if p.ordem == "desc" else min(rows, key=lambda r: r["total"])
    else:
        destaque = rows[0]
    adj = "menor" if p.ordem == "asc" else "maior"
    resposta = (f"{nome_dim} com {adj} valor é **{destaque['grupo']}**: {brl(destaque['total'])} "
                f"({plural(destaque['n'], 'lançamento')}).")
    if len(rows) > 1:
        total = sum(r["total"] for r in rows)
        plurais = {"departamento": ("departamento", "departamentos"), "categoria": ("categoria", "categorias"),
                   "status": ("status", "status"), "tipo": ("tipo", "tipos"), "mes": ("mês", "meses"),
                   "contraparte": ("contraparte", "contrapartes"), "centro_custo": ("centro de custo", "centros de custo"),
                   "metodo_pagamento": ("método", "métodos")}
        sing, plur = plurais[dim]
        resposta += f" Somando {plural(len(rows), sing, plur)}, o total é {brl(total)}."
    resposta += f"\n\nCritério: {_criterio(p)}."
    tabela = [{nome_dim.split(" ", 1)[1]: r["grupo"], "lançamentos": r["n"], "total": brl(r["total"])} for r in rows]
    return AgentResult(resposta, [FONTE_LANC], tabela=tabela)


def _op_maiores(p: FinParams) -> AgentResult:
    where, params = _where(p)
    ordem = "ASC" if p.ordem == "asc" else "DESC"
    rows = db.fetch_all(
        "SELECT id_lancamento, data_competencia, tipo, categoria, descricao, departamento, contraparte, "
        f"valor_brl, status FROM lancamentos_financeiros {where} ORDER BY valor_brl {ordem}, id_lancamento LIMIT %s",
        params + [p.limite])
    if not rows:
        return AgentResult(f"Nenhum lançamento encontrado com o critério: {_criterio(p)}.",
                           [FONTE_LANC], status="nao_encontrado")
    adj = "menores" if p.ordem == "asc" else "maiores"
    no_texto = rows[:5]
    resposta = (f"Os {len(rows)} {adj} lançamentos" + (f" (os 5 primeiros abaixo; todos em \"Ver dados\")" if len(rows) > 5 else "") + ":\n\n"
                + "\n".join(f"- {r['id_lancamento']} ({br_date(r['data_competencia'])}) — {r['tipo']}, "
                            f"{r['categoria']} / {r['descricao']}, {r['departamento']}: **{brl(r['valor_brl'])}** "
                            f"[{r['status']}]" for r in no_texto)
                + f"\n\nCritério: {_criterio(p)}.")
    tabela = [{"id": r["id_lancamento"], "competência": br_date(r["data_competencia"]), "tipo": r["tipo"],
               "categoria": r["categoria"], "departamento": r["departamento"], "valor": brl(r["valor_brl"]),
               "status": r["status"]} for r in rows]
    return AgentResult(resposta, [FONTE_LANC], ids_consultados=[r["id_lancamento"] for r in rows], tabela=tabela)


def _orc_where(p: FinParams) -> tuple[str, list[Any]]:
    clauses, params = [], []
    if p.period:
        clauses.append("make_date(ano, mes::int, 1) BETWEEN %s AND %s")
        params.extend([p.data_inicio.replace(day=1), p.data_fim])
    deps = list(p.departamentos) + [CC_DEPT[c] for c in p.centros_custo if c in CC_DEPT]
    if deps:
        clauses.append("departamento = ANY(%s)")
        params.append(deps)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _op_orcamento(p: FinParams) -> AgentResult:
    where, params = _orc_where(p)
    ordem = "ASC" if p.ordem == "asc" else "DESC"
    rows = db.fetch_all(
        f"SELECT departamento, centro_custo, COUNT(*) AS meses, SUM(orcamento_brl) AS total FROM orcamento_mensal "
        f"{where} GROUP BY departamento, centro_custo ORDER BY total {ordem}", params)
    periodo = p.period.label() if p.period else "todo o período disponível (2025–2026)"
    if not rows:
        return AgentResult(f"Não há orçamento registrado para {periodo}.", [FONTE_ORC], status="nao_encontrado")
    total = sum(r["total"] for r in rows)
    if p.agrupar_por == "departamento" and len(rows) > 1:
        adj = "menor" if p.ordem == "asc" else "maior"
        top = rows[0]
        empate = [r["departamento"] for r in rows if r["total"] == top["total"]]
        nome = " e ".join(empate)
        resposta = (f"O departamento com {adj} orçamento em {periodo} é **{nome}** ({top['centro_custo']}), "
                    f"com **{brl(top['total'])}**. O total orçado no período é {brl(total)}.")
    elif len(rows) == 1:
        resposta = (f"Orçamento aprovado de {rows[0]['departamento']} em {periodo}: **{brl(total)}**.")
    else:
        resposta = (f"Orçamento aprovado em {periodo}: **{brl(total)}**, somando "
                    f"{plural(len(rows), 'departamento')}.")
    resposta += "\n\nCritério: soma de orcamento_brl por departamento no período (versão Aprovado)."
    tabela = [{"departamento": r["departamento"], "centro de custo": r["centro_custo"], "meses": r["meses"],
               "orçamento": brl(r["total"])} for r in rows]
    return AgentResult(resposta, [FONTE_ORC], tabela=tabela, detalhes={"total": str(total)})


def _op_execucao(p: FinParams) -> AgentResult:
    p_desp = FinParams(**{**p.__dict__, "tipo": "Despesa", "status": ["Pago"], "campo_data": "data_competencia"})
    w_desp, params_desp = _where(p_desp)
    w_orc, params_orc = _orc_where(p)
    rows = db.fetch_all(
        f"""
        WITH orc AS (SELECT centro_custo, departamento, SUM(orcamento_brl) AS orcado FROM orcamento_mensal {w_orc}
                     GROUP BY centro_custo, departamento),
             real AS (SELECT centro_custo, SUM(valor_brl) AS realizado FROM lancamentos_financeiros {w_desp}
                      GROUP BY centro_custo)
        SELECT orc.departamento, orc.centro_custo, orc.orcado, COALESCE(real.realizado, 0) AS realizado
        FROM orc LEFT JOIN real USING (centro_custo) ORDER BY orc.centro_custo
        """, params_orc + params_desp)
    if not rows:
        return AgentResult("Não há orçamento para o período/departamento informado.", [FONTE_ORC],
                           status="nao_encontrado")
    tot_orc = sum(r["orcado"] for r in rows)
    tot_real = sum(r["realizado"] for r in rows)
    periodo = p.period.label() if p.period else "todo o período disponível (2025–2026)"
    com_orc = [r for r in rows if r["orcado"]]
    resposta = (f"Execução orçamentária em {periodo}: **{pct(tot_real / tot_orc) if tot_orc else 'n/d'}** "
                f"({brl(tot_real)} realizados de {brl(tot_orc)} orçados).")
    if len(com_orc) > 1:
        alto = max(com_orc, key=lambda r: r["realizado"] / r["orcado"])
        baixo = min(com_orc, key=lambda r: r["realizado"] / r["orcado"])
        resposta += (f" Maior execução: {alto['departamento']} ({pct(alto['realizado'] / alto['orcado'])}); "
                     f"menor: {baixo['departamento']} ({pct(baixo['realizado'] / baixo['orcado'])}).")
    resposta += ("\n\nCritério: despesas com status Pago por data de competência ÷ orçamento aprovado do mesmo "
                 "período e centro de custo (definição de indicadores_e_regras.json).")
    tabela = [{"departamento": r["departamento"], "orçado": brl(r["orcado"]), "realizado": brl(r["realizado"]),
               "execução": pct(r["realizado"] / r["orcado"]) if r["orcado"] else "n/d"} for r in rows]
    return AgentResult(resposta, [FONTE_LANC, FONTE_ORC, FONTE_REGRAS], tabela=tabela)


def _op_inadimplencia(p: FinParams) -> AgentResult:
    p2 = FinParams(**{**p.__dict__, "tipo": "Receita", "status": []})
    where, params = _where(p2)
    r = db.fetch_one(
        "SELECT COALESCE(SUM(valor_brl), 0) AS total, "
        "COALESCE(SUM(valor_brl) FILTER (WHERE status = 'Atrasado'), 0) AS atrasado, "
        "COUNT(*) AS n, COUNT(*) FILTER (WHERE status = 'Atrasado') AS n_atrasado "
        f"FROM lancamentos_financeiros {where}", params)
    if not r or not r["total"]:
        return AgentResult(f"Não há receitas registradas com o critério: {_criterio(p2)}.", [FONTE_LANC],
                           status="nao_encontrado")
    resposta = (f"Inadimplência de recebíveis: **{pct(r['atrasado'] / r['total'])}** — {brl(r['atrasado'])} "
                f"em receitas atrasadas ({plural(r['n_atrasado'], 'lançamento')}) de {brl(r['total'])} em receitas "
                f"registradas ({plural(r['n'], 'lançamento')}).\n\nCritério: receitas com status Atrasado ÷ total de receitas; {_criterio(p2, False)}.")
    return AgentResult(resposta, [FONTE_LANC, FONTE_REGRAS])


def _op_lancamento(p: FinParams) -> AgentResult:
    rows = db.fetch_all("SELECT * FROM lancamentos_financeiros WHERE id_lancamento = ANY(%s) ORDER BY 1", [p.ids])
    encontrados = {r["id_lancamento"] for r in rows}
    faltando = [i for i in p.ids if i not in encontrados]
    partes = [
        f"**{r['id_lancamento']}** — {r['tipo']} de **{brl(r['valor_brl'])}**, {r['categoria']} / {r['descricao']}, "
        f"{r['departamento']} ({r['centro_custo']}), contraparte {r['contraparte']}. Competência "
        f"{br_date(r['data_competencia'])}, vencimento {br_date(r['data_vencimento'])}, status **{r['status']}**"
        + (f", via {r['metodo_pagamento']}" if r["metodo_pagamento"] else "") + "."
        for r in rows]
    if faltando:
        partes.append(f"Não encontrei o(s) lançamento(s) {', '.join(faltando)} na base.")
    return AgentResult("\n\n".join(partes), [FONTE_LANC], ids_consultados=p.ids,
                       status="ok" if rows else "nao_encontrado")


HANDLERS = {
    "total": _op_total, "agrupar": _op_agrupar, "maiores_lancamentos": _op_maiores,
    "orcamento": _op_orcamento, "execucao_orcamentaria": _op_execucao,
    "inadimplencia": _op_inadimplencia, "lancamento": _op_lancamento,
}


def _tem_alvo(question: str, p: FinParams) -> bool:
    """A pergunta precisa dizer O QUE medir: um termo financeiro ou algum filtro concreto."""
    from app.router import keyword_scores

    return bool(keyword_scores(question)["financeiro"] > 0 or p.tipo or p.status or p.departamentos
                or p.categorias or p.centros_custo or p.ids)


def _esclarecimento() -> AgentResult:
    return AgentResult(
        "Não identifiquei qual informação financeira você quer consultar. Diga o que medir e, se possível, o "
        "período. Exemplos:\n"
        "- Quanto foi gasto em despesas pagas em março de 2025?\n"
        "- Qual departamento teve o maior orçamento em janeiro de 2026?\n"
        "- Quais as 5 maiores despesas de 2026?\n\n"
        "Se a dúvida for sobre uma regra (por exemplo, quem aprova uma compra), ela é respondida pelas "
        "políticas internas.",
        [], status="esclarecimento",
        opcoes=[{"dominio": "informacoes_internas", "rotulo": "Informações internas"}])


def answer(question: str) -> AgentResult:
    params, metodo, erro_llm = extract_params(question)
    if params.operacao == "nao_identificado" or not _tem_alvo(question, params):
        result = _esclarecimento()
    else:
        result = HANDLERS[params.operacao](params)
    result.llm_usado = metodo == "llm"
    result.detalhes.update({"parametros": params.as_dict(), "extracao": metodo})
    if erro_llm:
        result.detalhes["erro_llm"] = erro_llm
    if result.status == "esclarecimento":
        return result
    result.resposta += "\n\n_Dados sintéticos de demonstração; não representam transações reais._"
    return result
