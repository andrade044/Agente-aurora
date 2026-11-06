"""Configuração dos testes.

Os testes rodam em modo determinístico (LLM_PROVIDER=none). O comportamento com LLM é testado com um
cliente falso (FakeLLM), sem chamadas de rede. Testes que precisam do banco são pulados se ele não estiver
acessível (configure POSTGRES_* ou DATABASE_URL).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["LLM_PROVIDER"] = "none"
os.environ.setdefault("LOGS_DIR", tempfile.mkdtemp(prefix="aurora-logs-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.llm import LLMClient, LLMError, NullClient, set_llm  # noqa: E402


class FakeLLM(LLMClient):
    """Cliente falso: devolve respostas programadas por função."""

    enabled = True
    name = "fake"

    def __init__(self, json_fn=None, text_fn=None):
        self.json_fn = json_fn
        self.text_fn = text_fn
        self.calls: list[tuple[str, str]] = []

    def json_chat(self, system, user):
        self.calls.append(("json", user))
        if self.json_fn is None:
            raise LLMError("sem resposta programada")
        return self.json_fn(system, user)

    def text_chat(self, system, user):
        self.calls.append(("text", user))
        if self.text_fn is None:
            raise LLMError("sem resposta programada")
        return self.text_fn(system, user)

    def embed(self, texts):
        raise LLMError("embeddings indisponíveis no FakeLLM")


@pytest.fixture
def fake_llm():
    clients = []

    def _install(**kwargs):
        c = FakeLLM(**kwargs)
        set_llm(c)
        clients.append(c)
        return c

    yield _install
    set_llm(NullClient())


@pytest.fixture(autouse=True)
def _reset_llm():
    set_llm(NullClient())
    yield
    set_llm(NullClient())


@pytest.fixture(scope="session")
def database():
    from app import db, rag
    from app.ingest import run_ingestion

    try:
        db.init_pool(retries=2, delay_s=0.5)
    except RuntimeError as exc:
        pytest.skip(f"PostgreSQL indisponível: {exc}")
    set_llm(NullClient())
    run_ingestion()
    rag.load_index()
    yield db
    db.close_pool()
