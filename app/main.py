"""API FastAPI do agente orquestrador Aurora."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db, interaction_log, rag
from app.config import ROOT_DIR, settings
from app.ingest import run_ingestion
from app.llm import get_llm
from app.orchestrator import handle

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aurora.api")

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_pool()
    if os.getenv("INGEST_ON_STARTUP", "true").lower() != "false":
        report = run_ingestion()
        state["ingestao"] = {"carregados": report.carregados, "chunks": report.chunks,
                             "embeddings_gerados": report.embeddings_gerados,
                             "embeddings_erro": report.embeddings_erro,
                             "rejeitados": {k: len(v) for k, v in report.rejeitados.items()}}
    rag.load_index()
    yield
    db.close_pool()


app = FastAPI(title="Aurora — Agente Orquestrador", version="1.0.0", lifespan=lifespan,
              description="Classifica perguntas e as encaminha aos agentes Financeiro, Informações internas e Ouvidoria.")


class ChatRequest(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=1000, examples=["Qual o status do protocolo OUV-0002?"])
    dominio: Literal["financeiro", "informacoes_internas", "ouvidoria"] | None = Field(
        None, description="Opcional: força o domínio (usado após um pedido de esclarecimento).")


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        db.fetch_one("SELECT 1 AS ok")
        banco = "ok"
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"banco indisponível: {exc}") from exc
    return {"status": "ok", "banco": banco}


@app.get("/api/info")
def info() -> dict[str, Any]:
    llm = get_llm()
    idx = rag.get_index()
    return {
        "llm": {"habilitado": llm.enabled, "provedor": llm.name,
                "modelo": settings.openai_model if llm.enabled else None,
                "modelo_embeddings": settings.openai_embedding_model if llm.enabled else None},
        "rag": {"chunks": len(idx.rows), "embeddings": idx.has_embeddings},
        "ingestao": state.get("ingestao"),
        "limiar_confianca": settings.router_min_confidence,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    pergunta = req.pergunta.strip()
    if not pergunta:
        raise HTTPException(422, "pergunta vazia")
    return await run_in_threadpool(handle, pergunta, req.dominio)


@app.get("/api/logs")
def logs(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    return interaction_log.recent(limit)


@app.get("/api/logs/export", response_class=PlainTextResponse)
def export_logs(limit: int = Query(1000, ge=1, le=10000)) -> PlainTextResponse:
    """Exporta as interações do banco em JSONL (uma por linha), para download."""
    import json

    rows = interaction_log.export(limit)
    body = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) + ("\n" if rows else "")
    return PlainTextResponse(body, media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=interacoes.jsonl"})


@app.post("/api/admin/reingest")
def reingest() -> dict[str, Any]:
    report = run_ingestion()
    rag.load_index()
    return {"carregados": report.carregados, "chunks": report.chunks,
            "embeddings_gerados": report.embeddings_gerados, "embeddings_erro": report.embeddings_erro}


# Frontend estático (deve vir depois das rotas da API)
app.mount("/", StaticFiles(directory=ROOT_DIR / "frontend", html=True), name="frontend")
