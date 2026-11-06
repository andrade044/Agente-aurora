"""Tipos compartilhados pelos agentes especializados."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    resposta: str
    fontes: list[str] = field(default_factory=list)          # arquivos-fonte consultados
    ids_consultados: list[str] = field(default_factory=list)  # protocolos, lançamentos, chunks
    status: str = "ok"                                        # ok | nao_encontrado | recusado | esclarecimento | fora_de_escopo
    llm_usado: bool = False
    detalhes: dict[str, Any] = field(default_factory=dict)    # parâmetros, SQL, tabela para a UI
    tabela: list[dict[str, Any]] | None = None
    opcoes: list[dict[str, str]] | None = None                # botões de esclarecimento na UI
