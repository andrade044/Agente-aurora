"""Ingestão das bases de conhecimento no PostgreSQL.

Executado na inicialização da API (idempotente) ou manualmente:
    python -m app.ingest
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app import db
from app.config import ROOT_DIR, settings
from app.llm import LLMError, get_llm

log = logging.getLogger("aurora.ingest")

TIPOS = {"Receita", "Despesa"}
STATUS_FIN = {"Pago", "Pendente", "Atrasado"}


@dataclass
class IngestReport:
    carregados: dict[str, int] = field(default_factory=dict)
    rejeitados: dict[str, list[str]] = field(default_factory=dict)
    chunks: int = 0
    embeddings_gerados: int = 0
    embeddings_erro: str | None = None

    def reject(self, tabela: str, motivo: str) -> None:
        self.rejeitados.setdefault(tabela, []).append(motivo)


# --------------------------------------------------------------------------- helpers

def _read_csv(path: Path) -> list[dict[str, str]]:
    # utf-8-sig remove o BOM presente nos arquivos do pacote
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _dec(value: str) -> Decimal:
    d = Decimal(value.strip())
    if d < 0:
        raise InvalidOperation("valor negativo")
    return d.quantize(Decimal("0.01"))


def _date(value: str) -> date | None:
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def _none_if_empty(value: str | None) -> str | None:
    return value.strip() if value and value.strip() else None


def load_json(relative: str) -> dict | list:
    return json.loads((settings.data_dir / relative).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- schema

def apply_schema() -> None:
    schema = (settings.data_dir / "sql" / "schema.sql").read_text(encoding="utf-8")
    extra = (ROOT_DIR / "app" / "sql" / "extra.sql").read_text(encoding="utf-8")
    with db.get_pool().connection() as conn:
        conn.execute(schema)
        conn.execute(extra)


# --------------------------------------------------------------------------- tabelas

def _ingest_lancamentos(conn, report: IngestReport) -> None:
    rows = []
    for r in _read_csv(settings.data_dir / "financeiro" / "lancamentos_financeiros.csv"):
        try:
            if r["tipo"] not in TIPOS or r["status"] not in STATUS_FIN:
                raise ValueError(f"enum inválido tipo={r['tipo']} status={r['status']}")
            rows.append((
                r["id_lancamento"], _date(r["data_competencia"]), _date(r["data_vencimento"]),
                r["tipo"], r["categoria"], r["descricao"], r["centro_custo"], r["departamento"],
                r["contraparte"], _dec(r["valor_brl"]), r["status"],
                _none_if_empty(r.get("metodo_pagamento")), _none_if_empty(r.get("observacao")),
            ))
        except (ValueError, InvalidOperation, KeyError) as exc:
            report.reject("lancamentos_financeiros", f"{r.get('id_lancamento')}: {exc}")
    conn.execute("TRUNCATE lancamentos_financeiros")
    with conn.cursor().copy(
        "COPY lancamentos_financeiros (id_lancamento, data_competencia, data_vencimento, tipo, "
        "categoria, descricao, centro_custo, departamento, contraparte, valor_brl, status, "
        "metodo_pagamento, observacao) FROM STDIN"
    ) as copy:
        for row in rows:
            copy.write_row(row)
    report.carregados["lancamentos_financeiros"] = len(rows)


def _ingest_orcamento(conn, report: IngestReport) -> None:
    rows = []
    for r in _read_csv(settings.data_dir / "financeiro" / "orcamento_mensal.csv"):
        try:
            ano, mes = int(r["ano"]), r["mes"].zfill(2)
            if not 1 <= int(mes) <= 12:
                raise ValueError(f"mês inválido {mes}")
            rows.append((ano, mes, r["centro_custo"], r["departamento"], _dec(r["orcamento_brl"]),
                         r["versao_orcamento"], _none_if_empty(r.get("observacao"))))
        except (ValueError, InvalidOperation, KeyError) as exc:
            report.reject("orcamento_mensal", f"{r.get('ano')}-{r.get('mes')}-{r.get('centro_custo')}: {exc}")
    conn.execute("TRUNCATE orcamento_mensal")
    with conn.cursor().copy(
        "COPY orcamento_mensal (ano, mes, centro_custo, departamento, orcamento_brl, "
        "versao_orcamento, observacao) FROM STDIN"
    ) as copy:
        for row in rows:
            copy.write_row(row)
    report.carregados["orcamento_mensal"] = len(rows)


def _ingest_manifestacoes(conn, report: IngestReport) -> None:
    ref = load_json("ouvidoria/referencia_ouvidoria.json")
    status_ok, prio_ok, cat_ok = set(ref["status_validos"]), set(ref["prioridades_validas"]), set(ref["categorias"])
    rows = []
    for r in _read_csv(settings.data_dir / "ouvidoria" / "manifestacoes.csv"):
        try:
            if not re.fullmatch(r"OUV-\d{4}", r["protocolo"]):
                raise ValueError("protocolo fora do formato OUV-NNNN")
            if r["status"] not in status_ok or r["prioridade"] not in prio_ok or r["categoria"] not in cat_ok:
                raise ValueError(f"enum inválido status={r['status']} prioridade={r['prioridade']} categoria={r['categoria']}")
            rows.append((
                r["protocolo"], _date(r["data_abertura"]), r["categoria"], r["assunto"],
                r["canal_entrada"], r["prioridade"], r["status"], r["area_responsavel"],
                r["resumo_manifestacao"], _date(r.get("data_resposta", "")),
                _none_if_empty(r.get("resposta_resumo")), int(r["prazo_referencia_dias"]),
                _none_if_empty(r.get("dados_pessoais")), _none_if_empty(r.get("observacao")),
            ))
        except (ValueError, KeyError) as exc:
            report.reject("manifestacoes_ouvidoria", f"{r.get('protocolo')}: {exc}")
    conn.execute("TRUNCATE manifestacoes_ouvidoria")
    with conn.cursor().copy(
        "COPY manifestacoes_ouvidoria (protocolo, data_abertura, categoria, assunto, canal_entrada, "
        "prioridade, status, area_responsavel, resumo_manifestacao, data_resposta, resposta_resumo, "
        "prazo_referencia_dias, dados_pessoais, observacao) FROM STDIN"
    ) as copy:
        for row in rows:
            copy.write_row(row)
    report.carregados["manifestacoes_ouvidoria"] = len(rows)


# --------------------------------------------------------------------------- RAG

@dataclass
class Chunk:
    id: str
    source: str
    version: str | None
    title: str
    content: str
    domain: str = "informacoes_internas"

    @property
    def hash(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.content}".encode()).hexdigest()


_VERSION_RE = re.compile(r"Vers[aã]o\s+([\d.]+)\s+—\s+([\d/]+)")


def _slug(text: str) -> str:
    from app.textutils import normalize
    return re.sub(r"[^a-z0-9]+", "-", normalize(text)).strip("-")[:40] or "secao"


def build_chunks() -> list[Chunk]:
    """Divide cada Markdown por seções `##`; cada item do FAQ vira um chunk próprio."""
    base = settings.data_dir / "informacoes_internas"
    chunks: list[Chunk] = []
    for path in sorted(base.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        lines = text.splitlines()
        doc_title = lines[0].lstrip("# ").strip() if lines else path.stem
        vm = _VERSION_RE.search(text)
        version = f"{vm.group(1)} ({vm.group(2)})" if vm else None

        sections: list[tuple[str, list[str]]] = [("Geral", [])]
        for line in lines[1:]:
            if "Documento fictício para avaliação" in line:
                continue  # aviso padrão de todos os arquivos; a versão já vai para os metadados
            if line.startswith("## "):
                sections.append((line[3:].strip(), []))
            else:
                sections[-1][1].append(line)
        for name, body in sections:
            content = "\n".join(body).strip()
            if not content:
                continue
            title = doc_title if name == "Geral" else f"{doc_title} — {name}"
            chunks.append(Chunk(f"{path.name}#{_slug(name)}", path.name, version, title, content))

    for item in load_json("informacoes_internas/faq_interno.json"):
        chunks.append(Chunk(
            f"faq_interno.json#{item['id']}", item["documento"], None,
            f"FAQ {item['id']}: {item['pergunta']}", item["resposta"],
        ))
    return chunks


def _ingest_chunks(report: IngestReport) -> None:
    chunks = build_chunks()
    llm = get_llm()
    existing = {
        r["id"]: r for r in db.fetch_all("SELECT id, content_hash, embedding_model, embedding IS NOT NULL AS has_emb FROM rag_chunks")
    }
    need_embedding = [
        c for c in chunks
        if llm.enabled and not (
            c.id in existing and existing[c.id]["content_hash"] == c.hash
            and existing[c.id]["has_emb"] and existing[c.id]["embedding_model"] == llm.embedding_model
        )
    ]
    embeddings: dict[str, list[float]] = {}
    if need_embedding:
        try:
            vectors = llm.embed([f"{c.title}\n{c.content}" for c in need_embedding])
            embeddings = {c.id: v for c, v in zip(need_embedding, vectors)}
            report.embeddings_gerados = len(embeddings)
        except LLMError as exc:
            report.embeddings_erro = str(exc)
            log.warning("Falha ao gerar embeddings, RAG seguirá só com busca lexical: %s", exc)

    with db.get_pool().connection() as conn:
        ids = [c.id for c in chunks]
        conn.execute("DELETE FROM rag_chunks WHERE NOT (id = ANY(%s))", (ids,))
        for c in chunks:
            conn.execute(
                """
                INSERT INTO rag_chunks (id, domain, source, document_version, title, content, content_hash,
                                        embedding_model, embedding)
                VALUES (%(id)s, %(domain)s, %(source)s, %(version)s, %(title)s, %(content)s, %(hash)s,
                        %(model)s, %(emb)s)
                ON CONFLICT (id) DO UPDATE SET
                    domain = EXCLUDED.domain, source = EXCLUDED.source,
                    document_version = EXCLUDED.document_version, title = EXCLUDED.title,
                    content = EXCLUDED.content, content_hash = EXCLUDED.content_hash,
                    embedding_model = COALESCE(EXCLUDED.embedding_model,
                        CASE WHEN rag_chunks.content_hash = EXCLUDED.content_hash THEN rag_chunks.embedding_model END),
                    embedding = COALESCE(EXCLUDED.embedding,
                        CASE WHEN rag_chunks.content_hash = EXCLUDED.content_hash THEN rag_chunks.embedding END)
                """,
                {"id": c.id, "domain": c.domain, "source": c.source, "version": c.version,
                 "title": c.title, "content": c.content, "hash": c.hash,
                 "model": llm.embedding_model if c.id in embeddings else None,
                 "emb": embeddings.get(c.id)},
            )
    report.chunks = len(chunks)


# --------------------------------------------------------------------------- orquestração

def run_ingestion() -> IngestReport:
    report = IngestReport()
    apply_schema()
    with db.get_pool().connection() as conn:
        with conn.transaction():
            _ingest_lancamentos(conn, report)
            _ingest_orcamento(conn, report)
            _ingest_manifestacoes(conn, report)
    _ingest_chunks(report)
    log.info("Ingestão concluída: %s | chunks=%s | embeddings=%s | rejeitados=%s",
             report.carregados, report.chunks, report.embeddings_gerados,
             {k: len(v) for k, v in report.rejeitados.items()})
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db.init_pool()
    try:
        rep = run_ingestion()
    finally:
        db.close_pool()
    print(json.dumps({"carregados": rep.carregados, "rejeitados": rep.rejeitados, "chunks": rep.chunks,
                      "embeddings_gerados": rep.embeddings_gerados, "embeddings_erro": rep.embeddings_erro},
                     ensure_ascii=False, indent=2))
