"""
Monitor Background — Núclea Fraud Detection
─────────────────────────────────────────────
Processo que roda em segundo plano junto com a API.
Consome transações do simulador em tempo real, envia cada uma pelo pipeline
de 4 agentes e publica os alertas críticos via WebSocket para o dashboard.

Em produção real (Núclea), o método _fetch_next_transaction() seria
substituído por um consumidor Kafka/RabbitMQ ou listener de webhook.
"""
import asyncio
import logging
from datetime import datetime
from typing import Callable

from app import orchestrator
from app.simulator import generate_single
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class FraudMonitor:
    """
    Monitor de fraudes em background.

    Atributos controlados externamente:
        running:      True enquanto o loop está ativo.
        alert_callbacks: funções registradas para receber alertas críticos
                         (usadas pelo WebSocket para push ao frontend).
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self.running: bool = False
        self._alert_callbacks: list[Callable] = []
        self._processed: int = 0
        self._escalated: int = 0
        self._started_at: datetime | None = None

    # ── Registro de callbacks ─────────────────────────────────────────────────

    def register_alert_callback(self, callback: Callable) -> None:
        """Registra uma função que será chamada quando um alerta crítico for gerado."""
        self._alert_callbacks.append(callback)

    def unregister_alert_callback(self, callback: Callable) -> None:
        self._alert_callbacks = [cb for cb in self._alert_callbacks if cb != callback]

    # ── Fonte de transações ───────────────────────────────────────────────────

    async def _fetch_next_transaction(self) -> dict:
        """
        Obtém a próxima transação a processar.

        PROTÓTIPO: retorna uma transação gerada pelo simulador.
        PRODUÇÃO:  substituir por await kafka_consumer.get() ou similar.
        """
        # Simula latência variável de chegada de transações (0.5s a 3s)
        interval = self._settings.monitor_interval_seconds
        await asyncio.sleep(interval)
        return generate_single()

    # ── Processamento ─────────────────────────────────────────────────────────

    async def _process(self, transaction: dict) -> None:
        """Envia a transação pelo pipeline e notifica callbacks se for crítico."""
        tx_id = transaction.get("transaction_id", "?")
        logger.info("[Monitor] Processando transação %s", tx_id)

        try:
            # Executa em thread separada para não bloquear o event loop
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: orchestrator.analyze_transaction(transaction),
            )
        except Exception as exc:
            logger.error("[Monitor] Erro ao processar %s: %s", tx_id, exc)
            return

        self._processed += 1
        escalated = result.get("escalated", False)

        if escalated:
            self._escalated += 1
            master = result.get("agent_4_master") or {}
            score = master.get("risk_score", 0)
            urgency = master.get("urgency", "desconhecida")
            alert = master.get("cybersecurity_alert", {})

            logger.warning(
                "[Monitor] ⚠️  ALERTA — %s | Score: %d | Urgência: %s",
                tx_id, score, urgency,
            )

            # Notifica todos os listeners WebSocket registrados
            event = {
                "type": "fraud_alert",
                "timestamp": datetime.now().isoformat(),
                "transaction_id": tx_id,
                "risk_score": score,
                "risk_level": master.get("risk_level"),
                "urgency": urgency,
                "recommended_action": master.get("recommended_action"),
                "alert_subject": alert.get("subject"),
                "alert_priority": alert.get("priority"),
                "case_summary": alert.get("case_summary"),
                "immediate_actions": alert.get("immediate_actions", []),
                "total_criteria_met": result.get("total_criteria_met", 0),
                "simulation_profile": transaction.get("simulation_profile"),
            }

            for callback in list(self._alert_callbacks):
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as exc:
                    logger.error("[Monitor] Erro em callback: %s", exc)
        else:
            logger.debug("[Monitor] ✅  Normal — %s", tx_id)

    # ── Loop principal ────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Inicia o loop de monitoramento em background."""
        self.running = True
        self._started_at = datetime.now()
        logger.info("[Monitor] 🚀 Monitor Núclea iniciado — aguardando transações...")

        while self.running:
            try:
                transaction = await self._fetch_next_transaction()
                asyncio.create_task(self._process(transaction))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[Monitor] Erro no loop principal: %s", exc)
                await asyncio.sleep(2)

        logger.info("[Monitor] 🛑 Monitor encerrado.")

    def stop(self) -> None:
        """Para o loop de monitoramento."""
        self.running = False

    def stats(self) -> dict:
        """Retorna estatísticas do monitor para o health check."""
        uptime = None
        if self._started_at:
            uptime = str(datetime.now() - self._started_at).split(".")[0]
        escalation_rate = (
            round(self._escalated / self._processed * 100, 1)
            if self._processed > 0 else 0.0
        )
        return {
            "running": self.running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime": uptime,
            "transactions_processed": self._processed,
            "escalated_to_investigation": self._escalated,
            "escalation_rate_pct": escalation_rate,
        }


# Instância singleton compartilhada com a API
fraud_monitor = FraudMonitor()
