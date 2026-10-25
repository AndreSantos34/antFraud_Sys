"""
Monitor Background — AntFraud_Sys
───────────────────────────────────
Loop assíncrono que processa transações simuladas continuamente em segundo plano.
Independente de WebSocket — fechar conexões não interrompe o processamento.

Emite eventos WebSocket em cada estado do pipeline:
  ANALYZING            → transação aceita, pipeline iniciado
  COMPLETED            → pipeline concluído (transação normal ou suspeita processada)
  REQUIRES_HUMAN_REVIEW → risco alto/crítico ou falhas no pipeline
  FAILED               → exceção não tratada (não deve ocorrer com fallbacks ativos)

Em produção: substituir _fetch_next_transaction() por consumidor Kafka/RabbitMQ.
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
    Monitor de fraudes em background — independente de WebSocket.

    A ingestão e o processamento continuam mesmo sem clientes conectados.
    Os callbacks WebSocket são notificados apenas quando disponíveis.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self.running: bool = False
        self._alert_callbacks: list[Callable] = []
        self._processed: int = 0
        self._escalated: int = 0
        self._requires_review: int = 0
        self._failed: int = 0
        self._started_at: datetime | None = None

    # ── Callbacks WebSocket ────────────────────────────────────────────────────

    def register_alert_callback(self, callback: Callable) -> None:
        """Registra callback para push de eventos ao frontend via WebSocket."""
        if callback not in self._alert_callbacks:
            self._alert_callbacks.append(callback)

    def unregister_alert_callback(self, callback: Callable) -> None:
        self._alert_callbacks = [cb for cb in self._alert_callbacks if cb != callback]

    async def _emit(self, event: dict) -> None:
        """Envia evento para todos os callbacks registrados (sem bloquear o loop)."""
        for callback in list(self._alert_callbacks):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as exc:
                logger.error("[Monitor] Erro em callback: %s", exc)

    # ── Fonte de transações ────────────────────────────────────────────────────

    async def _fetch_next_transaction(self) -> dict:
        """
        PROTÓTIPO: gera transação via simulador.
        PRODUÇÃO:  substituir por await kafka_consumer.get() ou similar.
        """
        await asyncio.sleep(self._settings.monitor_interval_seconds)
        return generate_single()

    # ── Processamento ──────────────────────────────────────────────────────────

    async def _process(self, transaction: dict) -> None:
        """
        Processa uma transação pelo pipeline de 4 agentes.
        Emite eventos WebSocket em cada transição de estado.
        """
        tx_id = transaction.get("transaction_id", "?")
        trace_id = "pending"

        # ── Estado: ANALYZING ─────────────────────────────────────────────────
        await self._emit({
            "type": "status_update",
            "status": "ANALYZING",
            "transaction_id": tx_id,
            "timestamp": datetime.now().isoformat(),
            "message": f"Pipeline iniciado para {tx_id}.",
        })

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: orchestrator.analyze_transaction(transaction),
            )
        except Exception as exc:
            logger.error("[Monitor] Erro fatal ao processar %s: %s", tx_id, exc)
            self._failed += 1
            await self._emit({
                "type": "status_update",
                "status": "FAILED",
                "transaction_id": tx_id,
                "timestamp": datetime.now().isoformat(),
                "message": f"Falha no pipeline: {exc}",
            })
            return

        self._processed += 1
        escalated      = result.get("escalated", False)
        status         = result.get("processing_status", "COMPLETED")
        trace_id       = result.get("trace_id", "")
        final_score    = result.get("final_risk_score", 0)
        final_level    = result.get("final_risk_level", "minimo")
        master         = result.get("agent_4_master") or {}
        pipeline_errors = result.get("agent_4_master", {}).get("pipeline_errors", []) if master else []

        if escalated:
            self._escalated += 1
            if status == "REQUIRES_HUMAN_REVIEW":
                self._requires_review += 1

        # ── Estado final: COMPLETED / REQUIRES_HUMAN_REVIEW ──────────────────
        log_level = logging.WARNING if escalated else logging.DEBUG
        logger.log(
            log_level,
            "[Monitor] %s — status=%s | score=%d | nível=%s",
            tx_id, status, final_score, final_level,
        )

        event: dict = {
            "type": "fraud_alert" if escalated else "status_update",
            "status": status,
            "transaction_id": tx_id,
            "trace_id": trace_id,
            "case_id": result.get("case_id", ""),
            "timestamp": datetime.now().isoformat(),
            "escalated": escalated,
            "final_risk_score": final_score,
            "final_risk_level": final_level,
            "urgency": master.get("urgency", "baixa"),
            "recommended_action": master.get("recommended_action", ""),
            "alert_subject": master.get("alert_subject", ""),
            "alert_message": master.get("alert_message", ""),
            "immediate_actions": master.get("immediate_actions", []),
            "total_criteria_met": result.get("total_criteria_met", 0),
            "simulation_profile": transaction.get("simulation_profile"),
            "pipeline_errors": pipeline_errors,
        }

        await self._emit(event)

    # ── Loop principal ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Inicia o loop de monitoramento. Independente de WebSocket."""
        self.running = True
        self._started_at = datetime.now()
        logger.info("[Monitor] 🚀 Monitor iniciado — processamento contínuo em background.")

        while self.running:
            try:
                transaction = await self._fetch_next_transaction()
                # create_task garante que o processamento é não-bloqueante
                asyncio.create_task(self._process(transaction))
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("[Monitor] Erro no loop: %s", exc)
                await asyncio.sleep(2)

        logger.info("[Monitor] 🛑 Monitor encerrado.")

    def stop(self) -> None:
        """Para o loop de monitoramento."""
        self.running = False

    def stats(self) -> dict:
        """Estatísticas do monitor para health check e WebSocket."""
        uptime = None
        if self._started_at:
            uptime = str(datetime.now() - self._started_at).split(".")[0]
        suspicion_rate = (
            round(self._escalated / self._processed, 4)
            if self._processed > 0 else 0.0
        )
        return {
            # Chaves canônicas usadas pelo frontend e health check
            "running":             self.running,
            "started_at":         self._started_at.isoformat() if self._started_at else None,
            "uptime":             uptime,
            "processed":          self._processed,
            "escalated":          self._escalated,
            "requires_review":    self._requires_review,
            "failed":             self._failed,
            "suspicion_rate":     suspicion_rate,
            # Aliases para compatibilidade com health check existente
            "transactions_processed":     self._processed,
            "escalated_to_investigation": self._escalated,
            "requires_human_review":      self._requires_review,
            "escalation_rate_pct":        round(suspicion_rate * 100, 1),
        }


# Instância singleton compartilhada com a API e o WebSocket
fraud_monitor = FraudMonitor()
