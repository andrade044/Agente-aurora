# Ingestão e uso com FastAPI

## Dados tabulares
- Financeiro e Ouvidoria: carregar CSV para PostgreSQL.
- Converta `valor_brl` para `NUMERIC(14,2)` na importação; não use ponto flutuante binário para cálculos financeiros.
- Valide datas e os valores enumerados de `tipo`, `status`, `prioridade` e `categoria`.
- Restrinja consultas às tabelas/domínios permitidos; não execute SQL arbitrário gerado pelo modelo sem validação.

## Documentos RAG
1. Leia os arquivos `.md` em `informacoes_internas/`.
2. Divida por títulos/seções ou em chunks de aproximadamente 400–800 tokens com sobreposição moderada.
3. Grave metadados como `domain=informacoes_internas`, `source=<arquivo>`, `document_version=<versão>`.
4. Recupere os trechos relevantes e instrua o modelo a responder apenas com base neles.
5. Inclua o nome do arquivo-fonte na resposta.

## Orquestração
- Financeiro: consultas agregadas e filtros devem usar SQL/Python determinístico.
- Informações internas: recuperação semântica dos Markdown/FAQ.
- Ouvidoria: busca exata por protocolo e filtros por status/categoria/data.
- Baixa confiança ou pergunta ambígua: peça esclarecimento, sem inventar uma categoria.
- Fora de escopo: explique que os três agentes só cobrem os domínios definidos.

## Logs
Registre timestamp, pergunta, domínio previsto, agente escolhido, fontes/IDs consultados, latência, status e erro. Evite gravar dados pessoais ou segredos. Para este conjunto sintético, é possível usar os protocolos fictícios nos logs de teste.
