"""Agente de Ouvidoria.

- Busca EXATA por protocolo (OUV-NNNN). Nunca inventa protocolo: sem correspondência => "não encontrado".
- Perguntas sobre valores válidos (status, prioridades, categorias) são respondidas com referencia_ouvidoria.json.
- Contagens e listagens usam filtros parametrizados em SQL.
O LLM (quando disponível) só extrai filtros; as respostas são montadas a partir dos registros.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app import db
from app.agents.base import AgentResult
from app.ingest import load_json
from app.llm import LLMError, get_llm
from app.textutils import Period, br_date, normalize, parse_period, plural

log = logging.getLogger("aurora.ouvidoria")

FONTE_CSV = "manifestacoes.csv"
FONTE_REF = "referencia_ouvidoria.json"
NAO_RESOLVIDOS = ["Aberto", "Em análise", "Aguardando área responsável"]
CANAIS = ["Portal", "E-mail", "Telefone", "Chat"]
DIMENSOES = {"status": "status", "categoria": "categoria", "prioridade": "prioridade",
             "canal": "canal_entrada", "area": "area_responsavel", "mes": "to_char(data_abertura, 'YYYY-MM')"}


def referencia() -> dict:
    return load_json("ouvidoria/referencia_ouvidoria.json")


@dataclass
class OuvParams:
    operacao: str = "contagem"   # protocolo | referencia | contagem | listar | tempo_resposta
    protocolos: list[str] = field(default_factory=list)
    referencia_campo: str | None = None   # status | prioridades | categorias | regras
    status: list[str] = field(default_factory=list)
    categorias: list[str] = field(default_factory=list)
    prioridades: list[str] = field(default_factory=list)
    canais: list[str] = field(default_factory=list)
    data_inicio: date | None = None
    data_fim: date | None = None
    agrupar_por: str | None = None
    limite: int = 10

    @property
    def period(self) -> Period | None:
        return Period(self.data_inicio, self.data_fim) if self.data_inicio and self.data_fim else None

    def as_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["data_inicio"] = self.data_inicio.isoformat() if self.data_inicio else None
        d["data_fim"] = self.data_fim.isoformat() if self.data_fim else None
        return d


def _match_values(t: str, values: list[str]) -> list[str]:
    found = []
    for v in sorted(values, key=len, reverse=True):
        nv = normalize(v)
        if re.search(rf"\b{re.escape(nv)}s?\b", t):
            found.append(v)
            t = t.replace(nv, " ")
    return found


def parse_rules(question: str) -> OuvParams:
    t = normalize(question)
    ref = referencia()
    p = OuvParams()

    p.protocolos = sorted({f"OUV-{int(n):04d}" if len(n) <= 4 else f"OUV-{n}"
                           for n in re.findall(r"\bouv[-\s]?(\d+)\b", t)})
    if p.protocolos:
        p.operacao = "protocolo"
        return p

    contagem = re.search(r"\b(quantos|quantas|quantidade|numero de|total de|volume)\b", t)
    lista_ref = re.search(r"\b(quais|que|lista|liste|existem|possiveis|validos|validas|podem|tipos de)\b", t)
    if not contagem and lista_ref:
        for campo, pat in (("status", r"\bstatus\b"), ("prioridades", r"\bprioridades?\b"),
                           ("categorias", r"\bcategorias?\b"), ("canais", r"\bcana(l|is)\b"),
                           ("regras", r"\bregras?\b")):
            if re.search(pat, t) and not re.search(r"\b(manifestac|protocolos|reclamac)", t):
                p.operacao, p.referencia_campo = "referencia", campo
                return p

    p.categorias = _match_values(t, ref["categorias"])
    p.prioridades = _match_values(t, ref["prioridades_validas"])
    p.canais = _match_values(t, CANAIS)
    if re.search(r"\b(em aberto|pendentes?|nao respondid[oa]s?|sem resposta|nao conclu[ií]d[oa]s?|nao resolvid[oa]s?)\b", t):
        p.status = list(NAO_RESOLVIDOS)
    else:
        st = _match_values(t, ref["status_validos"])
        if not st and re.search(r"\b(abert[oa]s?)\b", t) and not re.search(r"\babert[oa]s?\s+(em|no|na|entre|de)\b", t):
            st = ["Aberto"]
        if not st and re.search(r"\brespondid[oa]s\b", t):
            st = ["Respondido"]
        if not st and re.search(r"\bconcluid[oa]s\b", t):
            st = ["Concluído"]
        p.status = st
    # "reclamações" é o termo genérico para manifestações; não filtra categoria

    period = parse_period(question)
    if period:
        p.data_inicio, p.data_fim = period.start, period.end

    for name, pat in (("status", r"status"), ("categoria", r"categorias?|tipos?|assuntos?"),
                      ("prioridade", r"prioridades?"), ("canal", r"cana(l|is)"),
                      ("area", r"areas?|equipes?|setor(es)?"), ("mes", r"mes|meses")):
        if re.search(rf"\b(por|cada|qual|quais)\s+(o |a |os |as )?({pat})\b", t):
            p.agrupar_por = name
            break

    if re.search(r"\b(tempo medio|prazo medio|tempo de resposta|prazo de resposta|prazo de referencia|prazo da ouvidoria|dentro do prazo|fora do prazo|demora)\b", t):
        p.operacao = "tempo_resposta"
    elif re.search(r"\b(liste|listar|lista|mostre|mostrar|quais sao os protocolos|quais protocolos|quais as manifestac|quais manifestac)\b", t) and not contagem:
        p.operacao = "listar"
    else:
        p.operacao = "contagem"
    return p


_SYSTEM = """Você extrai filtros de perguntas sobre a base de ouvidoria de uma empresa fictícia.
Responda SOMENTE com JSON com as chaves:
- "operacao": "protocolo" | "referencia" | "contagem" | "listar" | "tempo_resposta"
    referencia = a pergunta quer saber quais valores existem/são válidos (status, prioridades, categorias, canais, regras)
