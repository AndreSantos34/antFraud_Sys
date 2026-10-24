"""
WebSocket — Streaming de Alertas em Tempo Real
────────────────────────────────────────────────
Permite que o dashboard da Núclea receba alertas de fraude instantaneamente
via WebSocket, sem necessidade de polling.

Conexão: ws://host:8000/ws/alerts?api_key=<API_SECRET_KEY>
"""
import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from app.core.config import get_settings
from app.monitor import fraud_monitor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["realtime"])

# Conjunto de conexões WebSocket ativas
_active_connections: set[WebSocket] = set()


async def _broadcast(event: dict) -> None:
    """Envia um evento para todas as conexões WebSocket ativas."""
    if not _active_connections:
        return
    payload = json.dumps(event, ensure_ascii=False)
    dead: set[WebSocket] = set()
    for ws in list(_active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    # Remove apenas as conexões encerradas do set de conexões ativas.
    # O callback _broadcast só é desregistrado quando não há mais conexões vivas
    # (feito no bloco finally do handler websocket_alerts).
    for ws in dead:
        _active_connections.discard(ws)


@router.websocket("/ws/alerts")
async def websocket_alerts(
    websocket: WebSocket,
    api_key: str = Query(..., description="API Key para autenticação"),
):
    """
    WebSocket para streaming de alertas de fraude em tempo real.

    Eventos emitidos pelo servidor:
    - `connected`    → confirmação de conexão
    - `fraud_alert`  → alerta gerado pela IA Mestre para transação suspeita
    - `monitor_stats`→ estatísticas do monitor (enviadas a cada 30s)
    - `heartbeat`    → ping periódico para manter a conexão viva

    Envie `{"action": "stats"}` para solicitar estatísticas imediatas.
    """
    settings = get_settings()

    # Valida a API Key na query string
    if api_key != settings.api_secret_key:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("[WS] Tentativa de conexão com API Key inválida")
        return

    await websocket.accept()
    _active_connections.add(websocket)
    fraud_monitor.register_alert_callback(_broadcast)
    logger.info("[WS] Cliente conectado. Total ativo: %d", len(_active_connections))

    # Confirmação de conexão
    await websocket.send_json({
        "type": "connected",
        "message": "Conectado ao monitor de fraudes Núclea.",
        "monitor_running": fraud_monitor.running,
    })

    try:
        # Loop: escuta mensagens do cliente + mantém heartbeat
        heartbeat_task = asyncio.create_task(_heartbeat(websocket))
        stats_task = asyncio.create_task(_periodic_stats(websocket))

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
                msg = json.loads(data)
                if msg.get("action") == "stats":
                    await websocket.send_json({
                        "type": "monitor_stats",
                        **fraud_monitor.stats(),
                    })
            except asyncio.TimeoutError:
                # Sem mensagem em 60s — envia heartbeat e continua
                continue
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        logger.info("[WS] Cliente desconectado.")
    finally:
        _active_connections.discard(websocket)
        heartbeat_task.cancel()
        stats_task.cancel()
        if not _active_connections:
            fraud_monitor.unregister_alert_callback(_broadcast)
        logger.info("[WS] Conexões ativas: %d", len(_active_connections))


async def _heartbeat(websocket: WebSocket) -> None:
    """Envia ping a cada 25 segundos para manter a conexão viva."""
    while True:
        await asyncio.sleep(25)
        try:
            await websocket.send_json({"type": "heartbeat"})
        except Exception:
            break


async def _periodic_stats(websocket: WebSocket) -> None:
    """Envia estatísticas do monitor a cada 30 segundos."""
    while True:
        await asyncio.sleep(30)
        try:
            await websocket.send_json({
                "type": "monitor_stats",
                **fraud_monitor.stats(),
            })
        except Exception:
            break
