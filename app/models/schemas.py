"""
Modelos Pydantic para request/response da API
"""
from typing import Any
from pydantic import BaseModel, Field


class TransactionIn(BaseModel):
    """Transação enviada pelo cliente para análise ad-hoc."""
    transaction_id: str = Field(..., example="TXN-999")
    customer_id: str = Field(..., example="CLI-1001")
    amount: float = Field(..., example=9800.00)
    datetime: str = Field(..., example="2024-06-10T02:37:00")
    location: str = Field(..., example="São Paulo, SP")
    channel: str = Field(..., example="internet_banking")
    device: str = Field(..., example="dispositivo_desconhecido")
    receiver_id: str | None = Field(None, example="CLI-9999")


class CriteriaEvaluation(BaseModel):
    valor_elevado: bool
    horario_incomum: bool
    frequencia_elevada: bool
    valor_repetido: bool
    mudanca_geografica: bool
    dispositivo_desconhecido: bool


class Agent1RiskResult(BaseModel):
    transaction_id: str
    criteria_evaluation: dict[str, bool]
    total_criteria_met: int
    escalate_to_investigation: bool
    classification: str
    confidence: float
    justification: str


class Agent2InvestigationResult(BaseModel):
    transaction_id: str
    sender_profile: dict[str, Any]
    receiver_profile: dict[str, Any]
    crossed_indicators: list[str]
    investigation_summary: str
    data_collection_status: str
    missing_data: list[str]


class Agent3EvidenceResult(BaseModel):
    transaction_id: str
    case_id: str
    suspicion_confirmed: bool
    confirmation_confidence: float
    refutation_arguments: list[str]
    confirmation_arguments: list[str]
    evidence_summary: dict[str, list[str]]
    consolidated_case: dict[str, Any]
    data_quality: str
    information_gaps: list[str]
    recommendation_to_master: str


class CybersecurityAlert(BaseModel):
    subject: str
    priority: str
    timestamp: str
    message: str
    immediate_actions: list[str]
    case_summary: str


class Agent4MasterResult(BaseModel):
    transaction_id: str
    case_id: str
    risk_score: int
    risk_level: str
    urgency: str
    score_breakdown: dict[str, Any]
    recommended_action: str
    cybersecurity_alert: CybersecurityAlert
    disclaimer: str


class AnalysisResponse(BaseModel):
    transaction_id: str
    customer_id: str
    total_criteria_met: int
    escalated: bool
    case_persisted: bool
    agent_1_risk: dict[str, Any]
    agent_2_investigation: dict[str, Any] | None
    agent_3_evidence: dict[str, Any] | None
    agent_4_master: dict[str, Any] | None


class CaseSummary(BaseModel):
    case_id: str
    transaction_id: str | None
    risk_score: int | None
    risk_level: str | None
    urgency: str | None
    recommended_action: str | None
    saved_at: str | None
