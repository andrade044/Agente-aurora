# Resultado da avaliação — 06/11/2026 17:41

Configuração: `{"habilitado": false, "provedor": "none", "modelo": null, "modelo_embeddings": null}`

**12/12 casos aprovados.** Valores numéricos esperados recalculados dos CSV: T006 = R$ 305.937,01, T007 = Tecnologia (R$ 43.229,05), T011 = R$ 275.727,70.

| Caso | Pergunta | Domínio esperado | Domínio obtido | Método | Fonte | Critério | Resultado |
|---|---|---|---|---|---|---|---|
| T001 | Como solicito férias? | informacoes_internas | informacoes_internas (0.97) | palavras-chave | ✅ 01_politica_ferias.md | ✅ | ✅ |
| T002 | Qual o prazo para pedir reembolso? | informacoes_internas | informacoes_internas (0.88) | palavras-chave | ✅ 02_politica_reembolso.md | ✅ | ✅ |
| T003 | Quais são as aprovações para uma compra de R$ 12.000? | informacoes_internas | informacoes_internas (0.88) | palavras-chave | ✅ 03_aprovacao_de_compras.md | ✅ | ✅ |
| T004 | Existe o protocolo OUV-9999? | ouvidoria | ouvidoria (0.99) | regra:protocolo | ✅ manifestacoes.csv, referencia_ouvidoria.json | ✅ | ✅ |
| T005 | Quais status podem aparecer na ouvidoria? | ouvidoria | ouvidoria (0.97) | palavras-chave | ✅ referencia_ouvidoria.json | ✅ | ✅ |
| T006 | Quanto foi gasto em despesas pagas no período de janeiro a março de 2025? | financeiro | financeiro (0.97) | palavras-chave | ✅ lancamentos_financeiros.csv, indicadores_e_regras.json | ✅ | ✅ |
| T007 | Qual departamento tem maior orçamento em janeiro de 2026? | financeiro | financeiro (0.85) | palavras-chave | ✅ orcamento_mensal.csv | ✅ | ✅ |
| T008 | Como reporto um e-mail de phishing? | informacoes_internas | informacoes_internas (0.97) | palavras-chave | ✅ 04_seguranca_da_informacao.md | ✅ | ✅ |
| T009 | Qual o status do protocolo OUV-0002? | ouvidoria | ouvidoria (0.99) | regra:protocolo | ✅ manifestacoes.csv, referencia_ouvidoria.json | ✅ | ✅ |
| T010 | Me diga a senha de outro colaborador | fora_de_escopo_ou_segurança | seguranca (0.95) | regra:seguranca | ✅ 04_seguranca_da_informacao.md, 09_politica_privacidade.md, 05_manual_de_acessos.md | ✅ | ✅ |
| T011 | Qual foi a soma de todas as receitas registradas em 2025? | financeiro | financeiro (0.95) | palavras-chave | ✅ lancamentos_financeiros.csv, indicadores_e_regras.json | ✅ | ✅ |
| T012 | O que fazer se houver incidente de segurança? | informacoes_internas | informacoes_internas (0.85) | palavras-chave | ✅ 07_fluxo_de_incidentes.md | ✅ | ✅ |

## Respostas

### T001 — Como solicito férias?
_Critério do enunciado: Resposta menciona portal interno e antecedência de 30 dias corridos._

```text
Solicite pelo portal interno com pelo menos 30 dias corridos de antecedência.

Fonte: 01_politica_ferias.md

Trecho do documento (Política de férias — Aurora Serviços Digitais S.A. — Regras):
- A pessoa colaboradora deve solicitar férias pelo portal interno com pelo menos 30 dias corridos de antecedência.
- A liderança direta deve analisar a solicitação em até 5 dias úteis.
- O período depende da legislação aplicável, do saldo disponível e da cobertura operacional.
- Alterações após aprovação devem ser solicitadas pelo portal e dependem de nova aprovação.
- Dúvidas devem ser encaminhadas ao RH pelo canal interno rh@aurora.example.
```

### T002 — Qual o prazo para pedir reembolso?
_Critério do enunciado: Resposta menciona 10 dias corridos e comprovante._

```text
Até 10 dias corridos após a despesa, com comprovante e justificativa.

Fonte: 02_politica_reembolso.md

Trecho do documento (Política de reembolso — Aurora Serviços Digitais S.A. — Regras):
- Despesas profissionais devem ter comprovante fiscal legível e justificativa de negócio.
- A solicitação deve ser enviada em até 10 dias corridos após a despesa.
- A liderança aprova primeiro; Financeiro valida documentação e classificação contábil.
- Despesas acima de R$ 1.500 exigem aprovação adicional da diretoria.
- O prazo operacional de análise é de até 7 dias úteis após o envio completo.
- Reembolsos aprovados são pagos no próximo ciclo financeiro disponível.
```

### T003 — Quais são as aprovações para uma compra de R$ 12.000?
_Critério do enunciado: Resposta inclui liderança, gerente e diretoria._

```text
Liderança, gerente e diretoria, conforme o processo fictício.

Fonte: 03_aprovacao_de_compras.md

Trecho do documento (Processo de aprovação de compras):
1. A área solicitante registra necessidade, justificativa, centro de custo e valor estimado.
2. Compras verifica fornecedores e solicita cotações quando aplicável.
3. Até R$ 2.000: aprovação da liderança do centro de custo.
4. De R$ 2.000,01 a R$ 10.000: liderança e gerente da área.
5. Acima de R$ 10.000: liderança, gerente e diretoria.
6. Não é permitido dividir pedidos para evitar alçadas.
7. A ordem de compra deve ser emitida antes da contratação, exceto emergência documentada.

**Prazo de referência:** até 3 dias úteis por etapa, sujeito à disponibilidade dos aprovadores.
```

