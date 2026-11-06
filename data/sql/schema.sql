-- Esquema de referência para PostgreSQL
-- Execute em um banco de desenvolvimento. Dados são sintéticos.

CREATE TABLE IF NOT EXISTS lancamentos_financeiros (
    id_lancamento VARCHAR(16) PRIMARY KEY,
    data_competencia DATE NOT NULL,
    data_vencimento DATE NOT NULL,
    tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('Receita','Despesa')),
    categoria VARCHAR(80) NOT NULL,
    descricao VARCHAR(120) NOT NULL,
    centro_custo VARCHAR(10) NOT NULL,
    departamento VARCHAR(60) NOT NULL,
    contraparte VARCHAR(120) NOT NULL,
    valor_brl NUMERIC(14,2) NOT NULL CHECK (valor_brl >= 0),
    status VARCHAR(16) NOT NULL CHECK (status IN ('Pago','Pendente','Atrasado')),
    metodo_pagamento VARCHAR(40),
    observacao TEXT
);

CREATE TABLE IF NOT EXISTS orcamento_mensal (
    ano SMALLINT NOT NULL,
    mes CHAR(2) NOT NULL,
    centro_custo VARCHAR(10) NOT NULL,
    departamento VARCHAR(60) NOT NULL,
    orcamento_brl NUMERIC(14,2) NOT NULL CHECK (orcamento_brl >= 0),
    versao_orcamento VARCHAR(30) NOT NULL,
    observacao TEXT,
    PRIMARY KEY (ano, mes, centro_custo)
);

CREATE TABLE IF NOT EXISTS manifestacoes_ouvidoria (
    protocolo VARCHAR(16) PRIMARY KEY,
    data_abertura DATE NOT NULL,
    categoria VARCHAR(60) NOT NULL,
    assunto VARCHAR(120) NOT NULL,
    canal_entrada VARCHAR(20) NOT NULL,
    prioridade VARCHAR(12) NOT NULL,
    status VARCHAR(35) NOT NULL,
    area_responsavel VARCHAR(80) NOT NULL,
    resumo_manifestacao TEXT NOT NULL,
    data_resposta DATE,
    resposta_resumo TEXT,
    prazo_referencia_dias SMALLINT NOT NULL,
    dados_pessoais TEXT,
    observacao TEXT
);

CREATE INDEX IF NOT EXISTS idx_fin_data_tipo ON lancamentos_financeiros (data_competencia, tipo);
CREATE INDEX IF NOT EXISTS idx_fin_departamento ON lancamentos_financeiros (departamento);
CREATE INDEX IF NOT EXISTS idx_ouv_status ON manifestacoes_ouvidoria (status);
CREATE INDEX IF NOT EXISTS idx_ouv_categoria ON manifestacoes_ouvidoria (categoria);
CREATE INDEX IF NOT EXISTS idx_ouv_data_abertura ON manifestacoes_ouvidoria (data_abertura);
