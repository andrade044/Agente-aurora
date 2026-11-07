"""Log das interações com o agente: JSONL em logs/ + tabela agent_logs no PostgreSQL."""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from app import db
from app.config import settings

log = logging.getLogger("aurora.log")
_lock = threading.Lock()

_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@(?!aurora\.example\b)[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\(?\b\d{2}\)?\s?9?\d{4}-?\d{4}\b")
_SECRET = re.compile(r"\b(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{32,})\b")


def mask(text: str) -> str:
    """Remove dados pessoais/segredos óbvios antes de gravar (e-mails corporativos fictícios são mantidos)."""
    text = _SECRET.sub("[SEGREDO]", text)
    text = _CPF.sub("[CPF]", text)
    text = _EMAIL.sub("[EMAIL]", text)
    return _PHONE.sub("[TELEFONE]", text)


def log_interaction(entry: dict[str, Any]) -> None:
    entry = dict(entry)
    entry["pergunta"] = mask(entry["pergunta"])
    if entry.get("pergunta_interpretada"):
        entry["pergunta_interpretada"] = mask(entry["pergunta_interpretada"])
    entry.setdefault("pergunta_interpretada", None)
    entry.setdefault("resposta", None)
    entry.setdefault("ts", datetime.now(timezone.utc).isoformat())

    try:
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        with _lock, (settings.logs_dir / "interacoes.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        log.error("Falha ao gravar log JSONL: %s", exc)

    try:
        db.execute(
            """
            INSERT INTO agent_logs (id, ts, pergunta, pergunta_interpretada, resposta, dominio_previsto, confianca,
                                    metodo_classificacao, agente, fontes, ids_consultados, latencia_ms, status, erro,
                                    llm_usado, detalhes)
            VALUES (%(id)s, %(ts)s, %(pergunta)s, %(pergunta_interpretada)s, %(resposta)s, %(dominio_previsto)s, %(confianca)s, %(metodo_classificacao)s,
                    %(agente)s, %(fontes)s, %(ids_consultados)s, %(latencia_ms)s, %(status)s, %(erro)s,
                    %(llm_usado)s, %(detalhes)s)
            """,
            {**entry, "fontes": Jsonb(entry.get("fontes") or []),
             "ids_consultados": Jsonb(entry.get("ids_consultados") or []),
             "detalhes": Jsonb(json.loads(json.dumps(entry.get("detalhes") or {}, default=str)))},
        )
    except Exception as exc:  # noqa: BLE001 - log nunca deve derrubar a resposta
        log.error("Falha ao gravar log no banco: %s", exc)


def recent(limit: int = 50) -> list[dict[str, Any]]:
    return db.fetch_all(
        "SELECT id, ts, pergunta, pergunta_interpretada, dominio_previsto, confianca, metodo_classificacao, agente, fontes, "
        "ids_consultados, latencia_ms, status, erro, llm_usado FROM agent_logs ORDER BY ts DESC LIMIT %s",
        [limit])


def export(limit: int = 1000) -> list[dict[str, Any]]:
    """Todas as colunas, em ordem cronológica (para exportar em JSONL)."""
    rows = db.fetch_all("SELECT * FROM agent_logs ORDER BY ts DESC LIMIT %s", [limit])
    return list(reversed(rows))