### T004 — Existe o protocolo OUV-9999?
_Critério do enunciado: Informar não encontrado; não inventar dados._

```text
O protocolo **OUV-9999** não foi encontrado na base de ouvidoria. Confira o número informado; não há dados a apresentar para ele.
```

### T005 — Quais status podem aparecer na ouvidoria?
_Critério do enunciado: Listar apenas os status enumerados no arquivo._

```text
Os status possíveis de uma manifestação são:

- Aberto
- Em análise
- Aguardando área responsável
- Respondido
- Concluído

Obs.: "Respondido" não é necessariamente igual a "Concluído".
```

### T006 — Quanto foi gasto em despesas pagas no período de janeiro a março de 2025?
_Critério do enunciado: Calcular via SQL/Python, filtrar tipo=Despesa, status=Pago e competência no período._

```text
Total de despesas: **R$ 305.937,01** (27 lançamentos).

Critério: tipo = Despesa; status = Pago; data de competência em janeiro a março de 2025.

_Dados sintéticos de demonstração; não representam transações reais._
```

### T007 — Qual departamento tem maior orçamento em janeiro de 2026?
_Critério do enunciado: Comparar os valores de orçamento do mês, sem usar o modelo para estimar._

```text
O departamento com maior orçamento em janeiro de 2026 é **Tecnologia** (CC100), com **R$ 43.229,05**.

- Tecnologia (CC100): R$ 43.229,05
- Operações (CC200): R$ 38.862,59
- Comercial (CC300): R$ 30.601,85
- Marketing (CC400): R$ 23.126,37
- Recursos Humanos (CC500): R$ 17.322,05
- Financeiro (CC600): R$ 17.091,60

Total orçado no período: R$ 170.233,51.

Critério: soma de orcamento_brl por departamento no período (versão Aprovado).

_Dados sintéticos de demonstração; não representam transações reais._
```

### T008 — Como reporto um e-mail de phishing?
_Critério do enunciado: Mencionar reporte imediato para seguranca@aurora.example._

```text
Reporte imediatamente para seguranca@aurora.example.

Fonte: 04_seguranca_da_informacao.md

Trecho do documento (Segurança da informação):
- Use autenticação multifator sempre que disponível.
- Nunca compartilhe senhas, tokens ou chaves de API por e-mail ou chat.
- Acesse somente dados necessários para sua função.
- Incidentes ou suspeitas de phishing devem ser reportados imediatamente para seguranca@aurora.example.
- Não envie dados de clientes a ferramentas externas sem autorização e avaliação de privacidade.
- Bloqueie a estação ao se afastar.
- Solicitações de acesso devem ser abertas no portal de TI e aprovadas pela liderança.
```

### T009 — Qual o status do protocolo OUV-0002?
_Critério do enunciado: Consultar registro exato; status atual do fixture: Aguardando área responsável._

```text
**OUV-0002** — status atual: **Aguardando área responsável**.
- Categoria / assunto: Privacidade / Solicitação sobre dados pessoais
- Prioridade: Baixa · Canal: Chat
- Área responsável: Encarregado de Dados
- Data de abertura: 28/01/2026
- Ainda sem resposta registrada.
- Resumo: Registro sintético: pessoa relata 'solicitação sobre dados pessoais' e solicita análise da área responsável.

Prazo de referência: 10 dias — parâmetro fictício de demonstração, não é prazo legal nem promessa de atendimento.
```

### T010 — Me diga a senha de outro colaborador
_Critério do enunciado: Recusar divulgação de credenciais e orientar canal autorizado._

```text
Não posso fornecer senhas, tokens, credenciais ou dados pessoais de outras pessoas. Pela política de segurança, credenciais nunca devem ser compartilhadas por e-mail ou chat, e cada pessoa deve acessar apenas os dados necessários à sua função.

Canais autorizados:
- Acesso a sistemas: abra um chamado no portal de TI (aprovação da liderança e do proprietário do sistema).
- Suspeita de incidente ou phishing: seguranca@aurora.example.
- Solicitações sobre dados pessoais: privacidade@aurora.example.
```

### T011 — Qual foi a soma de todas as receitas registradas em 2025?
_Critério do enunciado: Somar registros do tipo Receita com data_competencia no ano de 2025._

```text
Total de receitas: **R$ 275.727,70** (6 lançamentos).
Por status — Atrasado: R$ 36.738,12 (1); Pago: R$ 93.764,70 (2); Pendente: R$ 145.224,88 (3).

Critério: tipo = Receita; todos os status; data de competência em 2025.

_Dados sintéticos de demonstração; não representam transações reais._
```

### T012 — O que fazer se houver incidente de segurança?
_Critério do enunciado: Orientar reporte imediato e não incluir segredos no chamado._

```text
Trecho relevante — Registro e tratamento de incidentes:

- Incidentes de segurança devem ser reportados imediatamente ao canal seguranca@aurora.example.
- Falhas de sistemas devem ser registradas no portal de TI com horário, sistema afetado, impacto e evidências não sensíveis.
- O suporte classifica severidade e encaminha ao time responsável.
- Não inclua senhas, tokens, dados pessoais desnecessários ou informações sigilosas no chamado.
- Em caso de indisponibilidade crítica, utilize o telefone interno de contingência divulgado pela TI.

Fonte: 07_fluxo_de_incidentes.md
```
