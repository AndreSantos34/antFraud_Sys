# Núclea / IBM — Backend de Prevenção de Fraudes Financeiras

Protótipo acadêmico de detecção de fraudes financeiras com **4 agentes de IA IBM WatsonX**
e persistência dual (MySQL + arquivos JSON locais).

---

## Arquitetura

```
main.py
└── app/
    ├── core/
    │   ├── config.py            ← Settings (Pydantic, lê .env) — inclui DATABASE_URL
    │   ├── security.py          ← Autenticação via X-API-Key
    │   └── watsonx_client.py    ← Cliente IAM + API de geração de texto
    ├── db/                      ← Camada MySQL (nova)
    │   ├── database.py          ← Engine SQLAlchemy + get_session()
    │   ├── models.py            ← ORM: tabelas transactions e cases
    │   └── crud.py              ← save_transaction, save_case, load_case, list_cases
    ├── agents/
    │   ├── agent_rule_screener.py     ← Agente 1: Triagem de Regras
    │   ├── agent_context_analyst.py   ← Agente 2: Análise Contextual
    │   ├── agent_report_generator.py  ← Agente 3: Base de Dados e Evidências
    │   └── agent_master.py            ← Agente 4: IA Mestre
    ├── models/
    │   └── schemas.py           ← Modelos Pydantic (request/response)
    ├── routes/
    │   ├── fraud.py             ← Endpoints FastAPI
    │   └── websocket.py         ← WebSocket — alertas em tempo real
    ├── data/
    │   ├── transactions.json    ← Dataset: 20 transações fictícias
    │   └── cases/               ← Dossiês JSON (fallback — gerados em execução)
    ├── case_storage.py          ← Dual-write: MySQL primário + JSON fallback
    ├── orchestrator.py          ← Pipeline de coordenação dos 4 agentes
    ├── monitor.py               ← Monitor background de transações
    └── simulator.py             ← Gerador de transações fictícias
```

## Pipeline de Agentes

| # | Agente | Modelo WatsonX | Temperature | Papel |
|---|--------|----------------|-------------|-------|
| 1 | Rule Screener | `ibm/granite-13b-instruct-v2` | 0.1 | Aplica os 6 critérios determinísticos |
| 2 | Context Analyst | `ibm/granite-20b-multilingual` | 0.4 | Investigação profunda de ameaças |
| 3 | Report Generator | `ibm/granite-34b-code-instruct` | 0.35 | Base de dados e evidências |
| 4 | IA Mestre | `ibm/granite-34b-code-instruct` | 0.55 | Score de risco + alerta cybersecurity |

Os Agentes 2, 3 e 4 são acionados apenas quando o Agente 1 detecta **≥ 3 critérios**.

## Critérios de Detecção

1. Valor elevado (padrão: > R$ 5.000)
2. Horário incomum (padrão: 22h–6h)
3. Frequência elevada (> 3 transações em 10 minutos)
4. Repetição de valores semelhantes
5. Mudança geográfica incompatível
6. Dispositivo não reconhecido

---

## Pré-requisitos

- **Python 3.10–3.12** (recomendado; pydantic-core requer ≤ 3.12 no Windows)
- **MySQL Server 8.x** instalado e em execução (MySQL Workbench opcional)
- **Credenciais IBM Cloud** para o WatsonX

---

## Configuração

### 1. Clonar e criar ambiente virtual (Windows — PowerShell)

```powershell
cd antFraud_Sys
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Instalar dependências

```powershell
pip install -r requirements.txt
```

Dependências adicionadas para MySQL:

| Pacote | Versão mínima | Finalidade |
|--------|--------------|------------|
| `sqlalchemy` | 2.0.30 | ORM + gerenciamento de conexões |
| `pymysql` | 1.1.0 | Driver MySQL puro-Python (sem build tools) |
| `cryptography` | 42.0.0 | Autenticação `caching_sha2_password` (MySQL 8.x) |

### 3. Configurar variáveis de ambiente

```powershell
copy .env.example .env
```

Edite `.env` com suas credenciais reais:

```env
# IBM WatsonX
WATSONX_API_KEY=sua_chave_ibm_cloud
WATSONX_PROJECT_ID=id_do_projeto_watsonx
WATSONX_URL=https://us-south.ml.cloud.ibm.com

