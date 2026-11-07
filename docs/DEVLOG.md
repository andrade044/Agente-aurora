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
| D12 | Memória curta no cliente (3 trocas) + reescrita da pergunta pelo LLM antes do roteamento | Memória de sessão no servidor; passar o histórico inteiro a cada agente | API continua sem estado; uma única reescrita serve a classificação e todos os agentes; fácil de auditar ("Entendi como") | Aceita |
| D11 | Frontend servido pelo próprio FastAPI (`StaticFiles`) | Container nginx | Menos peças; sem CORS | Aceita |

## Problemas conhecidos / limitações

- Docker Compose validado de ponta a ponta no ambiente da IA (ver [008]). O build lá exigiu um Dockerfile temporário com o certificado do proxy do ambiente — isso **não** faz parte do repositório; em máquina normal `docker compose up --build` funciona direto. Ainda assim, rodar uma vez na máquina do desenvolvedor antes da entrega.
- Caminho com OpenAI real não exercitado (sem chave no ambiente); coberto por testes com cliente simulado. Conferir o nome do modelo em `OPENAI_MODEL`.
- Memória curta de 3 trocas; sem LLM a continuação é aproximada por concatenação. Parser por regras não entende períodos relativos ("mês passado").
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

### [008] 2026-11-06 — Teste real com Docker e correção da permissão dos logs
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** "Pra liberar Docker Hub neste ambiente." → orientação para adicionar domínios do Docker Hub em Settings › Capabilities; depois "Pronto adicionei os domínios".
- **Resposta / solução proposta:** Tentativas de `docker pull` revelaram os domínios necessários (`registry-1.docker.io`, `auth.docker.io` e `production.cloudfront.docker.com` para as camadas — a sugestão inicial `production.cloudflare.docker.com` estava errada). Com os domínios liberados, imagens baixadas, build e `docker compose up` executados.
- **Decisão:** aceita.
- **Problemas encontrados e soluções:**
  - `429 Too Many Requests` do Docker Hub (limite anônimo) → novas tentativas com espera.
  - `pip install` no build falhou com `CERTIFICATE_VERIFY_FAILED` (proxy TLS do ambiente da IA) → Dockerfile **temporário, fora do repositório**, que copia o certificado via `--build-context` só para este teste. O `Dockerfile` do repositório não foi alterado.
  - **Bug real encontrado:** a API roda como usuário não-root (uid 1000) e a pasta `./logs` montada do host pertencia a outro usuário → `Permission denied` ao gravar `interacoes.jsonl` (o log no banco continuava funcionando). Em Linux com uid ≠ 1000 o avaliador veria o mesmo. **Correção:** volume nomeado `api_logs` no lugar do bind mount + endpoint `GET /api/logs/export` (JSONL do banco) + botão "Exportar JSONL" no frontend + instruções `docker compose cp` no README.
- **Testes / validação:** `docker compose down -v` e subida do zero: containers `healthy`, ingestão automática, `scripts.avaliar` dentro do container **12/12**, `interacoes.jsonl` com 12 linhas e zero erros de gravação, logs preservados após `docker compose restart api`, export com 12 linhas, frontend HTTP 200. `pytest` dentro de um container na rede do compose: **51 passed**.
- **Arquivos afetados:** `docker-compose.yml`, `app/main.py`, `app/interaction_log.py`, `frontend/index.html`, `frontend/styles.css`, `README.md`, `tests/test_integracao.py`

### [009] 2026-11-07 — Bug: OPENAI_BASE_URL vazio quebrava o cliente OpenAI
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** Ao preencher o `.env`: "No .env pede a URL base da openai" (o que colocar em `OPENAI_BASE_URL`).
- **Resposta / solução proposta:** Deixar em branco. Ao verificar, a IA descobriu que o SDK `openai` lê a variável de ambiente `OPENAI_BASE_URL` por conta própria: com `OPENAI_BASE_URL=` vazio (como no `.env.example` e no `env_file` do compose) o cliente ficava com `base_url = ''`, todas as chamadas falhariam e a aplicação cairia silenciosamente no modo determinístico. O código só passava `base_url` quando a variável tinha valor.
- **Decisão:** corrigido — `OpenAIClient` agora sempre passa `base_url` explícito (`OPENAI_BASE_URL` ou `https://api.openai.com/v1`). Comentário do `.env.example` esclarecido.
- **Problemas encontrados:** os testes usavam só o `FakeLLM`, por isso não pegaram a configuração real do SDK.
- **Testes / validação:** novo teste `test_base_url_vazia_usa_endpoint_oficial`, confirmado falhando no código antigo e passando no novo; suíte completa: 52 passed.
- **Arquivos afetados:** `app/llm.py`, `.env.example`, `tests/test_unit.py`

