"""
Segurança — autenticação por API Key para endpoints protegidos.
Header esperado: X-API-Key: <valor configurado em API_SECRET_KEY>
"""
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(api_key: str = Security(_api_key_header)) -> str:
    """
    Dependência FastAPI que valida o header X-API-Key.
    Use como: `Depends(require_api_key)` nos endpoints protegidos.
    """
    settings = get_settings()
    if not api_key or api_key != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida ou ausente. Inclua o header: X-API-Key",
        )
    return api_key
