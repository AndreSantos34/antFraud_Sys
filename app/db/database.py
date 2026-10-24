"""
Gerenciamento de conexão com o MySQL via SQLAlchemy (síncrono).

• O engine é criado sob demanda na primeira chamada a get_engine().
• get_session() fornece um context-manager seguro para transações.
• Se DATABASE_URL não estiver configurada, o banco permanece desabilitado
  e a aplicação cai de volta para persistência em arquivo JSON —
  nenhuma funcionalidade é perdida sem o MySQL.
"""
import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def _build_engine():
    """Cria o engine SQLAlchemy a partir de DATABASE_URL."""
    settings = get_settings()
    url = settings.database_url
    if not url:
        logger.warning(
            "[DB] DATABASE_URL não configurada — MySQL desabilitado. "
            "A aplicação operará em modo JSON-only (sem persistência no banco). "
            "Configure DATABASE_URL no arquivo .env para habilitar o MySQL."
        )
        return None

    engine = create_engine(
        url,
        # PyMySQL é síncrono — pool simples é suficiente para protótipo
        pool_pre_ping=True,       # valida a conexão antes de reutilizar
        pool_recycle=1800,        # recicla conexões após 30 min (evita timeout do MySQL)
        echo=False,               # True para ver SQL no log (só desenvolvimento)
        connect_args={
            "connect_timeout": 10,
        },
    )
    return engine


def get_engine():
    """Retorna o engine singleton, criando-o na primeira chamada."""
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine()
        if _engine is not None:
            _SessionLocal = sessionmaker(
                bind=_engine,
                autocommit=False,
                autoflush=False,
            )
            logger.info("[DB] Engine MySQL criado: %s", _engine.url.render_as_string(hide_password=True))
    return _engine


def is_db_available() -> bool:
    """Verifica se o banco está configurado e acessível."""
    engine = get_engine()
    if engine is None:
        return False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("[DB] MySQL indisponível: %s", exc)
        return False


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Context-manager que fornece uma Session transacional.

    Uso:
        with get_session() as session:
            session.add(obj)
    """
    if _SessionLocal is None:
        get_engine()  # tenta inicializar
    if _SessionLocal is None:
        raise RuntimeError("DATABASE_URL não configurada — MySQL indisponível.")

    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
