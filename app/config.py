"""Configuração centralizada, lida de variáveis de ambiente (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env(
            "DATABASE_URL",
            "postgresql://{u}:{p}@{h}:{port}/{db}".format(
                u=_env("POSTGRES_USER", "aurora"),
                p=_env("POSTGRES_PASSWORD", "aurora"),
                h=_env("POSTGRES_HOST", "localhost"),
                port=_env("POSTGRES_PORT", "5432"),
                db=_env("POSTGRES_DB", "aurora"),
            ),
        )
    )
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT_DIR / "data"))))
    logs_dir: Path = field(default_factory=lambda: Path(_env("LOGS_DIR", str(ROOT_DIR / "logs"))))

    # LLM
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openai").lower())
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-6-luna"))
    openai_embedding_model: str = field(
        default_factory=lambda: _env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    )
    openai_base_url: str = field(default_factory=lambda: _env("OPENAI_BASE_URL"))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT_S", "30")))

    # Orquestrador
    router_min_confidence: float = field(
        default_factory=lambda: float(_env("ROUTER_MIN_CONFIDENCE", "0.6"))
    )
    rag_top_k: int = field(default_factory=lambda: int(_env("RAG_TOP_K", "4")))

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "openai" and bool(self.openai_api_key)


settings = Settings()
