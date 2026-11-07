-- Tabelas auxiliares da aplicação (além de data/sql/schema.sql, fornecido no pacote).

CREATE TABLE IF NOT EXISTS rag_chunks (
    id              VARCHAR(80) PRIMARY KEY,      -- ex.: 01_politica_ferias.md#regras
    domain          VARCHAR(40)  NOT NULL,
    source          VARCHAR(120) NOT NULL,        -- arquivo de origem
    document_version VARCHAR(40),
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    content_hash    CHAR(64) NOT NULL,
    embedding_model VARCHAR(80),
    embedding       DOUBLE PRECISION[]            -- NULL quando não há provedor de embeddings
);

CREATE TABLE IF NOT EXISTS agent_logs (
    id                  UUID PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL,
    pergunta            TEXT NOT NULL,
    dominio_previsto    VARCHAR(40),
    confianca           NUMERIC(4,3),
    metodo_classificacao VARCHAR(30),
    agente              VARCHAR(40),
    fontes              JSONB,
    ids_consultados     JSONB,
    latencia_ms         INTEGER,
    status              VARCHAR(20) NOT NULL,
    erro                TEXT,
    llm_usado           BOOLEAN,
    detalhes            JSONB
);

-- colunas adicionadas depois da primeira versão (bancos já existentes recebem via ALTER)
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS pergunta_interpretada TEXT;
ALTER TABLE agent_logs ADD COLUMN IF NOT EXISTS resposta TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_logs_ts ON agent_logs (ts DESC);
