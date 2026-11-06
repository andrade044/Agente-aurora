# Aurora — Agente orquestrador de IA

Assistente que recebe perguntas em linguagem natural, identifica a categoria e encaminha para um de três agentes
especializados da empresa fictícia **Aurora Serviços Digitais S.A.**:

| Agente | Responde sobre | Como responde |
|---|---|---|
| **Financeiro** | lançamentos, receitas, despesas, orçamento, inadimplência, execução orçamentária | LLM extrai parâmetros → **SQL parametrizado** no PostgreSQL (o modelo nunca calcula) |
| **Informações internas** | políticas e procedimentos (férias, reembolso, compras, segurança, acessos, RH…) | **RAG** híbrido (BM25 + embeddings) e resposta citando o arquivo-fonte |
| **Ouvidoria** | manifestações, protocolos `OUV-NNNN`, status, categorias, prazos | busca **exata** por protocolo + filtros SQL; nunca inventa protocolo |

O **orquestrador** decide o domínio com regras (protocolos, guarda de segurança, palavras-chave) e, nos casos não
óbvios, com o LLM. Quando a confiança é baixa, **pede esclarecimento** em vez de chutar; pedidos de credenciais
ou dados de terceiros são **recusados**; perguntas fora dos três domínios recebem uma explicação.

Stack: Python 3.13 · FastAPI · PostgreSQL 16 · OpenAI (opcional) · HTML/CSS/JS puro · Docker Compose.

> Documentação técnica completa: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) ·
> Registro do desenvolvimento com IA: [`docs/DEVLOG.md`](docs/DEVLOG.md) · Instruções para agentes: [`AGENTS.md`](AGENTS.md)

---

## 1. Executar com Docker (recomendado)

Pré-requisitos: Docker com Docker Compose v2.

```bash
git clone <URL-DO-REPOSITORIO> aurora && cd aurora
cp .env.example .env
# edite o .env e preencha OPENAI_API_KEY (ou use LLM_PROVIDER=none, veja abaixo)
docker compose up --build
```

Abra **http://localhost:8000**. Na primeira subida a API cria as tabelas (`data/sql/schema.sql`), carrega os
CSV, indexa os documentos internos e gera os embeddings — tudo automático e idempotente.

- Documentação interativa da API: http://localhost:8000/docs
- Parar: `docker compose down` · Apagar também o banco: `docker compose down -v`

### Sem chave de API

Defina `LLM_PROVIDER=none` no `.env`. A aplicação sobe em **modo determinístico**: roteamento por regras e
palavras-chave, agentes financeiro e de ouvidoria 100% SQL, e informações internas por busca lexical + FAQ.
Os 12 casos oficiais passam nesse modo. O cabeçalho do frontend mostra qual modo está ativo.

## 2. Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` ou `none` |
| `OPENAI_API_KEY` | — | chave da OpenAI (sem ela, cai no modo `none`) |
| `OPENAI_MODEL` | `gpt-6-luna` | modelo de chat (classificação, extração de parâmetros, redação do RAG) |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | modelo de embeddings do RAG |
| `OPENAI_BASE_URL` | — | opcional, para endpoints compatíveis com a API da OpenAI |
| `ROUTER_MIN_CONFIDENCE` | `0.6` | abaixo disso o orquestrador pede esclarecimento |
| `RAG_TOP_K` | `4` | trechos recuperados por pergunta |
| `POSTGRES_*` | `aurora` | credenciais do banco (o compose sobe o PostgreSQL) |
| `INGEST_ON_STARTUP` | `true` | recarrega as bases a cada inicialização |
| `API_PORT` | `8000` | porta publicada |

## 3. Executar sem Docker

