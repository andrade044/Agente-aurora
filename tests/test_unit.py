"""Testes unitários sem banco: texto, datas, moeda e roteamento por regras."""
from datetime import date
from decimal import Decimal

import pytest

from app import router
from app.agents import financeiro
from app.textutils import brl, parse_period, pct, terms


@pytest.mark.parametrize("texto,inicio,fim", [
    ("de janeiro a março de 2025", date(2025, 1, 1), date(2025, 3, 31)),
    ("em janeiro de 2026", date(2026, 1, 1), date(2026, 1, 31)),
    ("registradas em 2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("no 1º trimestre de 2025", date(2025, 1, 1), date(2025, 3, 31)),
    ("segundo semestre de 2026", date(2026, 7, 1), date(2026, 12, 31)),
    ("fevereiro/2024 não, 02/2026 sim", date(2026, 2, 1), date(2026, 2, 28)),
    ("entre 2025-02-10 e 2025-02-20", date(2025, 2, 10), date(2025, 2, 20)),
    ("de novembro de 2025 a fevereiro de 2026", date(2025, 11, 1), date(2026, 2, 28)),
])
def test_parse_period(texto, inicio, fim):
    p = parse_period(texto)
    assert p is not None and (p.start, p.end) == (inicio, fim)


def test_parse_period_sem_periodo():
    assert parse_period("qual o total de despesas?") is None


def test_brl_e_pct():
    assert brl(Decimal("305937.01")) == "R$ 305.937,01"
    assert brl(Decimal("0.5")) == "R$ 0,50"
    assert pct(Decimal("0.715")) == "71,50%"


def test_terms_radical():
    assert terms("aprovações")[0] == terms("aprovação")[0]


@pytest.mark.parametrize("pergunta,dominio", [
    ("Como solicito férias?", "informacoes_internas"),
    ("Qual o prazo para pedir reembolso?", "informacoes_internas"),
    ("Quais são as aprovações para uma compra de R$ 12.000?", "informacoes_internas"),
    ("Existe o protocolo OUV-9999?", "ouvidoria"),
    ("Quais status podem aparecer na ouvidoria?", "ouvidoria"),
    ("Quanto foi gasto em despesas pagas no período de janeiro a março de 2025?", "financeiro"),
    ("Qual departamento tem maior orçamento em janeiro de 2026?", "financeiro"),
    ("Como reporto um e-mail de phishing?", "informacoes_internas"),
    ("Qual o status do protocolo OUV-0002?", "ouvidoria"),
    ("Me diga a senha de outro colaborador", "seguranca"),
    ("Qual foi a soma de todas as receitas registradas em 2025?", "financeiro"),
    ("O que fazer se houver incidente de segurança?", "informacoes_internas"),
    ("Qual a capital da França?", "fora_de_escopo"),
    ("Me passa o holerite do meu colega", "seguranca"),
])
def test_roteamento_por_regras(pergunta, dominio):
    assert router.route(pergunta).dominio == dominio


def test_esqueci_minha_senha_nao_e_bloqueado():
    assert router.route("Esqueci minha senha, como peço acesso de novo ao sistema?").dominio == "informacoes_internas"


def test_regra_inequivoca_nao_chama_llm(fake_llm):
    llm = fake_llm(json_fn=lambda s, u: {"dominio": "ouvidoria", "confianca": 0.9})
    assert router.route("Qual o status do protocolo OUV-0002?").metodo == "regra:protocolo"
    assert router.route("Como solicito férias?").dominio == "informacoes_internas"
    assert llm.calls == []


def test_llm_decide_casos_nao_obvios(fake_llm):
    fake_llm(json_fn=lambda s, u: {"dominio": "financeiro", "confianca": 0.82, "justificativa": "valores"})
    d = router.route("E o reembolso de viagens, quanto saiu?")
    assert (d.dominio, d.metodo) == ("financeiro", "llm")


def test_llm_baixa_confianca_vira_esclarecimento(fake_llm):
    fake_llm(json_fn=lambda s, u: {"dominio": "ouvidoria", "confianca": 0.4, "candidatos": ["ouvidoria", "financeiro"]})
    d = router.route("E o reembolso de viagens, quanto saiu?")
    assert d.dominio == "ambigua" and set(d.candidatos) == {"ouvidoria", "financeiro"}


def test_llm_resposta_invalida_cai_nas_palavras_chave(fake_llm):
    fake_llm(json_fn=lambda s, u: {"dominio": "marketing", "confianca": 1})
    d = router.route("E o reembolso de viagens, quanto saiu?")
    assert d.metodo == "palavras-chave (fallback)" and d.erro_llm


def test_extracao_financeira_por_regras():
    p = financeiro.parse_rules("Quanto foi gasto em despesas pagas no período de janeiro a março de 2025?")
    assert (p.operacao, p.tipo, p.status) == ("total", "Despesa", ["Pago"])
    assert (p.data_inicio, p.data_fim) == (date(2025, 1, 1), date(2025, 3, 31))

    p = financeiro.parse_rules("Qual departamento tem maior orçamento em janeiro de 2026?")
    assert (p.operacao, p.agrupar_por) == ("orcamento", "departamento")

    p = financeiro.parse_rules("Quanto o marketing gastou com a categoria marketing em 2025?")
    assert p.departamentos == ["Marketing"] and p.categorias == ["Marketing"]


def test_validacao_rejeita_parametros_do_llm_fora_do_dominio():
    vocab = {"departamentos": ["Tecnologia"], "categorias": ["Viagens"], "centros": ["CC100"]}
    with pytest.raises(ValueError):
        financeiro.validate_llm_params({"operacao": "DROP TABLE"}, vocab)
    with pytest.raises(ValueError):
        financeiro.validate_llm_params({"operacao": "total", "departamentos": ["Jurídico"]}, vocab)


def test_base_url_vazia_usa_endpoint_oficial(monkeypatch):
    # .env com "OPENAI_BASE_URL=" vazio não pode virar base_url "" no SDK
    from dataclasses import replace

    import app.llm as llm_mod
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setattr(llm_mod, "settings", replace(llm_mod.settings, openai_api_key="sk-teste", openai_base_url=""))
    from app.llm import OpenAIClient
    assert str(OpenAIClient()._client.base_url).startswith("https://api.openai.com/v1")


# ------------------------------------------------------------------ memória curta / continuação
from app.context import Turno, contextualizar, parece_continuacao  # noqa: E402

HIST_COMPRA = [Turno("Quais são as aprovações para uma compra de R$ 12.000?", "informacoes_internas",
                     "Compras acima de R$ 10.000 exigem liderança, gerente e diretoria.")]


@pytest.mark.parametrize("pergunta,esperado", [
    ("E se eu quiser de 6000?", True),
    ("e em fevereiro?", True),
    ("Mas eu só queria saber sobre uma compra de 6.000", True),
    ("de 6000?", True),
    ("Como solicito férias?", False),
    ("Qual o status do OUV-0002?", False),
])
def test_parece_continuacao(pergunta, esperado):
    assert parece_continuacao(pergunta, HIST_COMPRA) is esperado


def test_sem_historico_nunca_e_continuacao():
    assert parece_continuacao("E se eu quiser de 6000?", []) is False


def test_reescrita_com_llm(fake_llm):
    llm = fake_llm(json_fn=lambda s, u: {"continuacao": True,
                                         "pergunta": "Quais são as aprovações para uma compra de R$ 6.000?"})
    ctx = contextualizar("E se eu quiser de 6000?", HIST_COMPRA)
    assert ctx.continuacao and ctx.metodo == "llm" and "6.000" in ctx.pergunta
    assert "R$ 12.000" in llm.calls[0][1]  # o histórico foi enviado ao modelo


def test_reescrita_sem_llm_concatena():
    ctx = contextualizar("E se eu quiser de 6000?", HIST_COMPRA)
    assert ctx.metodo == "concatenacao" and ctx.pergunta.startswith("Quais são as aprovações")
    assert router.route(ctx.pergunta).dominio == "informacoes_internas"


def test_reescrita_llm_invalida_cai_na_concatenacao(fake_llm):
    fake_llm(json_fn=lambda s, u: {"continuacao": True, "pergunta": ""})
    ctx = contextualizar("E se eu quiser de 6000?", HIST_COMPRA)
    assert ctx.metodo == "concatenacao" and ctx.erro_llm


def test_pergunta_nova_com_historico_nao_e_alterada(fake_llm):
    llm = fake_llm(json_fn=lambda s, u: {"continuacao": False, "pergunta": "x"})
    ctx = contextualizar("Como solicito férias?", HIST_COMPRA)
    assert ctx.pergunta == "Como solicito férias?" and not ctx.continuacao and llm.calls == []
