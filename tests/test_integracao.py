"""Testes de integração com PostgreSQL: ingestão, agentes, orquestrador e API."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents import financeiro, interno, ouvidoria
from app.orchestrator import handle
from scripts.avaliar import criterios, dominio_ok, fonte_ok, gabarito
from app.textutils import normalize

CASOS = json.loads((Path(__file__).resolve().parent.parent / "data" / "testes" / "perguntas_avaliacao.json")
                   .read_text(encoding="utf-8"))["casos"]


def test_ingestao_contagens(database):
    assert database.fetch_one("SELECT COUNT(*) AS n FROM lancamentos_financeiros")["n"] == 300
    assert database.fetch_one("SELECT COUNT(*) AS n FROM orcamento_mensal")["n"] == 144
    assert database.fetch_one("SELECT COUNT(*) AS n FROM manifestacoes_ouvidoria")["n"] == 180
    assert database.fetch_one("SELECT COUNT(*) AS n FROM rag_chunks")["n"] >= 17


@pytest.mark.parametrize("caso", CASOS, ids=[c["id"] for c in CASOS])
def test_casos_oficiais_modo_deterministico(database, caso):
    r = handle(caso["pergunta"])
    texto = normalize(r["resposta"])
    assert dominio_ok(caso["dominio_esperado"], r["dominio"]), r["dominio"]
    assert fonte_ok(caso["fonte_esperada"], r["fontes"]), r["fontes"]
    for grupo in criterios(gabarito())[caso["id"]]:
        assert any(normalize(t) in texto for t in grupo), (grupo, r["resposta"])


def test_protocolo_inexistente_nao_inventa(database):
    r = ouvidoria.answer("Me mostre o OUV-0999 e o OUV-0001")
    assert "OUV-0999" in r.resposta and "não foi encontrado" in r.resposta
    assert "OUV-0001" in r.resposta and r.status == "ok"


def test_financeiro_com_llm_falso_usa_sql(database, fake_llm):
    fake_llm(json_fn=lambda s, u: {
        "operacao": "total", "tipo": "Despesa", "status": ["Pago"], "departamentos": [], "categorias": [],
        "centros_custo": [], "data_inicio": "2025-01-01", "data_fim": "2025-03-31",
        "campo_data": "data_competencia", "agrupar_por": None, "ordem": "desc", "limite": 10, "ids": [],
        "foco_contagem": False})
    r = financeiro.answer("quanto saiu de despesas pagas no 1º tri de 2025")
    assert gabarito()["T006"] in r.resposta and r.llm_usado and r.detalhes["extracao"] == "llm"


def test_financeiro_llm_alucinado_cai_nas_regras(database, fake_llm):
    fake_llm(json_fn=lambda s, u: {"operacao": "total", "departamentos": ["Departamento Inexistente"]})
    r = financeiro.answer("Qual foi a soma de todas as receitas registradas em 2025?")
    assert gabarito()["T011"] in r.resposta and r.detalhes["extracao"] == "regras (fallback)"


def test_interno_com_llm_recebe_somente_trechos_recuperados(database, fake_llm):
    llm = fake_llm(text_fn=lambda s, u: "Solicite pelo portal interno com 30 dias corridos. Fonte: 01_politica_ferias.md")
    r = interno.answer("Como solicito férias?")
    assert r.llm_usado and r.fontes == ["01_politica_ferias.md"]
    prompt = llm.calls[-1][1]
    assert "01_politica_ferias.md" in prompt and "seguranca@aurora.example" not in prompt


def test_interno_sem_documento_relevante(database):
    r = interno.answer("Qual é a política de estacionamento para visitantes?")
    assert r.status == "nao_encontrado"


def test_api_chat_logs_e_validacao(database, monkeypatch):
    monkeypatch.setenv("INGEST_ON_STARTUP", "false")
    from app.main import app
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        r = client.post("/api/chat", json={"pergunta": "Qual o status do protocolo OUV-0002?"})
        assert r.status_code == 200 and r.json()["dominio"] == "ouvidoria"
        r = client.post("/api/chat", json={"pergunta": "reembolso", "dominio": "ouvidoria"})
        assert r.json()["metodo_classificacao"] == "escolha_do_usuario"
        assert client.post("/api/chat", json={"pergunta": ""}).status_code == 422
        logs = client.get("/api/logs?limit=5").json()
        assert logs and {"pergunta", "dominio_previsto", "latencia_ms", "status", "fontes"} <= set(logs[0])
        export = client.get("/api/logs/export?limit=5")
        assert export.status_code == 200 and export.text.strip().splitlines()
        assert client.get("/").status_code == 200


# ------------------------------------------------------------------ continuação e esclarecimento
from app.context import Turno  # noqa: E402

HIST = [Turno("Quais são as aprovações para uma compra de R$ 12.000?", "informacoes_internas",
              "Compras acima de R$ 10.000 exigem liderança, gerente e diretoria.")]


def test_continuacao_sem_llm_herda_o_assunto(database):
    r = handle("E se eu quiser de 6000?", historico=HIST)
    assert r["dominio"] == "informacoes_internas" and "03_aprovacao_de_compras.md" in r["fontes"]
    assert r["pergunta_interpretada"]


def test_continuacao_com_llm_reescreve_e_responde(database, fake_llm):
    def json_fn(system, user):
        assert "reescreve" in system  # roteamento por regras não precisa do LLM aqui
        return {"continuacao": True, "pergunta": "Quais são as aprovações para uma compra de R$ 6.000?"}

    fake_llm(json_fn=json_fn,
             text_fn=lambda s, u: "Até R$ 10.000 basta a aprovação da liderança. Fonte: 03_aprovacao_de_compras.md")
    r = handle("E se eu quiser de 6000?", historico=HIST)
    assert r["pergunta_interpretada"] == "Quais são as aprovações para uma compra de R$ 6.000?"
    assert r["dominio"] == "informacoes_internas" and r["fontes"] == ["03_aprovacao_de_compras.md"]


def test_financeiro_sem_alvo_pede_esclarecimento(database, fake_llm):
    # mesmo que o LLM "chute" uma operação, sem termo financeiro nem filtro o agente não inventa consulta
    fake_llm(json_fn=lambda s, u: {"operacao": "maiores_lancamentos", "limite": 10})
    r = handle("E se eu quiser de 6000?", dominio_forcado="financeiro")
    assert r["status"] == "esclarecimento" and not r["tabela"]
    r = handle("Mas eu só queria saber sobre uma compra de 6.000, não queria extrato", dominio_forcado="financeiro")
    assert r["status"] == "esclarecimento"


def test_log_guarda_resposta_e_pergunta_interpretada(database):
    r = handle("E se eu quiser de 6000?", historico=HIST)
    row = database.fetch_one("SELECT pergunta, pergunta_interpretada, resposta FROM agent_logs WHERE id = %s",
                             [r["id"]])
    assert row["pergunta"] == "E se eu quiser de 6000?"
    assert row["pergunta_interpretada"] and row["resposta"] == r["resposta"]


def test_api_aceita_historico(database, monkeypatch):
    monkeypatch.setenv("INGEST_ON_STARTUP", "false")
    from app.main import app
    with TestClient(app) as client:
        body = {"pergunta": "E se eu quiser de 6000?",
                "historico": [{"pergunta": HIST[0].pergunta, "dominio": "informacoes_internas", "resposta": "..."}]}
        r = client.post("/api/chat", json=body).json()
        assert r["dominio"] == "informacoes_internas" and r["pergunta_interpretada"]
