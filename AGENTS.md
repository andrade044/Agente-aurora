# AGENTS.md — Instruções para agentes de IA neste repositório

Este arquivo orienta qualquer agente de IA (Claude, Copilot, Cursor, Codex etc.) que trabalhe neste projeto.
`CLAUDE.md` aponta para cá. **Leia este arquivo inteiro antes de qualquer alteração.**

## 1. Contexto do projeto

Agente de IA com **orquestrador** que classifica perguntas em linguagem natural e as encaminha para um de três agentes especializados da empresa fictícia *Aurora Serviços Digitais S.A.*:

| Domínio | Fonte | Estratégia |
|---|---|---|
| `financeiro` | `data/financeiro/*.csv`, `indicadores_e_regras.json` | Extração de parâmetros pelo LLM → **SQL parametrizado e determinístico** (o LLM nunca faz conta nem gera SQL livre) |
| `informacoes_internas` | `data/informacoes_internas/*.md`, `faq_interno.json` | RAG: chunks por seção + recuperação + resposta citando o arquivo-fonte |
| `ouvidoria` | `data/ouvidoria/manifestacoes.csv`, `referencia_ouvidoria.json` | Busca exata por protocolo (`OUV-NNNN`) + filtros por status/categoria/data |

Casos ambíguos → pedir esclarecimento. Fora de escopo ou pedidos de credenciais/dados pessoais → recusar e orientar o canal correto.

**Stack:** Python + FastAPI, frontend HTML/CSS/JS puro, PostgreSQL, Docker Compose.

**Referências obrigatórias antes de mexer em um agente:** `data/documentacao/ingestao_e_uso.md`, `data/documentacao/dicionario_de_dados.md` e as `regras` dos JSON de cada domínio.

## 2. Forma de trabalho

- Desde a entrada [003] do DEVLOG, o desenvolvedor (Matheus) delegou a implementação à IA. A IA escreve o código, mas **toda decisão relevante continua registrada** e o desenvolvedor revisa antes da entrega.
- Trabalhe de forma incremental: uma etapa por vez, validada (testes ou execução real) antes de seguir.
- Mantenha os casos de `data/testes/perguntas_avaliacao.json` passando: rode `python -m pytest -q` e `python -m scripts.avaliar` após mudanças em orquestrador ou agentes.
- Valores monetários sempre com `Decimal` / `NUMERIC(14,2)`. Nunca `float`.
- Nunca commitar `.env`, chaves de API ou tokens.

## 3. Registro obrigatório do processo (DEVLOG)

O registro do desenvolvimento fica em **`docs/DEVLOG.md`** e deve ser atualizado **durante** o trabalho, não no final.

### Quando registrar
Ao final de cada interação relevante — qualquer uma que produza ou descarte código, tome uma decisão técnica, encontre um problema ou rode um teste. Conversas triviais (ex.: "ok", correção de typo) não precisam de entrada.

### Formato de cada entrada
Adicione entradas **no final** do arquivo, numeradas em sequência, neste formato:

```markdown
### [NNN] AAAA-MM-DD — Título curto
- **Ferramenta:** (ex.: Claude Opus 5.5 / claude.ai)
- **Prompt / solicitação:** resumo fiel do que foi pedido (citar literal quando curto)
- **Resposta / solução proposta:** o que a IA sugeriu
- **Decisão:** aceita | modificada | descartada — e por quê
- **Problemas encontrados:** (se houver) e estratégia de resolução
- **Testes / validação:** o que foi executado e o resultado
- **Arquivos afetados:** lista
```

### Seções fixas do DEVLOG (manter atualizadas)
- **Decisões técnicas (ADR resumido):** tabela com decisão, alternativas consideradas e motivo. Atualize quando uma decisão mudar — não apague a antiga, marque como substituída.
- **Problemas conhecidos / limitações:** alimenta a seção de limitações da documentação final.

### Regras do registro
- Nunca registre chaves de API, tokens, senhas ou dados pessoais. Use `***` no lugar.
- Seja factual: registre o que de fato aconteceu, inclusive sugestões erradas da IA que foram descartadas.
- Sugestões de código: diga se foram aceitas como estavam, modificadas (o que mudou) ou descartadas.

## 4. Histórico de conversas

Exportações brutas das conversas com ferramentas de IA ficam em `docs/ai-conversations/` (instruções no README da pasta). Revise e remova dados sensíveis antes de commitar.

## 5. Logs do agente em execução

Diferente do DEVLOG: os logs das perguntas feitas **ao agente desenvolvido** ficam em `logs/` (JSONL) e na tabela de logs do banco. Campos: timestamp, pergunta, domínio previsto, confiança, agente escolhido, fontes/IDs consultados, latência, status, erro. Sem dados pessoais nem segredos.

## 6. Testes

Os casos oficiais estão em `data/testes/perguntas_avaliacao.json` (T001–T012). Toda mudança em orquestrador ou agente deve rodar esses casos e registrar o resultado no DEVLOG.