### [010] 2026-11-07 — Primeiro teste com LLM real: continuação de conversa, financeiro "chutando" e resposta no log
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** Matheus rodou com a chave da OpenAI e enviou `interacoes.jsonl` pedindo para conferir ("Vê se essa conversa está de acordo"); depois autorizou as correções ("Por favor").
- **Análise do log:** os 12 casos oficiais corretos, com LLM e embeddings ativos (cosseno preenchido, extração financeira via LLM batendo com o gabarito). Três problemas:
  1. "E se eu quiser de 6000?" após a pergunta da compra de R$ 12.000 virou pergunta ambígua: o agente não tinha memória da conversa.
  2. Com o domínio Financeiro escolhido no esclarecimento, o LLM "chutou" `maiores_lancamentos` e `total` geral para uma pergunta sem nada a calcular.
  3. O log não guardava o texto da resposta, dificultando auditar a interação.
- **Resposta / solução proposta:**
  1. `app/context.py`: memória curta. O frontend envia as 3 últimas trocas; mensagens que parecem continuação são reescritas pelo LLM (JSON validado) antes do roteamento; sem LLM, concatenação com a pergunta anterior. A UI mostra "Entendi como: …" e ganhou o botão "Nova conversa".
  2. Financeiro: operação `nao_identificado` no prompt e checagem determinística `_tem_alvo` (termo financeiro ou filtro concreto); sem alvo → pedido de esclarecimento com exemplos, mesmo com domínio forçado.
  3. Colunas `pergunta_interpretada` e `resposta` em `agent_logs` (via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, compatível com bancos já criados) e no JSONL.
- **Decisão:** aceita (D12).
- **Problemas encontrados:** a primeira versão da heurística tratava qualquer pergunta curta como continuação ("Como solicito férias?" tem 3 palavras) → pergunta curta só conta como continuação se não tiver termo de nenhum domínio nem protocolo.
- **Testes / validação:** 16 testes novos (heurística de continuação, reescrita com LLM simulado, fallback por concatenação, reescrita inválida, pergunta nova não alterada, cenário completo do log com e sem LLM, financeiro sem alvo com LLM chutando, campos novos no log, API com `historico`): **68 passed**. Fluxo repetido no navegador (Chrome headless). Docker do zero: `healthy`, avaliação **12/12**, continuação e esclarecimento via HTTP, export com `resposta` e `pergunta_interpretada`, nenhum erro no log do container. Log real recebido salvo em `docs/logs/interacoes_llm_2026-11-07.jsonl`.
- **Arquivos afetados:** `app/context.py` (novo), `app/orchestrator.py`, `app/main.py`, `app/agents/financeiro.py`, `app/interaction_log.py`, `app/sql/extra.sql`, `frontend/*`, `tests/*`, `README.md`, `docs/ARQUITETURA.md`

### [011] 2026-11-07 — Tela inicial mais limpa
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** Matheus, olhando a tela inicial: "A entrada da plataforma é essa mesma? Com esse tanto de informação?"; aceitou a proposta de três cartões ("Acho que seria mais interessante").
- **Resposta / solução proposta:** Os 10 botões com códigos de teste (T001…) deram lugar a três cartões, um por agente (Financeiro, Informações internas, Ouvidoria), cada um com uma linha explicando o que responde e 2 exemplos clicáveis. Os códigos de teste saíram da interface (continuam no `scripts/avaliar.py`). "Nova conversa" volta a mostrar os cartões. Placeholder encurtado.
- **Decisão:** modificada a pedido — com 2 exemplos a tela ficou vazia demais ("deixa umas 3 ou 4 opções"); passou a 4 exemplos por cartão (12 no total, cobrindo 9 casos oficiais e perguntas extras como maiores despesas, execução orçamentária e tempo médio de resposta).
- **Problemas encontrados:** placeholder longo quebrava em duas linhas no celular → encurtado.
- **Testes / validação:** screenshots em 1422×767 e 390×844 (Chrome headless), clique em exemplo e "Nova conversa" funcionando, console sem erros; cada um dos 12 exemplos enviado à API e roteado ao agente certo com status ok; `pytest` 68 passed.
- **Arquivos afetados:** `frontend/index.html`, `frontend/app.js`, `frontend/styles.css`

### [012] 2026-11-07 — Tela inicial vazia depois de atualizar o frontend (cache do navegador)
- **Ferramenta:** Claude Opus 5.5 (claude.ai)
- **Prompt / solicitação:** "Mas não mudou nada, a tela continua vazia de tudo" (após copiar o novo `frontend/` e rodar `docker compose up --build`).
- **Diagnóstico:** o `index.html` novo não traz mais os exemplos fixos (agora gerados pelo `app.js`). Se o navegador reaproveita do cache um `app.js` antigo, esse script procura `#examples` (que não existe mais), lança `TypeError` e para antes de desenhar a tela, que fica vazia. Cenário reproduzido combinando os dois arquivos.
- **Resposta / solução proposta:** middleware no FastAPI com `Cache-Control: no-cache, must-revalidate` para tudo que não é `/api/`, e versão nos links (`app.js?v=11`, `styles.css?v=11`) para forçar o download na primeira carga após a atualização.
- **Decisão:** aceita. Evita o mesmo problema para o avaliador se ele abrir versões diferentes do projeto.
- **Testes / validação:** cabeçalho conferido com `curl -I` (frontend com `no-cache`, API sem); screenshot e cliques sem erros no console; `pytest` 68 passed.
- **Arquivos afetados:** `app/main.py`, `frontend/index.html`