# MySQL — substitua USUARIO e SENHA pelos valores reais
DATABASE_URL=mysql+pymysql://antfraud_user:SENHA@localhost:3306/antfraud_db

# Deixe DATABASE_URL em branco para usar apenas arquivos JSON locais (sem MySQL):
# DATABASE_URL=
```

> **Segurança:** o arquivo `.env` está no `.gitignore` e **nunca** deve ser versionado.

### 4. Preparar o banco `antfraud_db` no MySQL Workbench

Abra o MySQL Workbench e execute:

```sql
-- 1. Cria o banco de dados (uma única vez)
CREATE DATABASE IF NOT EXISTS antfraud_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 2. Cria um usuário de aplicação com permissões limitadas
--    (substitua 'SENHA_FORTE' por uma senha real)
CREATE USER IF NOT EXISTS 'antfraud_user'@'localhost'
  IDENTIFIED BY 'SENHA_FORTE';

-- 3. Concede apenas os privilégios necessários (nunca SUPER/GRANT OPTION)
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, DROP, REFERENCES
  ON antfraud_db.*
  TO 'antfraud_user'@'localhost';

FLUSH PRIVILEGES;
```

> **Nota:** a criação do banco é manual (etapa administrativa).
> As **tabelas** são criadas automaticamente pela aplicação na inicialização.

### 5. Inicializar as tabelas

As tabelas `transactions` e `cases` são criadas automaticamente quando a
aplicação sobe, via `init_db()` no lifespan do FastAPI.

Você também pode inicializá-las manualmente:

```powershell
python -c "from app.db.models import init_db; init_db(); print('Tabelas criadas.')"
```

---

## Execução

```powershell
uvicorn main:app --reload
```

Acesse: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/` | Informações da API |
| `GET` | `/api/v1/health` | Health check + status WatsonX + monitor |
| `GET` | `/api/v1/transactions` | Lista as 20 transações do dataset |
| `GET` | `/api/v1/analyze/{id}` | Analisa uma transação do dataset pelo ID |
| `POST` | `/api/v1/analyze` | Analisa uma transação ad-hoc (JSON no body) |
| `POST` | `/api/v1/analyze/batch` | Processa todas as 20 transações |
| `GET` | `/api/v1/cases` | Lista casos suspeitos persistidos |
| `GET` | `/api/v1/cases/{case_id}` | Recupera dossiê completo de um caso |
| `POST` | `/api/v1/monitor/start` | Inicia o monitor background |
| `POST` | `/api/v1/monitor/stop` | Para o monitor background |
| `GET` | `/api/v1/monitor/stats` | Estatísticas do monitor |
| `POST` | `/api/v1/simulate/transaction` | Gera e analisa uma transação simulada |
| `WS` | `/ws/alerts?api_key=...` | WebSocket — alertas em tempo real |

Todos os endpoints `/api/v1/` requerem o header `X-API-Key`.

### Exemplo de chamada ad-hoc

```powershell
curl -X POST http://localhost:8000/api/v1/analyze `
  -H "Content-Type: application/json" `
  -H "X-API-Key: nuclea-dev-key-change-in-production" `
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

---

## Execução dos Testes

```powershell
# Instalar dependências de teste (necessário apenas uma vez)
pip install pytest httpx

# Executar todos os testes
pytest tests/test_mysql.py -v

# Executar apenas os testes que não precisam de MySQL (10 e 11)
pytest tests/test_mysql.py -v -k "test_10 or test_11"
```

Os testes 1–9 são automaticamente ignorados (`skip`) quando o MySQL não está
disponível. O teste 10 e o teste 11 funcionam sem banco de dados.

---

## Estratégia de Persistência (Dual-Write)

```
Transação analisada
       │
       ▼
  case_storage.save_case()
       │
  ┌────┴─────────────────────────────────────────┐
  │ MySQL (primário)          │ JSON (fallback)  │
  │ antfraud_db.cases         │ app/data/cases/  │
  │ antfraud_db.transactions  │ <case_id>.json   │
  └───────────────────────────┴──────────────────┘
```

