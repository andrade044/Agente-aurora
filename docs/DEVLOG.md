# DEVLOG — Registro do desenvolvimento com IA

Registro contínuo das interações com ferramentas de IA durante a construção do projeto. Formato e regras em [`AGENTS.md`](../AGENTS.md#3-registro-obrigatório-do-processo-devlog).

## Decisões técnicas (ADR resumido)

| # | Decisão | Alternativas consideradas | Motivo | Status |
|---|---|---|---|---|
| D1 | PostgreSQL para dados tabulares (financeiro e ouvidoria) | SQLite, pandas em memória | O pacote já traz `schema.sql` para Postgres e `ingestao_e_uso.md` recomenda Postgres; `NUMERIC(14,2)` garante precisão monetária | Proposta |
| D2 | Agente financeiro: LLM extrai parâmetros (intenção, período, tipo, status, departamento) → consultas SQL pré-definidas e parametrizadas | Text-to-SQL livre | Documentação proíbe SQL arbitrário do modelo; cálculo determinístico e auditável | Proposta |
| D3 | Orquestrador híbrido: regra rápida (regex `OUV-\d{4}`, palavras de credencial) + classificação via LLM com saída estruturada e confiança | Só LLM; só classificador clássico | Regras dão precisão nos casos óbvios; LLM cobre linguagem natural; confiança baixa → pedir esclarecimento | Proposta |
| D4 | RAG com chunks por seção (`##`) dos Markdown + FAQ como chunks próprios, metadados `source` e `document_version` | Chunk por tamanho fixo | Documentos são curtos (~700 bytes); seção preserva o sentido e facilita citação | Proposta |
| D5 | Logs do agente em JSONL + tabela no Postgres | Só arquivo | JSONL é fácil de entregar; tabela permite consulta | Proposta |
| D6 | Provedor de LLM: **OpenAI** (chat + embeddings na mesma chave), modelos configuráveis via `.env`; camada de provedor desacoplada | Anthropic (sem API de embeddings), Gemini gratuito (limite de ~100 req/dia), Ollama local (imagem pesada) | Uma chave cobre LLM e RAG; limite folgado para testes; provedor mais comum entre avaliadores | Aceita |
| D7 | Modo degradado sem chave (`LLM_PROVIDER=none`): orquestrador por regras/palavras-chave, financeiro e ouvidoria determinísticos, informações internas via busca lexical + FAQ | Exigir chave para subir | Aplicação sobe e responde parte dos casos mesmo sem chave de API | Proposta |

## Problemas conhecidos / limitações

- (a preencher ao longo do desenvolvimento)

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
