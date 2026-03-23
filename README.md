# Webhook com Django + Celery + Redis — Exemplo Instrucional

Projeto didático que demonstra como webhooks funcionam na prática,
replicando o modelo usado por **Stripe**, **GitHub** e outros serviços do mercado.

**Esta branch (`redis`)** usa **Celery + Redis** para processamento assíncrono,
orquestrado com **Docker Compose**.

---

## O que vai aprender aqui

- O que é um webhook e quando usar
- Autenticação por API Key (consumer → servidor) e HMAC-SHA256 (servidor → callback)
- Processamento assíncrono com Celery + Redis (fila de tarefas)
- Docker Compose orquestrando 4 containers
- Como um consumer se cadastra via API, recebe credenciais e consome serviços
- Cada serviço tem sua própria rota e seu próprio callback

---

## Arquitetura

4 containers Docker que conversam entre si:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Docker Compose                                     │
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌────────────────────────┐  │
│  │   REDIS :6379   │    │   DJANGO :8000  │    │   CELERY WORKER       │  │
│  │   (broker)      │◄───┤   (API)         │    │   (processa tasks)    │  │
│  │                 │    │                 │    │                       │  │
│  │  Fila de tasks  │───►│  Enfileira task ├───►│  Pega da fila         │  │
│  │                 │    │  Responde 202   │    │  Executa o serviço    │  │
│  └─────────────────┘    └─────────────────┘    │  Envia callback ──┐  │  │
│                                                 └──────────────────┼──┘  │
│                                                                    │     │
│  ┌──────────────────────────────────────┐                          │     │
│  │   EMITTER :9000                      │◄─────────────────────────┘     │
│  │   (consumer simulado)                │  POST /primos/ (com HMAC)      │
│  │                                      │  POST /pokemon/                │
│  │   Menu interativo + callback server  │  POST /traduzir/               │
│  └──────────────────────────────────────┘  POST /converter-pdf/          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Fluxo com Celery:**

```text
Consumer → POST /webhook/primos/ → Django valida → responde 202
                                        ↓
                                   Enfileira task no Redis
                                        ↓
                                   Celery Worker pega da fila
                                        ↓
                                   Processa (gera primos)
                                        ↓
                                   Envia callback com HMAC → Consumer
```

**Comparação com a branch `main`:**

| Aspecto | `main` (threads) | `redis` (Celery) |
|---|---|---|
| Processamento | `threading.Thread` | Celery task via Redis |
| Infra | Apenas Django | Docker Compose (4 containers) |
| Persistência da fila | Perde se o servidor cair | Redis persiste |
| Retry | Não tem | Celery suporta retry nativo |
| Monitoramento | Logs apenas | Celery Flower (extensível) |
| Escalabilidade | Limitado a 1 processo | Múltiplos workers |

---

## Modelo de autenticação (padrão de mercado)

```text
IDA (consumer → servidor):
  Header: X-Api-Key: <api_key>
  Autenticação simples — funciona no Swagger, Postman, curl

VOLTA (servidor → callback):
  Header: X-Hub-Signature-256: sha256=<hmac_do_body>
  O servidor assina com o secret_key do consumer
  O consumer valida para garantir que veio do servidor legítimo
```

---

## Rotas da API

### Rotas públicas (sem autenticação)

| Rota | Método | Descrição |
|---|---|---|
| `/webhook/events/` | GET | Lista eventos disponíveis com payloads de exemplo |
| `/webhook/register/` | POST | Cadastro de consumer (retorna api_key + secret_key) |

### Rotas de serviço (autenticadas por API Key)

| Rota | Método | Serviço | Payload |
|---|---|---|---|
| `/webhook/primos/` | POST | Gerador de primos | `{"quantidade": 10}` |
| `/webhook/pokemon/` | POST | Consulta PokéAPI | `{"pokemon": "pikachu"}` |
| `/webhook/traduzir/` | POST | Fun Translations | `{"texto": "...", "idioma": "yoda"}` |
| `/webhook/converter-pdf/` | POST | PDF → Markdown (Docling) | Upload de arquivo (multipart/form-data) |

### Rotas de documentação

| Rota | Método | Descrição |
|---|---|---|
| `/api/docs/` | GET | Swagger UI (interativo) |
| `/api/redoc/` | GET | ReDoc (leitura) |
| `/api/schema/` | GET | OpenAPI Schema (YAML) |
| `/admin/` | GET | Django Admin |