- Se `DATABASE_URL` estiver configurada e o MySQL acessível → **grava em ambos**.
- Se MySQL indisponível → **grava apenas em JSON** (aplicação continua funcionando).
- Na leitura: **MySQL tem prioridade**; fallback automático para JSON.

---

## Esquema do Banco de Dados

### Tabela `transactions`

| Coluna | Tipo MySQL | Notas |
|--------|-----------|-------|
| `id` | `BIGINT AUTO_INCREMENT` | PK |
| `transaction_id` | `VARCHAR(255) UNIQUE` | Índice único |
| `customer_id` | `VARCHAR(255)` | Indexado |
| `receiver_id` | `VARCHAR(255)` | Nullable |
| `amount` | `DECIMAL(18,2)` | Precisão monetária |
| `transaction_datetime` | `DATETIME` | UTC recomendado |
| `location` | `VARCHAR(255)` | Nullable |
| `channel` | `VARCHAR(100)` | Nullable |
| `device` | `VARCHAR(255)` | Nullable |
| `label` | `VARCHAR(100)` | `normal` / `suspeita` |
| `reason` | `TEXT` | Justificativa do Agente 1 |
| `created_at` | `DATETIME` | Preenchido automaticamente |

### Tabela `cases`

| Coluna | Tipo MySQL | Notas |
|--------|-----------|-------|
| `id` | `BIGINT AUTO_INCREMENT` | PK |
| `case_id` | `VARCHAR(255) UNIQUE` | Índice único |
| `transaction_id` | `VARCHAR(255)` | FK → transactions.transaction_id ON DELETE SET NULL |
| `risk_score` | `SMALLINT` | 0–100 (CHECK no MySQL ≥ 8.0.16) |
| `risk_level` | `VARCHAR(50)` | ex: `crítico`, `alto` |
| `urgency` | `VARCHAR(50)` | ex: `imediata` |
| `status` | `VARCHAR(50)` | Padrão: `open` |
| `reason` | `TEXT` | Nullable |
| `recommended_action` | `TEXT` | Nullable |
| `agent_results` | `JSON` | Saídas dos Agentes 1–3 |
| `final_result` | `JSON` | Saída do Agente 4 (IA Mestre) |
| `created_at` | `DATETIME` | Preenchido automaticamente |
| `updated_at` | `DATETIME` | Atualizado automaticamente |

---

## Solução de Problemas Comuns

### `Access denied for user`

```sql
-- No MySQL Workbench, verifique as permissões:
SHOW GRANTS FOR 'antfraud_user'@'localhost';

-- Se necessário, reconceda:
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, DROP, REFERENCES
  ON antfraud_db.* TO 'antfraud_user'@'localhost';
FLUSH PRIVILEGES;
```

### `Can't connect to MySQL server on localhost`

Verifique se o serviço MySQL está rodando:

```powershell
# Windows
Get-Service -Name "MySQL*"
Start-Service -Name "MySQL80"  # ajuste o nome conforme a versão instalada
```

### `Unknown database 'antfraud_db'`

O banco precisa ser criado manualmente (ver **Passo 4** acima):

```sql
CREATE DATABASE IF NOT EXISTS antfraud_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### `Authentication plugin 'caching_sha2_password' cannot be loaded`

Garanta que `cryptography` está instalado:

```powershell
pip install cryptography>=42.0.0
```

### Aplicação sobe sem MySQL configurado

Comportamento esperado. Sem `DATABASE_URL` no `.env`, a aplicação usa apenas
arquivos JSON em `app/data/cases/`. Configure o `.env` e reinicie para ativar o MySQL.

### Erro de permissão no PowerShell ao ativar venv

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
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
- O campo `CHECK` em `risk_score` (0–100) é aplicado pelo MySQL ≥ 8.0.16.
  Em versões anteriores, a validação ocorre na camada Pydantic.

---

*Projeto acadêmico — Núclea / IBM*
