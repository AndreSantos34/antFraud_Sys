# Núclea / IBM — Backend de Prevenção de Fraudes Financeiras

Protótipo acadêmico de detecção de fraudes financeiras com **3 agentes de IA IBM WatsonX**.

---

## Arquitetura

```
main.py
└── app/
    ├── core/
    │   ├── config.py            ← Settings (Pydantic, lê .env)
    │   └── watsonx_client.py    ← Cliente IAM + API de geração de texto
    ├── agents/
    │   ├── agent_rule_screener.py     ← Agente 1: Triagem de Regras
    │   ├── agent_context_analyst.py   ← Agente 2: Análise Contextual
    │   └── agent_report_generator.py  ← Agente 3: Gerador de Relatório
    ├── models/
    │   └── schemas.py           ← Modelos Pydantic (request/response)
    ├── routes/
    │   └── fraud.py             ← Endpoints FastAPI
    ├── data/
    │   └── transactions.json    ← Dataset: 20 transações fictícias
    └── orchestrator.py          ← Pipeline de coordenação dos agentes
```

## Pipeline de Agentes

| # | Agente | Modelo WatsonX | Temperature | Papel |
|---|--------|----------------|-------------|-------|
| 1 | Rule Screener | `ibm/granite-13b-instruct-v2` | 0.1 | Aplica os 6 critérios determinísticos e classifica: `normal` / `suspeita` |
| 2 | Context Analyst | `ibm/granite-20b-multilingual` | 0.4 | Análise contextual profunda só para transações suspeitas |
| 3 | Report Generator | `ibm/granite-34b-code-instruct` | 0.65 | Gera relatório final consolidado para revisão humana |

O Agente 2 e o Agente 3 só são acionados quando o Agente 1 classifica como `suspeita`.

## Critérios de Detecção

1. Valor elevado (padrão: > R$ 5.000)
2. Horário incomum (padrão: 22h–6h)
3. Frequência elevada (> 3 transações em 10 minutos)
4. Repetição de valores semelhantes
5. Mudança geográfica incompatível
6. Dispositivo não reconhecido

## Configuração

### 1. Variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` com suas credenciais IBM Cloud:

```env
WATSONX_API_KEY=sua_chave_ibm_cloud
WATSONX_PROJECT_ID=id_do_projeto_watsonx
WATSONX_URL=https://us-south.ml.cloud.ibm.com
```

### 2. Pré-requisito: Python

> **Importante:** FastAPI e pydantic-core requerem **Python 3.8–3.12**.
> Python 3.13+ ainda não possui wheels pré-compilados para pydantic-core no Windows.
> Recomenda-se usar Python 3.11 ou 3.12.
>
> Verifique com: `python --version`

### 3. Instalação

```bash
pip install -r requirements.txt
```

### 4. Execução

```bash
uvicorn main:app --reload
```

Acesse a documentação interativa em: http://localhost:8000/docs

---

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Informações da API |
| `GET` | `/api/v1/health` | Health check + status WatsonX |
| `GET` | `/api/v1/transactions` | Lista as 20 transações do dataset |
| `GET` | `/api/v1/analyze/{id}` | Analisa uma transação do dataset pelo ID |
| `POST` | `/api/v1/analyze` | Analisa uma transação ad-hoc (JSON no body) |
| `POST` | `/api/v1/analyze/batch` | Processa todas as 20 transações |

### Exemplo de chamada ad-hoc

```bash
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "TXN-999",
    "customer_id": "CLI-9999",
    "amount": 9800.00,
    "datetime": "2024-06-10T02:37:00",
    "location": "Miami, EUA",
    "channel": "internet_banking",
    "device": "dispositivo_desconhecido"
  }'
```

### Exemplo de resposta

```json
{
  "transaction_id": "TXN-999",
  "customer_id": "CLI-9999",
  "pipeline_triggered_all_agents": true,
  "agent_1_screening": {
    "classification": "suspeita",
    "triggered_rules": ["valor_elevado", "horario_incomum", "dispositivo_desconhecido"],
    "confidence": 0.92,
    "justification": "..."
  },
  "agent_2_context": {
    "risk_level": "critico",
    "recommendation": "bloquear_preventivo",
    ...
  },
  "agent_3_report": {
    "final_risk_level": "critico",
    "requires_human_review": true,
    "full_report": "...",
    "disclaimer": "..."
  }
}
```

---

## Dataset

O arquivo [`app/data/transactions.json`](app/data/transactions.json) contém 20 transações fictícias:
- **12 normais** — operações cotidianas sem indicadores relevantes
- **8 suspeitas** — com um ou mais dos 6 critérios disparados

> Os dados são exclusivamente acadêmicos e não representam parâmetros reais da Núclea ou de instituições financeiras.

## Limitações

- Suspeita ≠ confirmação de fraude.
- O protótipo deve ser avaliado considerando falsos positivos e falsos negativos.
- Qualquer decisão relevante requer validação humana adequada.

---

*Projeto acadêmico — Núclea / IBM*