### Rotas do Emitter (callback na porta 9000)

| Rota | Método | Recebe callback de |
|---|---|---|
| `/primos/` | POST | gerar_primos |
| `/pokemon/` | POST | pokemon |
| `/traduzir/` | POST | traduzir |
| `/converter-pdf/` | POST | converter_pdf |

---

## Fluxo completo de uma requisição

```text
1. Consumer envia POST /webhook/pokemon/
   Header: X-Api-Key: <api_key>
   Body: {"pokemon": "pikachu"}

2. Django (container web):
   a) Busca consumer pela api_key ──── "quem é?"
   b) Verifica inscrição no evento ─── "tem permissão pra pokemon?"
   c) Responde 202 Accepted ────────── "ok, recebi"
   d) Enfileira task no Redis ─────── task.delay()

3. Celery Worker (container worker):
   a) Pega a task da fila do Redis
   b) Consulta a PokéAPI
   c) Atualiza o status no banco (processando → concluído)
   d) Envia callback assinado com HMAC

4. Callback chega no Emitter (container emitter):
   URL: http://emitter:9000/pokemon/
   Header: X-Hub-Signature-256: sha256=<HMAC>
   Body: {"evento": "pokemon", "status": "concluido", "resultado": {...}}

5. Emitter valida HMAC e exibe o resultado
```

---

## Estrutura do Projeto

```text
webhook/
├── manage.py                    # CLI do Django
├── emitter.py                   # Consumer simulado (callback server + menu)
├── Dockerfile                   # Imagem Python 3.11 + dependências
├── docker-compose.yml           # 4 containers: redis, web, worker, emitter
├── requirements.txt             # Dependências (local/macOS)
├── requirements.docker.txt      # Dependências (Docker/Linux, sem pyobjc)
├── postman_collection.json      # Collection para Postman
├── .dockerignore
├── .gitignore
├── README.md
│
├── core/                        # Projeto Django
│   ├── __init__.py              # Importa celery_app
│   ├── celery.py                # Configuração do Celery
│   ├── settings.py              # Apps, Swagger, banco, Redis broker
│   └── urls.py                  # Rotas: /admin/, /webhook/, /api/docs/
│
└── webhook/                     # App do webhook
    ├── models.py                # Consumer, Inscricao, WebhookLog
    ├── views.py                 # Auth + rotas + registro (enfileira tasks)
    ├── tasks.py                 # 4 serviços como Celery tasks + callback
    ├── urls.py                  # 6 rotas (4 serviços + register + events)
    └── admin.py                 # Gerencia consumers, inscrições e logs
```

---

## Instalação e execução com Docker

```bash
# 1. Clone o repositório
git clone https://github.com/LGPDNOW/webhook_partner.git
cd webhook_partner
git checkout redis

# 2. Suba tudo com Docker Compose
docker compose up --build
```

Isso cria e sobe 4 containers:

| Container | Porta | Descrição |
|---|---|---|
| `redis` | 6379 | Broker do Celery (fila de tasks) |
| `web` | 8000 | Django API + Admin + Swagger |
| `worker` | — | Celery Worker (processa os 4 serviços) |
| `emitter` | 9000 | Consumer simulado (menu + callback server) |

O container `web` roda as migrações e cria o superusuário automaticamente:

**Admin:** `http://localhost:8000/admin/` — `admin` / `admin123`

### Comandos úteis

```bash
# Ver logs de todos os containers
docker compose logs -f

# Ver logs só do worker (Celery)
docker compose logs -f worker

# Ver logs só do emitter
docker compose logs -f emitter

# Parar tudo
docker compose down

# Rebuild após mudanças
docker compose up --build
```

---

## Instalação sem Docker (local)

```bash
# 1. Instale e suba o Redis localmente
brew install redis && redis-server &

# 2. Crie e ative o ambiente virtual
python3 -m venv venv && source venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Migrate e crie o superusuário
python manage.py migrate
python manage.py createsuperuser

# Terminal 1 — Django
python manage.py runserver

# Terminal 2 — Celery Worker
celery -A core worker --loglevel=info

# Terminal 3 — Emitter
python emitter.py
```

---

## Passo a passo para testar

### Passo 1 — Suba os containers

```bash
docker compose up --build
```

### Passo 2 — Interaja com o emitter

```bash
docker compose exec -it emitter python emitter.py
```

