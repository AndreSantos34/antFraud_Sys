"""
Contratos Pydantic v2 — AntFraud_Sys Backend
─────────────────────────────────────────────
Modelos de entrada/saída de cada agente e dos endpoints REST.
Todos os campos opcionais usam None explícito para distinguir
"ausente" de "vazio" — obrigatório para a regra ZERO ALUCINAÇÃO.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# Enumerações — valores fechados usados por múltiplos agentes
# ══════════════════════════════════════════════════════════════════════════════

class RiskLevel(str, Enum):
    BAIXO    = "baixo"
    MEDIO    = "medio"
    ALTO     = "alto"
    CRITICO  = "critico"


class ProcessingStatus(str, Enum):
    ANALYZING            = "ANALYZING"
    COMPLETED            = "COMPLETED"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    FAILED               = "FAILED"


class UrgencyLevel(str, Enum):
    BAIXA  = "baixa"
    MEDIA  = "media"
    ALTA   = "alta"
    MAXIMA = "maxima"


# ══════════════════════════════════════════════════════════════════════════════
# Entrada — Transação
# ══════════════════════════════════════════════════════════════════════════════

class TransactionIn(BaseModel):
    """Transação enviada pelo cliente para análise ad-hoc ou ingestão."""
    transaction_id: str   = Field(..., examples=["TXN-999"])
    customer_id:    str   = Field(..., examples=["CLI-1001"])
    amount:         float = Field(..., gt=0, examples=[9800.00])
    datetime:       str   = Field(..., examples=["2024-06-10T02:37:00"])
    location:       str   = Field(..., examples=["São Paulo, SP"])
    channel:        str   = Field(..., examples=["internet_banking"])
    device:         str   = Field(..., examples=["dispositivo_desconhecido"])
    receiver_id:    str | None = Field(None, examples=["CLI-9999"])

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount deve ser positivo")
        return round(v, 2)


# ══════════════════════════════════════════════════════════════════════════════
# Agente 1 — Monitor e Detecção
# ══════════════════════════════════════════════════════════════════════════════

class CriteriaFlags(BaseModel):
    """Resultado booleano de cada critério de detecção."""
    valor_elevado:            bool = False
    horario_incomum:          bool = False
    frequencia_elevada:       bool = False
    valor_repetido:           bool = False
    mudanca_geografica:       bool = False
    dispositivo_desconhecido: bool = False


class DetectionResult(BaseModel):
    """Saída do Agente 1."""
    transaction_id:           str
    criteria_flags:           CriteriaFlags
    # Contagem determinística (Python) — NÃO vem do LLM
    total_criteria_met:       int = Field(ge=0, le=6)
    escalate_to_investigation: bool
    # "normal" | "suspeita" — derivado deterministicamente
    classification:           str
    # Evidências brutas coletadas deterministicamente
    deterministic_evidence:   list[str] = Field(default_factory=list)
    # Justificativa contextual gerada pelo LLM (pode ser None se LLM falhou)
    llm_justification:        str | None = None
    llm_confidence:           float | None = Field(None, ge=0.0, le=1.0)


# ══════════════════════════════════════════════════════════════════════════════
# Agente 2 — Investigação e Correlação
# ══════════════════════════════════════════════════════════════════════════════

class SenderProfile(BaseModel):
    customer_id:                str
    typical_amount_range:       str | None = None   # "Dado não disponível" quando ausente
    typical_hours:              str | None = None
    typical_locations:          list[str]  = Field(default_factory=list)
    known_devices:              list[str]  = Field(default_factory=list)
    behavioral_deviation_score: float | None = Field(None, ge=0.0, le=1.0)
    anomalies_found:            list[str]  = Field(default_factory=list)


class ReceiverProfile(BaseModel):
    receiver_id:                str | None = None
    appears_in_other_suspicious: bool = False
    receiver_notes:             str | None = None


class InvestigationResult(BaseModel):
    """Saída do Agente 2."""
    transaction_id:        str
    sender_profile:        SenderProfile
    receiver_profile:      ReceiverProfile
    # Indicadores que se reforçam mutuamente
    crossed_indicators:    list[str] = Field(default_factory=list)
    # Correlações cruzadas com outros eventos no dataset
    correlated_events:     list[str] = Field(default_factory=list)
    investigation_summary: str
    data_collection_status: str   # "completo" | "parcial" | "insuficiente"
    missing_data:          list[str] = Field(default_factory=list)
    llm_generated:         bool = True   # False quando saída é fallback


# ══════════════════════════════════════════════════════════════════════════════
# Agente 3 — Avaliação de Risco e Recomendação
# ══════════════════════════════════════════════════════════════════════════════

class RiskDimensions(BaseModel):
    """
    Três dimensões obrigatórias do risco — cada uma com valor e justificativa.
    Separa impacto potencial, urgência operacional e solidez das evidências.
    """
    # Gravidade: impacto potencial caso seja fraude confirmada
    severity_level:        RiskLevel
    severity_justification: str

    # Prioridade: urgência de atenção humana agora
    priority_level:        UrgencyLevel
    priority_justification: str

    # Confiança: solidez das evidências que sustentam a conclusão
    confidence_score:      float = Field(ge=0.0, le=1.0)
    confidence_justification: str


class RiskRecommendation(BaseModel):
    """Recomendação consultiva — NUNCA executa operações financeiras."""
    action_code:   str          # ex: "solicitar_2fa", "encaminhar_nivel2", "monitorar"
    description:   str          # descrição humana da recomendação
    proportional:  bool = True  # ação proporcional ao risco detectado


class RiskAssessmentResult(BaseModel):
    """Saída do Agente 3."""
    transaction_id:     str
    case_id:            str
    # Score numérico calculado deterministicamente (0-100)
    risk_score:         int = Field(ge=0, le=100)
    risk_dimensions:    RiskDimensions
    # Evidências classificadas por relevância
    critical_evidence:  list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    weak_evidence:      list[str] = Field(default_factory=list)
    refutation_points:  list[str] = Field(default_factory=list)
    # Recomendações consultivas (jamais operacionais)
    recommendations:    list[RiskRecommendation] = Field(default_factory=list)
    information_gaps:   list[str] = Field(default_factory=list)
    # Flag explícita quando score foi calculado via fallback (LLM indisponível)
    score_is_fallback:  bool = False


# ══════════════════════════════════════════════════════════════════════════════
# Agente 4 — Explicabilidade, Relatório e Orquestração
# ══════════════════════════════════════════════════════════════════════════════

class ExecutiveReport(BaseModel):
    """
    Relatório executivo estruturado para o analista SOC.
    Separa explicitamente o que é fato do que é inferência da IA.
    """
    # Fatos observados — apenas dados presentes no payload ou histórico
    observed_facts:    list[str] = Field(default_factory=list)
    # Hipóteses da IA — inferências do LLM, marcadas como tal
    ai_hypotheses:     list[str] = Field(default_factory=list)
    # Limitações — dados ausentes, lacunas de informação
    limitations:       list[str] = Field(default_factory=list)
    # Justificativa do risco — raciocínio de síntese
    risk_justification: str
    # Texto completo para o analista SOC, em PT-BR
    full_narrative:    str


class MasterResult(BaseModel):
    """Saída do Agente 4 — resultado final consolidado do pipeline."""
    transaction_id:   str
    case_id:          str
    trace_id:         str          # UUID rastreável pelo frontend
    processing_status: ProcessingStatus
    # Score final (originado do Agente 3 ou fallback)
    final_risk_score: int = Field(ge=0, le=100)
    final_risk_level: RiskLevel
    urgency:          UrgencyLevel
    recommended_action: str
    # Relatório executivo gerado pelo LLM
    executive_report: ExecutiveReport
    # Alerta pronto para envio ao profissional de cibersegurança
    alert_subject:    str
    alert_message:    str
    immediate_actions: list[str] = Field(default_factory=list)
    # Metadados de rastreabilidade
    pipeline_stages_completed: list[str] = Field(default_factory=list)
    pipeline_errors:  list[str] = Field(default_factory=list)
    completed_at:     str
    disclaimer:       str = (
        "Sistema acadêmico de apoio à triagem. "
        "Decisão final sob responsabilidade humana. "
        "Este sistema NÃO executa operações financeiras."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Fluxo de Aprovação Humana
# ══════════════════════════════════════════════════════════════════════════════

class ActionStatus(str, Enum):
    PENDING  = "PENDING"   # aguardando decisão do analista
    APPROVED = "APPROVED"  # aprovada — execução solicitada ao banco
    REJECTED = "REJECTED"  # rejeitada pelo analista
    EXECUTED = "EXECUTED"  # confirmada pelo executor (simulado ou real)
    FAILED   = "FAILED"    # executor retornou erro


class SuggestedAction(BaseModel):
    """Ação sugerida pelo Agente 4, aguardando aprovação humana."""
    action_id:    str              # ex: "ACT-001"
    action_code:  str              # ex: "bloquear_conta_temporariamente"
    description:  str              # texto exibido ao analista no frontend
    risk_level:   str              # nível de risco que motivou a sugestão
    proportional: bool = True      # ação proporcional ao risco
    status:       ActionStatus = ActionStatus.PENDING


class ActionDecision(BaseModel):
    """Decisão do analista sobre uma ação sugerida."""
    decided_by:   str              # identificador do analista (ex: nome, ID)
    decision:     str              # "approve" | "reject"
    justification: str | None = None  # observação opcional do analista


class ActionResult(BaseModel):
    """Resultado do executor após aprovação de uma ação."""
    action_id:      str
    case_id:        str
    action_code:    str
    description:    str
    status:         ActionStatus
    decided_by:     str
    decided_at:     str
    executed_at:    str | None = None
    execution_note: str | None = None   # resposta simulada ou real do banco
    simulated:      bool = True         # True = executor simulado (protótipo)


# ══════════════════════════════════════════════════════════════════════════════
# Resposta da API — Pipeline completo
# ══════════════════════════════════════════════════════════════════════════════

class AnalysisResponse(BaseModel):
    """Resposta de endpoints que executam o pipeline completo."""
    transaction_id:     str
    customer_id:        str
    case_id:            str
    trace_id:           str
    processing_status:  ProcessingStatus
    total_criteria_met: int
    escalated:          bool
    case_persisted:     bool
    final_risk_score:   int | None
    final_risk_level:   str | None
    # Saídas brutas de cada agente (None se não executou)
    agent_1_detection:    dict[str, Any]
    agent_2_investigation: dict[str, Any] | None
    agent_3_risk:         dict[str, Any] | None
    agent_4_master:       dict[str, Any] | None


class IngestResponse(BaseModel):
    """Resposta imediata do endpoint de ingestão (fire-and-forget)."""
    accepted:       bool
    transaction_id: str
    trace_id:       str
    message:        str


class CaseSummary(BaseModel):
    """Resumo de um caso persistido para listagem."""
    case_id:            str
    transaction_id:     str | None
    trace_id:           str | None
    processing_status:  str | None
    final_risk_score:   int | None
    final_risk_level:   str | None
    urgency:            str | None
    recommended_action: str | None
    saved_at:           str | None
