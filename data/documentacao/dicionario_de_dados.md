# Dicionário de dados

## Financeiro — `lancamentos_financeiros.csv`
- `id_lancamento`: identificador único do lançamento.
- `data_competencia`: data de competência (ISO).
- `data_vencimento`: vencimento previsto (ISO).
- `tipo`: `Receita` ou `Despesa`.
- `categoria`: classificação contábil simplificada.
- `descricao`: descrição curta.
- `centro_custo`: código CC100–CC600.
- `departamento`: área organizacional fictícia.
- `contraparte`: cliente ou fornecedor fictício.
- `valor_brl`: valor decimal em reais, armazenado como texto no CSV.
- `status`: `Pago`, `Pendente` ou `Atrasado`.
- `metodo_pagamento`: método de liquidação/recebimento.
- `observacao`: aviso de que é dado sintético.

## Financeiro — `orcamento_mensal.csv`
- `ano`, `mes`: período orçamentário.
- `centro_custo`, `departamento`: área responsável.
- `orcamento_brl`: orçamento mensal fictício aprovado.
- `versao_orcamento`: versão de referência.
- `observacao`: aviso de dado sintético.

## Ouvidoria — `manifestacoes.csv`
- `protocolo`: identificador sintético OUV-NNNN.
- `data_abertura`: data de abertura.
- `categoria`, `assunto`: classificação da manifestação.
- `canal_entrada`: Portal, E-mail, Telefone ou Chat.
- `prioridade`: Baixa, Média, Alta ou Crítica.
- `status`: Aberto, Em análise, Aguardando área responsável, Respondido ou Concluído.
- `area_responsavel`: equipe fictícia responsável.
- `resumo_manifestacao`: resumo sintético, sem identificadores pessoais.
- `data_resposta`: data da resposta, vazia se ainda não respondida.
- `resposta_resumo`: resposta padronizada, vazia se ainda não respondida.
- `prazo_referencia_dias`: parâmetro demonstrativo de 10 dias, não prazo legal.
- `dados_pessoais`: indicação de ausência de dados pessoais.
- `observacao`: aviso de dado sintético.

## Informações internas
Cada arquivo Markdown contém política/procedimento fictício, versão, data, regras e limites de resposta. O JSON `faq_interno.json` contém pares de pergunta/resposta e referência ao documento de origem.