- "protocolos": lista de protocolos no formato OUV-NNNN citados na pergunta
- "referencia_campo": "status" | "prioridades" | "categorias" | "canais" | "regras" | null
- "status": lista entre {status}  (use os 3 primeiros não-finais para "em aberto/pendentes/não respondidas")
- "categorias": lista entre {categorias}
- "prioridades": lista entre {prioridades}
- "canais": lista entre {canais}
- "data_inicio", "data_fim": datas ISO do período de abertura pedido, ou null
- "agrupar_por": "status" | "categoria" | "prioridade" | "canal" | "area" | "mes" | null
- "limite": inteiro 1..50
Não invente filtros que a pergunta não pede."""


def _canon(values: Any, allowed: list[str]) -> list[str]:
    if not values:
        return []
    by_norm = {normalize(a): a for a in allowed}
    out = []
    for v in values if isinstance(values, list) else [values]:
        c = by_norm.get(normalize(str(v)))
        if c is None:
            raise ValueError(f"valor fora do domínio: {v}")
        out.append(c)
    return out


def _validate(raw: dict[str, Any], ref: dict) -> OuvParams:
    op = raw.get("operacao")
    if op not in {"protocolo", "referencia", "contagem", "listar", "tempo_resposta"}:
        raise ValueError(f"operação inválida: {op}")
    protos = [str(x).upper() for x in raw.get("protocolos") or []]
    if any(not re.fullmatch(r"OUV-\d{4}", x) for x in protos):
        raise ValueError("protocolo fora do formato")
    campo = raw.get("referencia_campo")
    if campo not in {None, "status", "prioridades", "categorias", "canais", "regras"}:
        raise ValueError("referencia_campo inválido")
    agrupar = raw.get("agrupar_por")
    if agrupar is not None and agrupar not in DIMENSOES:
        raise ValueError("agrupar_por inválido")
    di = date.fromisoformat(raw["data_inicio"]) if raw.get("data_inicio") else None
    df = date.fromisoformat(raw["data_fim"]) if raw.get("data_fim") else None
    if (di is None) != (df is None):
        raise ValueError("período inconsistente")
    return OuvParams(
        operacao=op, protocolos=protos, referencia_campo=campo,
        status=_canon(raw.get("status"), ref["status_validos"]),
        categorias=_canon(raw.get("categorias"), ref["categorias"]),
        prioridades=_canon(raw.get("prioridades"), ref["prioridades_validas"]),
        canais=_canon(raw.get("canais"), CANAIS), data_inicio=di, data_fim=df, agrupar_por=agrupar,
        limite=max(1, min(int(raw.get("limite") or 10), 50)),
    )


def extract_params(question: str) -> tuple[OuvParams, str, str | None]:
    rules = parse_rules(question)
    # protocolos citados explicitamente: regex é exata e suficiente, não gasta chamada de LLM
    if rules.operacao in {"protocolo", "referencia"}:
        return rules, "regras", None
    llm = get_llm()
    if not llm.enabled:
        return rules, "regras", None
    ref = referencia()
    try:
        system = _SYSTEM.format(status=", ".join(ref["status_validos"]), categorias=", ".join(ref["categorias"]),
                                prioridades=", ".join(ref["prioridades_validas"]), canais=", ".join(CANAIS))
        params = _validate(llm.json_chat(system, question), ref)
        if params.period is None and rules.period is not None:
            params.data_inicio, params.data_fim = rules.data_inicio, rules.data_fim
        return params, "llm", None
    except (LLMError, ValueError, KeyError, TypeError) as exc:
        log.warning("Extração via LLM falhou (%s); usando regras.", exc)
        return rules, "regras (fallback)", str(exc)


# =========================================================================== operações

def _where(p: OuvParams) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for col, values in (("status", p.status), ("categoria", p.categorias), ("prioridade", p.prioridades),
                        ("canal_entrada", p.canais)):
        if values:
            clauses.append(f"{col} = ANY(%s)")
            params.append(values)
    if p.period:
        clauses.append("data_abertura BETWEEN %s AND %s")
        params.extend([p.data_inicio, p.data_fim])
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def _criterio(p: OuvParams) -> str:
    partes = []
    if p.status:
        partes.append("status: " + ", ".join(p.status))
    if p.categorias:
        partes.append("categoria: " + ", ".join(p.categorias))
    if p.prioridades:
        partes.append("prioridade: " + ", ".join(p.prioridades))
    if p.canais:
        partes.append("canal: " + ", ".join(p.canais))
    partes.append(f"abertura em {p.period.label()}" if p.period else "todo o período da base")
    return "; ".join(partes)


IDENTIDADE_RE = re.compile(r"\b(quem (abriu|fez|registrou|reclamou)|nome d[oa]|cpf|e-?mail d[oa]|telefone d[oa]|"
                           r"identidade|manifestante)\b")


def _op_protocolo(p: OuvParams, question: str) -> AgentResult:
    rows = db.fetch_all("SELECT * FROM manifestacoes_ouvidoria WHERE protocolo = ANY(%s) ORDER BY protocolo",
                        [p.protocolos])
    achados = {r["protocolo"]: r for r in rows}
    partes = []
    for proto in p.protocolos:
        r = achados.get(proto)
        if r is None:
            partes.append(f"O protocolo **{proto}** não foi encontrado na base de ouvidoria. Confira o número "
                          "informado; não há dados a apresentar para ele.")
            continue
        texto = (f"**{proto}** — status atual: **{r['status']}**.\n"
                 f"- Categoria / assunto: {r['categoria']} / {r['assunto']}\n"
                 f"- Prioridade: {r['prioridade']} · Canal: {r['canal_entrada']}\n"
                 f"- Área responsável: {r['area_responsavel']}\n"
                 f"- Data de abertura: {br_date(r['data_abertura'])}\n")
        if r["data_resposta"]:
            dias = (r["data_resposta"] - r["data_abertura"]).days
            texto += (f"- Data de resposta: {br_date(r['data_resposta'])} ({plural(dias, 'dia')} após a abertura)\n"
                      f"- Resposta: {r['resposta_resumo'] or '—'}\n")
        else:
            texto += "- Ainda sem resposta registrada.\n"
        texto += f"- Resumo: {r['resumo_manifestacao']}"
        if r["status"] == "Respondido":
            texto += "\n\nObs.: \"Respondido\" não significa necessariamente \"Concluído\"."
        texto += (f"\n\nPrazo de referência: {r['prazo_referencia_dias']} dias — parâmetro fictício de demonstração, "
                  "não é prazo legal nem promessa de atendimento.")
        partes.append(texto)
    if IDENTIDADE_RE.search(normalize(question)):
        partes.append("A base não contém dados de identificação do manifestante (nome, CPF, e-mail ou telefone), "
                      "e o agente não infere identidade.")
    return AgentResult("\n\n".join(partes), [FONTE_CSV, FONTE_REF], ids_consultados=p.protocolos,
                       status="ok" if rows else "nao_encontrado")


def _op_referencia(p: OuvParams) -> AgentResult:
    ref = referencia()
    campo = p.referencia_campo or "status"
    if campo == "status":
        itens, titulo = ref["status_validos"], "Os status possíveis de uma manifestação são"
    elif campo == "prioridades":
        itens, titulo = ref["prioridades_validas"], "As prioridades possíveis são"
    elif campo == "categorias":
        itens, titulo = ref["categorias"], "As categorias de manifestação são"
    elif campo == "canais":
        itens, titulo = CANAIS, "Os canais de entrada registrados na base são"
    else:
        itens, titulo = ref["regras"], "Regras de atendimento da ouvidoria"
    resposta = f"{titulo}:\n\n" + "\n".join(f"- {i}" for i in itens)
    if campo == "status":
        resposta += "\n\nObs.: \"Respondido\" não é necessariamente igual a \"Concluído\"."
    fonte = FONTE_CSV if campo == "canais" else FONTE_REF
    return AgentResult(resposta, [fonte])


def _op_contagem(p: OuvParams) -> AgentResult:
    where, params = _where(p)
    total = db.fetch_one(f"SELECT COUNT(*) AS n FROM manifestacoes_ouvidoria {where}", params)["n"]
    dim = p.agrupar_por
    if dim is None and len(p.status) != 1:
        dim = "status"
    rows = []
    if dim:
        expr = DIMENSOES[dim]
        order = "1" if dim == "mes" else "n DESC, 1"
        rows = db.fetch_all(f"SELECT {expr} AS grupo, COUNT(*) AS n FROM manifestacoes_ouvidoria {where} "
                            f"GROUP BY 1 ORDER BY {order}", params)
    resposta = f"Há **{plural(total, 'manifestação', 'manifestações')}** com o critério ({_criterio(p)})."
    if rows:
        resposta += f"\n\nDistribuição por {dim}:\n" + "\n".join(f"- {r['grupo']}: {r['n']}" for r in rows)
    tabela = [{dim: r["grupo"], "manifestações": r["n"]} for r in rows] if rows else None
    return AgentResult(resposta, [FONTE_CSV], tabela=tabela, detalhes={"total": total},
                       status="ok" if total else "nao_encontrado")


def _op_listar(p: OuvParams) -> AgentResult:
    where, params = _where(p)
    rows = db.fetch_all(
        "SELECT protocolo, data_abertura, categoria, assunto, prioridade, status, area_responsavel "
        f"FROM manifestacoes_ouvidoria {where} ORDER BY data_abertura DESC, protocolo LIMIT %s", params + [p.limite])
    total = db.fetch_one(f"SELECT COUNT(*) AS n FROM manifestacoes_ouvidoria {where}", params)["n"]
    if not rows:
        return AgentResult(f"Nenhuma manifestação encontrada com o critério ({_criterio(p)}).", [FONTE_CSV],
                           status="nao_encontrado")
    resposta = (f"{plural(total, 'manifestação', 'manifestações')} com o critério ({_criterio(p)}). "
                f"Mostrando as {len(rows)} mais recentes:\n\n"
                + "\n".join(f"- **{r['protocolo']}** ({br_date(r['data_abertura'])}) — {r['categoria']} / "
                            f"{r['assunto']}, prioridade {r['prioridade']}, status {r['status']}" for r in rows))
    tabela = [{"protocolo": r["protocolo"], "abertura": br_date(r["data_abertura"]), "categoria": r["categoria"],
               "assunto": r["assunto"], "prioridade": r["prioridade"], "status": r["status"]} for r in rows]
    return AgentResult(resposta, [FONTE_CSV], ids_consultados=[r["protocolo"] for r in rows], tabela=tabela)


def _op_tempo(p: OuvParams) -> AgentResult:
    where, params = _where(p)
    extra = ("AND " if where else "WHERE ") + "data_resposta IS NOT NULL"
    r = db.fetch_one(
        "SELECT COUNT(*) AS n, AVG(data_resposta - data_abertura) AS media, "
        "COUNT(*) FILTER (WHERE data_resposta - data_abertura <= prazo_referencia_dias) AS no_prazo "
        f"FROM manifestacoes_ouvidoria {where} {extra}", params)
    if not r["n"]:
        return AgentResult(f"Não há manifestações respondidas com o critério ({_criterio(p)}).", [FONTE_CSV],
                           status="nao_encontrado")
    media = f"{float(r['media']):.1f}".replace(".", ",")
    resposta = (f"Entre as {plural(r['n'], 'manifestação respondida', 'manifestações respondidas')} "
                f"({_criterio(p)}), o tempo médio entre abertura e resposta foi de **{media} dias**; "
                f"{r['no_prazo']} ({round(100 * r['no_prazo'] / r['n'])}%) foram respondidas em até 10 dias.\n\n"
                "O prazo de 10 dias é um parâmetro fictício de demonstração, não prazo legal nem promessa real. "
                "Cálculo: data_resposta − data_abertura (as duas datas são distintas).")
    return AgentResult(resposta, [FONTE_CSV, FONTE_REF])


def answer(question: str) -> AgentResult:
    params, metodo, erro_llm = extract_params(question)
    if params.operacao == "protocolo" and not params.protocolos:
        params.operacao = "contagem"
    if params.operacao == "protocolo":
        result = _op_protocolo(params, question)
    elif params.operacao == "referencia":
        result = _op_referencia(params)
    elif params.operacao == "listar":
        result = _op_listar(params)
    elif params.operacao == "tempo_resposta":
        result = _op_tempo(params)
    else:
        result = _op_contagem(params)
    result.llm_usado = metodo == "llm"
    result.detalhes.update({"parametros": params.as_dict(), "extracao": metodo})
    if erro_llm:
        result.detalhes["erro_llm"] = erro_llm
    return result
