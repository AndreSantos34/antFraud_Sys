# Núclea / IBM — Backend de Prevenção de Fraudes Financeiras

Protótipo acadêmico de detecção de fraudes financeiras utilizando uma arquitetura multiagente com **3 agentes de IA baseados em modelos IBM WatsonX**.

---

## Arquitetura do Projeto

```text
antFraud_Sys/
├── main.py                    ← Ponto de entrada FastAPI (Uvicorn)
├── requirements.txt           ← Dependências do projeto
├── .env.example               ← Exemplo de variáveis de ambiente
└── app/
    ├── core/
    │   ├── config.py          ← Configurações e leitura do .env (Pydantic Settings)
    │   └── watsonx_client.py  ← Cliente IAM + Integração com API WatsonX
    ├── agents/
    │   ├── agent_rule_screener.py    ← Agente 1: Triagem Determinística de Regras
    │   ├── agent_context_analyst.py  ← Agente 2: Análise Contextual Profunda
    │   └── agent_report_generator.py ← Agente 3: Gerador de Relatório Final
    ├── models/
    │   └── schemas.py         ← Esquemas Pydantic para requisição e resposta
    ├── routes/
    │   └── fraud.py           ← Endpoints e rotas da API FastAPI
    ├── data/
    │   └── transactions.json  ← Dataset fictício com 20 transações
    └── orchestrator.py        ← Orquestrador do pipeline de execução dos agentes

    Pipeline de Agentes#AgenteModelo WatsonXTemperatureFunção no Pipeline1Rule Screeneribm/granite-13b-instruct-v20.1Agente 1: Triagem Determinística de Regras. Aplica os 6 critérios determinísticos e classifica a transação em normal ou suspeita.2Context Analystibm/granite-20b-multilingual0.4Agente 2: Análise Contextual Profunda. Executa uma análise contextual aprofundada para avaliar o risco de transações suspeitas.3Report Generatoribm/granite-34b-code-instruct0.65Agente 3: Gerador de Relatório Final. Consolida a análise e gera o relatório final formatado para revisão humana.Nota de Fluxo: O Agente 2 e o Agente 3 são acionados apenas quando o Agente 1 classifica a transação como suspeita.Critérios de DetecçãoO Agente 1 valida cada transação com base em 6 regras principais:Valor elevado: Transações com valor acima do padrão (ex: > R$ 5.000,00).Horário incomum: Operações realizadas na janela noturna/madrugada (ex: 22h às 6h).Frequência elevada: Alta repetição de operações (> 3 transações em um intervalo de 10 minutos).Repetição de valores: Padrão repetitivo de montantes semelhantes em curto espaço de tempo.Mudança geográfica incompatível: Localização da transação inconsistente com o histórico do cliente.Dispositivo não reconhecido: Acesso realizado por um dispositivo inédito ou não mapeado.Configuração e Instalação1. Variáveis de AmbienteCrie o arquivo .env a partir do modelo de exemplo:Bashcp .env.example .env
Edite o .env informando suas credenciais da IBM Cloud e WatsonX:Snippet de códigoWATSONX_API_KEY=sua_chave_ibm_cloud
WATSONX_PROJECT_ID=id_do_projeto_watsonx
WATSONX_URL=[https://us-south.ml.cloud.ibm.com](https://us-south.ml.cloud.ibm.com)
2. Pré-requisitos de AmbientePython 3.8 a 3.12 (Recomendado: Python 3.11 ou 3.12).Aviso de Compatibilidade: O Python 3.13+ pode apresentar incompatibilidades com pré-compilações (wheels) do pydantic-core em certos sistemas operacionais (como Windows).Verifique sua versão com: python --version3. Instalação de DependênciasCrie um ambiente virtual (opcional, mas recomendado) e instale os pacotes necessários:Bashpython -m venv .venv
# Ativação no Windows:
.venv\Scripts\activate
# Ativação no Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
4. Execução da APIInicie o servidor de desenvolvimento via Uvicorn:Bashuvicorn main:app --reload
A documentação interativa estará disponível em:Swagger UI: http://localhost:8000/docsReDoc: http://localhost:8000/redocEndpoints da APIMétodoRotaDescriçãoGET/Retorna informações gerais sobre o status da APIGET/api/v1/healthVerificação de integridade (Health Check) e status do WatsonXGET/api/v1/transactionsRetorna a lista completa das 20 transações do datasetGET/api/v1/analyze/{id}Executa o pipeline de análise para uma transação do dataset pelo IDPOST/api/v1/analyzeAnalisa uma transação personalizada enviada no corpo da requisiçãoPOST/api/v1/analyze/batchProcessa em lote todas as 20 transações salvas no datasetExemplo de Uso — Requisição Ad-hoc (POST /api/v1/analyze)Bashcurl -X POST http://localhost:8000/api/v1/analyze \
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
Exemplo de Resposta JSONJSON{
  "transaction_id": "TXN-999",
  "customer_id": "CLI-9999",
  "pipeline_triggered_all_agents": true,
  "agent_1_screening": {
    "classification": "suspeita",
    "triggered_rules": ["valor_elevado", "horario_incomum", "dispositivo_desconhecido"],
    "confidence": 0.92,
    "justification": "Operação realizada fora do horário habitual e em localização divergente."
  },
  "agent_2_context": {
    "risk_level": "critico",
    "recommendation": "bloquear_preventivo",
    "context_summary": "Transação noturna de valor expressivo via dispositivo inédito."
  },
  "agent_3_report": {
    "final_risk_level": "critico",
    "requires_human_review": true,
    "full_report": "...",
    "disclaimer": "Relatório gerado automaticamente por modelo computacional acadêmico."
  }
}
Dataset de TesteO arquivo app/data/transactions.json conta com 20 registros fictícios simulando cenários reais:12 Transações Normais: Operações comuns sem alertas disparados.8 Transações Suspeitas: Operações com um ou múltiplos critérios de alerta ativos.Disclaimer: Todo o conjunto de dados é puramente sintético e acadêmico, não refletindo parâmetros ou dados operacionais reais da Núclea ou de parceiros financeiros.Limitações e Isenção de ResponsabilidadeValidação Humana: A indicação de suspeita não confirma a ocorrência de fraude. Qualquer tomada de decisão administrativa ou financeira deve ser precedida de análise por especialistas humanos.Falsos Positivos e Negativos: Como protótipo conceitual, a acurácia dos modelos IBM WatsonX deve ser calibrada continuamente para ambientes de produção.Projeto Acadêmico — Núclea / IBM
