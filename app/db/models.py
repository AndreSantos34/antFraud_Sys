"""
Modelos ORM (SQLAlchemy declarativo) para as tabelas MySQL do antFraud_Sys.

Tabelas:
    transactions — transações financeiras analisadas pelo sistema.
    cases        — dossiês de casos suspeitos com resultados dos agentes.

Tipos MySQL usados (alinhados ao schema real do banco antfraud_db):
    BIGINT AUTO_INCREMENT   → chave primária numérica
    VARCHAR(100)            → identificadores de transação/cliente
    VARCHAR(150)            → identificador de caso
    DECIMAL(12, 2)          → valores monetários com precisão garantida
    TIMESTAMP               → data/hora (armazenado em UTC pela aplicação)
    JSON                    → dados estruturados dos agentes (MySQL >= 5.7.8)
    TEXT                    → textos longos
    INTEGER                 → risk_score (0–100)

Notas de compatibilidade MySQL:
    • Restrições CHECK são ignoradas silenciosamente no MySQL < 8.0.16;
      a validação de risk_score (0-100) é mantida na camada Pydantic.
    • ON DELETE SET NULL na FK de cases→transactions preserva o histórico
      de casos mesmo se a transação for excluída do registro.
    • O campo JSON é nativo no MySQL >= 5.7.8.
    • transaction_datetime, location, channel e device são NOT NULL no banco;
      a aplicação deve sempre fornecer esses valores.

Schema real confirmado via SHOW CREATE TABLE (MySQL Server 8.0).
"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Transaction(Base):
    """
    Tabela `transactions` — espelho das transações financeiras processadas.

    Campos NOT NULL no banco real: transaction_datetime, location, channel, device.
    O código que chama save_transaction() deve garantir esses campos.
    """
    __tablename__ = "transactions"

    __table_args__ = (
        # Índice adicional presente no banco real
        Index("idx_transactions_datetime", "transaction_datetime"),
        # CHECK constraint presente no banco real (amount >= 0)
        CheckConstraint("amount >= 0", name="transactions_chk_1"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    transaction_id = Column(String(100), nullable=False, unique=True, index=True)
    customer_id = Column(String(100), nullable=False, index=True)
    receiver_id = Column(String(100), nullable=True)
    amount = Column(Numeric(12, 2), nullable=False)
    # NOT NULL no banco: a aplicação deve sempre fornecer este campo
    transaction_datetime = Column(DateTime, nullable=False)
    # NOT NULL no banco: a aplicação deve sempre fornecer estes campos
    location = Column(String(255), nullable=False)
    channel = Column(String(100), nullable=False)
    device = Column(String(255), nullable=False)
    label = Column(String(30), nullable=True)     # classificação final (normal/suspeita)
    reason = Column(Text, nullable=True)           # justificativa do agente 1
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relacionamento reverso: casos associados a esta transação
    cases = relationship(
        "Case",
        back_populates="transaction_ref",
        foreign_keys="Case.transaction_id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Transaction {self.transaction_id} amount={self.amount}>"


class Case(Base):
    """
    Tabela `cases` — dossiês de casos suspeitos investigados.

    Chave estrangeira para transactions.transaction_id com ON DELETE SET NULL:
    se uma transação for excluída, o caso é preservado com transaction_id = NULL.
    """
    __tablename__ = "cases"

    __table_args__ = (
        # CHECK constraint presente no banco real
        CheckConstraint("risk_score between 0 and 100", name="cases_chk_1"),
        # Índice adicional presente no banco real
        Index("idx_cases_risk_level", "risk_level"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # VARCHAR(150) conforme banco real
    case_id = Column(String(150), nullable=False, unique=True, index=True)

    # FK para transactions.transaction_id (não para transactions.id)
    # ON DELETE SET NULL: o caso sobrevive mesmo se a transação for removida
    # Nome da constraint alinhado ao banco real: fk_cases_transaction
    transaction_id = Column(
        String(100),
        ForeignKey(
            "transactions.transaction_id",
            ondelete="SET NULL",
            name="fk_cases_transaction",
        ),
        nullable=True,
        index=True,
    )

    risk_score = Column(Integer, nullable=True)       # 0–100; INT no banco real
    risk_level = Column(String(50), nullable=True)    # ex: "crítico", "alto", "médio"
    urgency = Column(String(50), nullable=True)
    status = Column(String(50), nullable=False, default="open")
    reason = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=True)
    agent_results = Column(JSON, nullable=True)       # saídas combinadas dos agentes 1–3
    final_result = Column(JSON, nullable=True)        # saída do agente 4 (IA Mestre)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacionamento com Transaction (pode ser None se ON DELETE SET NULL)
    transaction_ref = relationship(
        "Transaction",
        back_populates="cases",
        foreign_keys=[transaction_id],
    )

    def __repr__(self) -> str:
        return f"<Case {self.case_id} score={self.risk_score}>"


def init_db() -> None:
    """
    Verifica se as tabelas existem no banco MySQL.

    Usa checkfirst=True: não cria nem altera tabelas que já existem.
    Não é uma ferramenta de migração — não altera colunas ou índices existentes.
    Se o schema real divergir dos modelos, nenhuma alteração automática ocorre.
    """
    from app.db.database import get_engine
    import logging

    logger = logging.getLogger(__name__)
    engine = get_engine()
    if engine is None:
        logger.warning("[DB] init_db: DATABASE_URL não configurada — tabelas não criadas.")
        return

    Base.metadata.create_all(engine, checkfirst=True)
    logger.info("[DB] Tabelas verificadas: transactions, cases")
