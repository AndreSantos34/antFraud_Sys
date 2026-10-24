-- ============================================================
-- antFraud_Sys — Schema MySQL
-- Banco: antfraud_db
-- Charset: utf8mb4 / utf8mb4_0900_ai_ci
--
-- Este arquivo documenta o schema REAL do banco antfraud_db,
-- confirmado via SHOW CREATE TABLE no MySQL Server 8.0.
--
-- IMPORTANTE: este arquivo é documentação de referência.
-- O banco já existe — NÃO execute este arquivo em produção
-- sem garantir que as tabelas ainda não existem.
--
-- Para criar o banco do zero (ambiente limpo):
--   source /caminho/para/antfraud_db.sql
--
-- As tabelas também são verificadas automaticamente na
-- inicialização da aplicação via init_db() (checkfirst=True);
-- init_db() NÃO altera tabelas existentes.
-- ============================================================

-- ── Banco de dados ───────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS antfraud_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE antfraud_db;

-- ── Usuário de aplicação (executar como root) ────────────────
-- Substitua 'SENHA_FORTE' por uma senha real antes de executar.
-- CREATE USER IF NOT EXISTS 'antfraud_user'@'localhost'
--   IDENTIFIED BY 'SENHA_FORTE';
-- GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, DROP, REFERENCES
--   ON antfraud_db.* TO 'antfraud_user'@'localhost';
-- FLUSH PRIVILEGES;

-- ────────────────────────────────────────────────────────────
-- Tabela: transactions
-- Registra cada transação financeira processada pelo pipeline.
--
-- Campos NOT NULL obrigatórios (a aplicação deve sempre fornecê-los):
--   transaction_datetime, location, channel, device
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id                   BIGINT          NOT NULL AUTO_INCREMENT,
    transaction_id       VARCHAR(100)    NOT NULL,
    customer_id          VARCHAR(100)    NOT NULL,
    receiver_id          VARCHAR(100)    DEFAULT NULL,
    amount               DECIMAL(12, 2)  NOT NULL,
    transaction_datetime TIMESTAMP       NOT NULL,
    location             VARCHAR(255)    NOT NULL,
    channel              VARCHAR(100)    NOT NULL,
    device               VARCHAR(255)    NOT NULL,
    label                VARCHAR(30)     DEFAULT NULL   COMMENT 'Classificação final: normal / suspeita',
    reason               TEXT                           COMMENT 'Justificativa do Agente 1 (Rule Screener)',
    created_at           TIMESTAMP       NOT NULL       DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY  transaction_id             (transaction_id),
    KEY         idx_transactions_customer  (customer_id),
    KEY         idx_transactions_datetime  (transaction_datetime),

    CONSTRAINT transactions_chk_1
        CHECK (amount >= 0)

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Transações financeiras processadas pelo sistema antifraude';

-- ────────────────────────────────────────────────────────────
-- Tabela: cases
-- Dossiês de casos suspeitos com os resultados dos 4 agentes.
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cases (
    id                  BIGINT          NOT NULL AUTO_INCREMENT,
    case_id             VARCHAR(150)    NOT NULL,
    transaction_id      VARCHAR(100)    DEFAULT NULL   COMMENT 'FK para transactions.transaction_id; NULL se a transação for excluída',
    risk_score          INT             DEFAULT NULL   COMMENT 'Score de risco 0–100 (validado pelo CHECK e pela camada Pydantic)',
    risk_level          VARCHAR(50)     DEFAULT NULL   COMMENT 'Ex: crítico, alto, médio, baixo',
    urgency             VARCHAR(50)     DEFAULT NULL   COMMENT 'Ex: imediata, alta, moderada',
    status              VARCHAR(50)     NOT NULL       DEFAULT 'open' COMMENT 'Estado do caso: open / closed / reviewed',
    reason              TEXT            DEFAULT NULL   COMMENT 'Justificativa consolidada',
    recommended_action  TEXT            DEFAULT NULL   COMMENT 'Ação recomendada pelo Agente 4',
    agent_results       JSON            DEFAULT NULL   COMMENT 'Saídas combinadas dos Agentes 1, 2 e 3',
    final_result        JSON            DEFAULT NULL   COMMENT 'Saída do Agente 4 (IA Mestre)',
    created_at          TIMESTAMP       NOT NULL       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       NOT NULL       DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY  case_id                (case_id),
    KEY         idx_cases_transaction  (transaction_id),
    KEY         idx_cases_risk_level   (risk_level),

    -- Risk score deve estar entre 0 e 100.
    CONSTRAINT cases_chk_1
        CHECK (risk_score BETWEEN 0 AND 100),

    -- ON DELETE SET NULL: preserva o histórico do caso mesmo que a
    -- transação de origem seja removida da tabela transactions.
    -- Nota: sem ON UPDATE CASCADE (conforme banco real).
    CONSTRAINT fk_cases_transaction
        FOREIGN KEY (transaction_id)
        REFERENCES transactions (transaction_id)
        ON DELETE SET NULL

) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Dossiês de casos suspeitos investigados pelo pipeline de agentes';
