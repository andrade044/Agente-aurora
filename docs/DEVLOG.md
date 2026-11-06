# DEVLOG — Registro do desenvolvimento com IA

Registro contínuo das interações com ferramentas de IA durante a construção do projeto. Formato e regras em [`AGENTS.md`](../AGENTS.md#3-registro-obrigatório-do-processo-devlog).

## Decisões técnicas (ADR resumido)

| # | Decisão | Alternativas consideradas | Motivo | Status |
|---|---|---|---|---|
| D1 | PostgreSQL para dados tabulares (financeiro e ouvidoria) | SQLite, pandas em memória | O pacote já traz `schema.sql` para Postgres e `ingestao_e_uso.md` recomenda Postgres; `NUMERIC(14,2)` garante precisão monetária | Aceita |
| D2 | Agente financeiro: LLM extrai parâmetros (intenção, período, tipo, status, departamento) → consultas SQL pré-definidas e parametrizadas | Text-to-SQL livre | Documentação proíbe SQL arbitrário do modelo; cálculo determinístico e auditável | Aceita |
| D3 | Orquestrador híbrido: regra rápida (regex `OUV-\d{4}`, palavras de credencial) + classificação via LLM com saída estruturada e confiança | Só LLM; só classificador clássico | Regras dão precisão nos casos óbvios; LLM cobre linguagem natural; confiança baixa → pedir esclarecimento | Aceita |
| D4 | RAG com chunks por seção (`##`) dos Markdown + FAQ como chunks próprios, metadados `source` e `document_version` | Chunk por tamanho fixo | Documentos são curtos (~700 bytes); seção preserva o sentido e facilita citação | Aceita |
| D5 | Logs do agente em JSONL + tabela no Postgres | Só arquivo | JSONL é fácil de entregar; tabela permite consulta | Aceita |
| D6 | Provedor de LLM: **OpenAI** (chat + embeddings na mesma chave), modelos configuráveis via `.env`; camada de provedor desacoplada | Anthropic (sem API de embeddings), Gemini gratuito (limite de ~100 req/dia), Ollama local (imagem pesada) | Uma chave cobre LLM e RAG; limite folgado para testes; provedor mais comum entre avaliadores | Aceita |
| D7 | Modo degradado sem chave (`LLM_PROVIDER=none`): orquestrador por regras/palavras-chave, financeiro e ouvidoria determinísticos, informações internas via busca lexical + FAQ | Exigir chave para subir | Aplicação sobe e responde os casos mesmo sem chave de API | Aceita |
| D8 | RAG com índice BM25 em memória + embeddings persistidos em `DOUBLE PRECISION[]` no Postgres, busca híbrida 50/50 | pgvector; FAISS; só embeddings | Corpus de ~20 chunks; evita extensão/imagem extra; BM25 garante funcionamento sem chave | Aceita |
| D9 | Atalho por regras no orquestrador: confiança ≥ 0,85 pula o LLM | Sempre chamar o LLM | Menos custo/latência; casos comuns determinísticos e testáveis | Aceita (limiar ajustado na [005]) |
| D10 | Respostas numéricas (financeiro/ouvidoria) montadas por template; LLM redige só no RAG | LLM redigindo tudo | Texto nunca diverge do SQL; critério explícito na resposta | Aceita |
| D11 | Frontend servido pelo próprio FastAPI (`StaticFiles`) | Container nginx | Menos peças; sem CORS | Aceita |

## Problemas conhecidos / limitações

- Docker Compose não pôde ser executado no ambiente de desenvolvimento da IA (Docker Hub bloqueado — ver [004]); a configuração foi validada com `docker compose config` e a aplicação testada com o mesmo PostgreSQL 16 via uvicorn. **Validar `docker compose up --build` na máquina do desenvolvedor antes da entrega.**
- Caminho com OpenAI real não exercitado (sem chave no ambiente); coberto por testes com cliente simulado. Conferir o nome do modelo em `OPENAI_MODEL`.
- Sem memória de conversa; parser por regras não entende períodos relativos ("mês passado").
- Lista completa em `docs/ARQUITETURA.md#limitações-conhecidas`.

## Gabarito calculado dos casos de teste

Calculado diretamente dos CSV com Python + `Decimal` (script ad hoc, entrada [001]), para validar as respostas do agente:

| Caso | Valor esperado |
|---|---|
| T006 — despesas pagas jan–mar/2025 | R$ 305.937,01 |
| T007 — maior orçamento jan/2026 | Tecnologia — R$ 43.229,05 |
| T009 — status OUV-0002 | Aguardando área responsável |
| T011 — receitas de 2025 | R$ 275.727,70 |

---

## Entradas

### [001] 2026-11-06 — Análise das bases e estrutura inicial
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** Enviado o enunciado completo do desafio e o `.zip` das bases. Pedido: "Dê uma verificada nos arquivos e me diga o que tem neles e se vamos utilizar todos e faça o que já ia fazer."
- **Resposta / solução proposta:** Inventário dos 21 arquivos; recomendação de uso por domínio; proposta de arquitetura (decisões D1–D5); criação da estrutura do repositório, `AGENTS.md`, `CLAUDE.md`, este DEVLOG e pasta para histórico de conversas. Cálculo do gabarito numérico dos testes T006, T007, T009 e T011.
- **Decisão:** estrutura aceita como ponto de partida; D1–D5 propostas, aguardando confirmação; D6 em aberto.
- **Problemas encontrados:** CSVs têm BOM UTF-8 (`﻿` no primeiro cabeçalho) → ler com `encoding="utf-8-sig"` na ingestão.
- **Testes / validação:** perfil dos CSV (300 lançamentos: 283 despesas/17 receitas; competência 2025-01-01 a 2026-12-28; 6 departamentos; 180 manifestações de 2026-01-05 a 2026-10-11; 144 linhas de orçamento) bate com `manifesto_pacote.json`.
- **Arquivos afetados:** `AGENTS.md`, `CLAUDE.md`, `docs/DEVLOG.md`, `docs/ai-conversations/README.md`, `.gitignore`, `data/` (cópia das bases)

### [002] 2026-11-06 — Escolha do provedor de LLM
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** Discussão sobre qual API usar: chave temporária da Anthropic, créditos da OpenAI (esgotados), alternativa gratuita. Pergunta final: "Qual seria a melhor API?"
- **Resposta / solução proposta:** Comparativo OpenAI × Anthropic × Gemini (custo, embeddings, rate limit, qualidade, chance de o avaliador ter chave). Recomendação: OpenAI se houver ~US$ 5 de crédito; Gemini gratuito como alternativa. Em qualquer caso, camada de provedor desacoplada e modo sem LLM. Orientação de segurança: projeto/chave dedicados ao desafio, limite de gasto, chave só no `.env` e revogada ao final.
- **Decisão:** aceita — OpenAI (D6). Gemini e Anthropic descartados como padrão, mas a interface de provedor fica preparada para troca. Modo sem LLM (D7) proposto.
- **Problemas encontrados:** créditos pré-pagos da OpenAI expirados; Anthropic não oferece embeddings; Gemini gratuito com rate limit baixo e uso dos dados para treino.
- **Testes / validação:** — (decisão de arquitetura)
- **Arquivos afetados:** `docs/DEVLOG.md`

### [003] 2026-11-06 — Mudança de forma de trabalho: IA escreve o código
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** "pode fazer a parte codada toda, isso não é levado em consideração"
- **Resposta / solução proposta:** A IA passa a implementar todo o código, mantendo o registro no DEVLOG. Plano em 6 etapas: infraestrutura → núcleo do backend (config, banco, ingestão, LLM, logs) → orquestrador e agentes → frontend → testes/avaliação → documentação.
- **Decisão:** aceita. `AGENTS.md` seção 2 atualizada.
- **Problemas encontrados:** —
- **Testes / validação:** —
- **Arquivos afetados:** `AGENTS.md`

### [004] 2026-11-06 — Backend: ingestão, agentes, orquestrador e API
- **Ferramenta:** Claude Opus 5.5 (claude.ai), executando código num ambiente Linux com PostgreSQL 16 local
- **Prompt / solicitação:** continuação de [003].
- **Resposta / solução proposta:**
  - `app/ingest.py`: aplica `schema.sql` + `extra.sql`, valida e carrega os CSV com `COPY` numa transação; gera chunks por seção `##` + FAQ; embeddings só para chunks novos/alterados (hash).
  - `app/llm.py`: camada de provedor (`OpenAIClient` com JSON mode + embeddings; `NullClient`).
  - `app/router.py`: guarda de segurança → IDs → palavras-chave → LLM → limiar.
  - Agentes: financeiro (7 operações SQL pré-definidas, validação estrita do JSON do LLM), interno (RAG híbrido), ouvidoria (protocolo exato, referência, contagem, listagem, tempo de resposta).
  - `app/orchestrator.py`, `app/interaction_log.py` (JSONL + `agent_logs`, com máscara de dados pessoais), `app/main.py`.
- **Decisão:** aceita. D8–D11 registradas.
- **Problemas encontrados e soluções:**
  - Nome do modelo de chat atual da OpenAI incerto → consultada a documentação oficial (`gpt-6-luna` como padrão, configurável); parâmetro `temperature` omitido para compatibilidade entre modelos.
  - Busca "Qual o prazo para pedir reembolso?" empatava com o FAQ de acesso por causa de "pedir" → verbos genéricos ("pedir", "gostaria", "saber") adicionados às stopwords.
  - Todo Markdown começa com "Documento fictício…", poluindo os chunks → linha removida do texto (versão mantida nos metadados).
  - Bug na operação de orçamento: condição comparava `p.ordem` com regex de "maior|menor" (sempre falso) → simplificada para `agrupar_por == "departamento"`.
  - Respostas com concordância errada ("O categoria", "1 lançamentos") e período cru ("01/01/2026 a 31/01/2026") → rótulos por gênero, `plural()` e `Period.label()` ("janeiro de 2026").
  - "Qual o prazo de resposta da ouvidoria?" caía em contagem → padrão de prazo adicionado à operação `tempo_resposta`.
  - Docker Hub retornou `403 Forbidden` no ambiente da IA (política de rede) → não contornado; `docker compose config` validado e app testado com uvicorn + PostgreSQL 16 local.
- **Testes / validação:** os 12 casos oficiais rodados pelo orquestrador em modo determinístico; valores conferidos com o gabarito da [001] (T006 R$ 305.937,01; T007 Tecnologia R$ 43.229,05; T011 R$ 275.727,70). Smoke test da API (`/api/health`, `/api/info`, `/api/chat`, `/api/logs`, validação 422).
- **Arquivos afetados:** `app/**`, `requirements*.txt`

### [005] 2026-11-06 — Testes automatizados e ajustes revelados por eles
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Resposta / solução proposta:** `tests/test_unit.py` (datas, moeda, roteamento dos 12 casos, LLM simulado: decisão, baixa confiança → esclarecimento, resposta inválida → fallback; validação de parâmetros alucinados) e `tests/test_integracao.py` (ingestão, 12 casos com critérios, protocolo inexistente, financeiro com LLM simulado válido e alucinado, prompt do RAG contendo só trechos recuperados, API via TestClient). `FakeLLM` em `conftest.py` evita chamadas de rede.
- **Decisão:** aceita.
- **Problemas encontrados e soluções:**
  - "E o reembolso de viagens, quanto saiu?" era decidida pelas regras (uma palavra fraca, "reembolso", dava confiança 0,86) sem consultar o LLM → fórmula ajustada (`0,7 + 0,1 × pontuação`): um termo fraco não basta para pular o LLM; "quanto saiu/deu" passou a contar para financeiro. Sem LLM a pergunta vira pedido de esclarecimento, comportamento desejado.
  - "Política de estacionamento" (inexistente) retornava trecho irrelevante porque "política" aparece em todos os títulos → termos genéricos ignorados no BM25 (`GENERIC_TERMS`).
- **Testes / validação:** `pytest`: 51 passed.
- **Arquivos afetados:** `tests/**`, `app/router.py`, `app/rag.py`

### [006] 2026-11-06 — Frontend
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Resposta / solução proposta:** HTML/CSS/JS puro: chat com exemplos clicáveis (casos oficiais), selo de domínio/confiança/método/agente/latência, fontes, tabela de dados, botões de esclarecimento que reenviam a pergunta com o domínio escolhido, detalhes técnicos recolhíveis, aba de logs, indicador de modo (LLM x determinístico). Markdown mínimo renderizado com escape de HTML.
- **Decisão:** aceita.
- **Problemas encontrados e soluções:** inspeção por screenshot (Chrome headless) mostrou 404 de favicon, selos quebrando linha e "Fontes" duplicado na resposta de segurança → favicon inline, `white-space: nowrap`, texto removido.
- **Testes / validação:** screenshots da tela inicial, conversa e logs; console sem erros após correção.
- **Arquivos afetados:** `frontend/**`, `app/orchestrator.py`

### [007] 2026-11-06 — Avaliação, Docker e documentação
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Resposta / solução proposta:** `scripts/avaliar.py` (casos oficiais via HTTP ou local, gabarito recalculado dos CSV, relatório em `docs/resultados_avaliacao.md`); `Dockerfile` (python:3.13-slim, usuário não-root, healthcheck), `docker-compose.yml` (Postgres com healthcheck + `depends_on: service_healthy`, volume de logs), `.env.example`, `.dockerignore`; `README.md`; `docs/ARQUITETURA.md`; amostra de logs em `docs/logs/`.
- **Decisão:** aceita.
- **Problemas encontrados:** ver limitação do Docker na seção "Problemas conhecidos".
- **Testes / validação:** `python -m scripts.avaliar` contra a API em modo determinístico: **12/12**. Sessão extra com perguntas ambíguas, fora de escopo, recusadas e escolha de domínio registrada em `docs/logs/interacoes_exemplo_modo_deterministico.jsonl`.
- **Arquivos afetados:** `scripts/avaliar.py`, `Dockerfile`, `docker-compose.yml`, `.env.example`, `.dockerignore`, `README.md`, `docs/**`
