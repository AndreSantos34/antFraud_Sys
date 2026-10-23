"""
Pacote de agentes — AntFraud_Sys
─────────────────────────────────
4 agentes de responsabilidade isolada:
  agent_rule_screener   — Agente 1: Detecção determinística + justificativa LLM
  agent_context_analyst — Agente 2: Investigação histórica + correlação cruzada
  agent_risk_analyzer   — Agente 3: Avaliação de risco (Gravidade/Prioridade/Confiança) + recomendações
  agent_master          — Agente 4: Relatório executivo + orquestração final
"""
from app.agents import (
    agent_rule_screener,
    agent_context_analyst,
    agent_risk_analyzer,
    agent_master,
)

__all__ = [
    "agent_rule_screener",
    "agent_context_analyst",
    "agent_risk_analyzer",
    "agent_master",
]