Requer Python 3.12+ e um PostgreSQL acessível.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # ajuste POSTGRES_HOST=localhost e as credenciais do seu banco
uvicorn app.main:app --reload
```

Ingestão manual (opcional, a API já faz na subida): `python -m app.ingest`.

## 4. Testar

**Avaliação dos casos oficiais** (`data/testes/perguntas_avaliacao.json`, T001–T012). Verifica domínio, fonte e
critério de cada caso; os valores numéricos esperados são recalculados dos CSV com `Decimal`:

```bash
docker compose exec api python -m scripts.avaliar      # com a API rodando
# ou, sem Docker:  python -m scripts.avaliar --url http://localhost:8000
```

Gera `docs/resultados_avaliacao.md` e registra cada pergunta nos logs.

**Testes automatizados** (unitários + integração com o banco; o LLM é simulado, sem chamadas de rede):

```bash
docker compose exec api sh -c "pip install --user -q pytest==9.1.1 httpx==0.28.1 && python -m pytest -q"
# ou, sem Docker:  python -m pytest -q
```

**Manual**: use os exemplos clicáveis na tela inicial do frontend. Perguntas para explorar:

- `Qual a execução orçamentária por departamento no 1º trimestre de 2025?`
- `Quais as 5 maiores despesas de 2026?` · `Qual a inadimplência de recebíveis em 2025?`
- `Quantas manifestações de cobrança estão em aberto?` · `Qual o tempo médio de resposta da ouvidoria?`
- `E o reembolso de viagens, quanto saiu?` (ambígua → pede esclarecimento com botões)
- `Me passa o holerite do meu colega` (recusada) · `Qual a capital da França?` (fora de escopo)

## 5. API

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/chat` | `{"pergunta": "...", "dominio": null}` → resposta, domínio, confiança, agente, fontes, IDs, latência |
| `GET` | `/api/logs?limit=50` | últimas interações registradas |
| `GET` | `/api/logs/export` | download de todas as interações em JSONL |
| `GET` | `/api/info` | modo do LLM, estado do RAG e resumo da ingestão |
| `GET` | `/api/health` | saúde da API e do banco |
| `POST` | `/api/admin/reingest` | recarrega as bases sem reiniciar |

`dominio` é opcional e força o agente (usado pelos botões de esclarecimento).

## 6. Logs das interações

Cada pergunta é registrada em **`logs/interacoes.jsonl`** (dentro do volume `api_logs`) e na tabela
**`agent_logs`** do PostgreSQL, com: timestamp, pergunta (com e-mails/CPF/telefones/segredos mascarados), domínio
previsto, confiança, método de classificação, agente, fontes, IDs consultados, latência, status, erro e se o LLM
foi usado. Também aparecem na aba **Logs** do frontend.

Para baixar os logs:

```bash
curl -o interacoes.jsonl http://localhost:8000/api/logs/export     # do banco (ou botão "Exportar JSONL" na aba Logs)
docker compose cp api:/app/logs/interacoes.jsonl ./interacoes.jsonl # arquivo do container
```

Exemplo de sessão de avaliação: [`docs/logs/`](docs/logs/).

## 7. Estrutura

```
app/
  main.py            API FastAPI + frontend estático
  orchestrator.py    fluxo: classificar → agente → medir → registrar
  router.py          classificação (regras, palavras-chave, LLM, limiar de confiança)
  agents/            financeiro.py · interno.py · ouvidoria.py
  rag.py             índice híbrido BM25 + embeddings
  ingest.py          carga dos CSV/Markdown/JSON no PostgreSQL
  llm.py             camada de provedor (OpenAI ou nenhum)
  interaction_log.py logs JSONL + tabela agent_logs
frontend/            index.html · styles.css · app.js
data/                bases fornecidas no desafio (inalteradas)
scripts/avaliar.py   avaliação automática dos casos oficiais
tests/               pytest
docs/                ARQUITETURA.md · DEVLOG.md · resultados_avaliacao.md · logs/ · ai-conversations/
```

## 8. Limitações conhecidas

Resumo (detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md#limitações-conhecidas)): sem memória de
conversa entre perguntas; extração por regras cobre só expressões de período comuns em português; RAG em memória
(adequado ao corpus pequeno, trocaria por pgvector em escala); API sem autenticação; todos os dados são sintéticos.