Ou use o Swagger em `http://localhost:8000/api/docs/`.

### Passo 3 — Cadastrar via Swagger ou emitter

No Swagger, execute `POST /webhook/register/`:

```json
{
    "nome": "Minha App",
    "email": "dev@empresa.com",
    "inscricoes": [
        {"evento": "gerar_primos", "callback_url": "http://emitter:9000/primos/"},
        {"evento": "pokemon", "callback_url": "http://emitter:9000/pokemon/"}
    ]
}
```

Copie a `api_key` da resposta.

### Passo 4 — Chamar um serviço

No Swagger, execute `POST /webhook/primos/` com header `X-Api-Key`:

```json
{"quantidade": 10}
```

Resposta imediata: `202 Accepted`

### Passo 5 — Acompanhar o processamento

**Logs do Django (web):**

```text
📥 [GERAR_PRIMOS] Nova requisição recebida
🔑 Autenticando — api_key=9f77f53d…
✅ Autenticado: Minha App
📥 [GERAR_PRIMOS] Task enfileirada no Celery!
```

**Logs do Celery (worker):**

```text
Task webhook.gerar_primos received
⚙️  [CELERY WORKER] Task iniciada: evento='gerar_primos'
🔢 [PRIMOS] Iniciando geração de 10 primos…
🔢 [PRIMOS] Concluído! 10 primos gerados. Último: 29
📤 [CALLBACK] Enviando para http://emitter:9000/primos/…
📤 [CALLBACK] Entregue com sucesso! HTTP 200
Task webhook.gerar_primos succeeded in 5.2s
```

**Logs do Emitter:**

```text
📥 CALLBACK RECEBIDO em /primos/
📌 Evento: gerar_primos
🔒 Assinatura HMAC válida — resposta autêntica do servidor
🔢 Total: 10 primos
🔢 Primos: [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]
```

### Passo 6 — Verificar no Admin

Acesse `http://localhost:8000/admin/` → **Logs de Webhook**:
- Status: recebido → processando → concluído → callback_enviado
- Payload e resultado completos

---

## Testando com Swagger

Acesse `http://localhost:8000/api/docs/` com os containers rodando.

1. Execute `POST /webhook/register/` para se cadastrar
2. Copie a `api_key` da resposta
3. Nas rotas de serviço, passe a `api_key` no header `X-Api-Key`

Para ver os callbacks, acompanhe os logs do emitter: `docker compose logs -f emitter`

---

## Testando com Postman

1. Importe `postman_collection.json`
2. Execute **"Cadastrar consumer"** primeiro — credenciais preenchidas automaticamente
3. Todas as requisições seguintes já usam a `api_key`

| Pasta | Requisição | Resultado |
|---|---|---|
| Rotas Públicas | Listar eventos | 200 |
| Rotas Públicas | Cadastrar consumer | 201 |
| Serviços | Gerar 10 Primos | 202 |
| Serviços | Consultar Pokémon | 202 |
| Serviços | Traduzir para Yoda | 202 |
| Serviços | Converter PDF | 202 |
| Testes de erro | API Key inválida | 401 |
| Testes de erro | Consumer não inscrito | 403 |
| Testes de erro | Email duplicado | 409 |

---

## Segurança — HMAC no callback

O HMAC é usado apenas no **callback** (servidor → consumer):

```text
Celery Worker termina o processamento e envia:

  POST http://emitter:9000/pokemon/
  Header: X-Hub-Signature-256: sha256=a1b2c3d4...
  Body: {"evento": "pokemon", "status": "concluido", "resultado": {...}}

O consumer (emitter) valida:

  1. Tem o secret_key (recebeu no cadastro)
  2. Recalcula: HMAC-SHA256(secret_key, body) → "a1b2c3d4..."
  3. Compara com compare_digest (tempo constante)
  4. Iguais? → Autêntico ✓
     Diferentes? → ⚠️ Pode ser forjado

O secret_key NUNCA trafega na rede — só o hash resultante.
```

---

## Tecnologias

| Componente | Tecnologia |
|---|---|
| Servidor | Django 5.x |
| API REST | Django REST Framework |
| API docs | drf-spectacular (Swagger/ReDoc) |
| Task Queue | Celery 5.x |
| Broker | Redis 7 |
| Processamento PDF | Docling |
| Containers | Docker Compose |
| Banco | SQLite (gerado automaticamente) |
| Emitter | http.server (stdlib Python) |
