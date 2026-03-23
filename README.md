# Webhook com Django — Exemplo Instrucional

Projeto didático que demonstra como webhooks funcionam na prática,
replicando o modelo usado por **Stripe**, **GitHub** e outros serviços do mercado.

---

## O que vai aprender aqui

- O que é um webhook e quando usar
- Autenticação por API Key (consumer → servidor) e HMAC-SHA256 (servidor → callback)
- Fluxo assíncrono: aceita o pedido, processa em background, notifica via callback
- Como um consumer se cadastra via API, recebe credenciais e consome serviços
- Cada serviço tem sua própria rota e seu próprio callback

---

## Arquitetura

O projeto tem **dois processos** que conversam entre si:

```text
┌───────────────────────────────────┐       ┌───────────────────────────────────┐
│       EMITTER (porta 9000)        │       │        DJANGO (porta 8000)        │
│       Simula o consumer           │       │        Servidor do webhook        │
│                                   │       │                                   │
│  ┌─────────────────────────────┐  │       │  Rotas públicas:                  │
│  │ Menu interativo             │  │       │    GET  /webhook/events/           │
│  │ (cadastro + escolhe serviço)│──┼──────►│    POST /webhook/register/         │
│  └─────────────────────────────┘  │       │                                   │
│                                   │       │  Rotas autenticadas (API Key):     │
│  Callbacks por serviço:           │       │    POST /webhook/primos/           │
│    POST /primos/       ◄──────────┼───────┤    POST /webhook/pokemon/          │
│    POST /pokemon/      ◄──────────┼───────┤    POST /webhook/traduzir/         │
│    POST /traduzir/     ◄──────────┼───────┤    POST /webhook/converter-pdf/    │
│    POST /converter-pdf/◄──────────┼───────┤                                   │
│                                   │       │  Callback assinado com HMAC ────►  │
│  Valida HMAC do callback          │       │                                   │
│  Exibe o resultado na tela        │       │  Swagger: /api/docs/              │
└───────────────────────────────────┘       └───────────────────────────────────┘
```

**Isso é exatamente como funciona no mercado:**

| Analogia | Neste projeto | No Stripe |
|---|---|---|
| Você (consumer) | `emitter.py` | Sua aplicação |
| Se cadastrar | `POST /webhook/register/` | Dashboard do Stripe |
| Receber credenciais | `api_key` + `secret_key` | API Key + Webhook Secret |
| Informar callback por evento | `callback_url` por inscrição | Endpoint URL no dashboard |
| Chamar um serviço | `POST /webhook/primos/` | `POST /v1/charges` |
| Receber aviso | `POST /primos/` (callback) | Stripe chama seu endpoint |
| Autenticação na ida | API Key (header) | Bearer Token |
| Autenticação no callback | HMAC-SHA256 | Stripe-Signature |

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

O `secret_key` **nunca trafega na rede** — só é usado para calcular e validar o HMAC.

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

2. Django:
   a) Busca consumer pela api_key ──── "quem é?"
   b) Verifica inscrição no evento ─── "tem permissão pra pokemon?"
   c) Responde 202 Accepted ────────── "ok, recebi"
   d) Dispara thread em background

3. Thread consulta a PokéAPI (pode demorar)

4. Quando termina, Django envia POST no callback do consumer:
   URL: http://localhost:9000/pokemon/  (cadastrado na inscrição)
   Header: X-Hub-Signature-256: sha256=<HMAC assinado com secret_key>
   Body: {"evento": "pokemon", "status": "concluido", "resultado": {...}}

5. Consumer (emitter) recebe o callback:
   a) Valida HMAC ─── "veio mesmo do servidor?"
   b) Exibe o resultado na tela
```

---

## Cadastro de consumer

O cadastro é feito via API. Cada inscrição tem **seu próprio callback_url**:

```json
POST /webhook/register/

{
    "nome": "Minha Aplicação",
    "email": "dev@empresa.com",
    "inscricoes": [
        {"evento": "gerar_primos", "callback_url": "http://meu-server:9000/primos/"},
        {"evento": "pokemon",      "callback_url": "http://meu-server:9000/pokemon/"},
        {"evento": "traduzir",     "callback_url": "http://meu-server:9000/traduzir/"}
    ]
}
```

Resposta:

```json
{
    "status": "cadastrado",
    "consumer": {
        "nome": "Minha Aplicação",
        "email": "dev@empresa.com",
        "api_key": "9f83137e02352894669d79f6f85af6d9",
        "secret_key": "eccda6da04eb207fe0b4259296c521a2...",
        "inscricoes": [
            {"evento": "gerar_primos", "callback_url": "...", "rota": "/webhook/primos/"},
            {"evento": "pokemon",      "callback_url": "...", "rota": "/webhook/pokemon/"},
            {"evento": "traduzir",     "callback_url": "...", "rota": "/webhook/traduzir/"}
        ]
    },
    "aviso": "GUARDE a secret_key — ela não será exibida novamente!"
}
```

---

## Estrutura do Projeto

```text
webhook/
├── manage.py                    # CLI do Django
├── emitter.py                   # Consumer simulado (callback server + menu)
├── requirements.txt             # Dependências
├── postman_collection.json      # Collection para Postman
├── .gitignore
├── README.md
│
├── core/                        # Projeto Django
│   ├── settings.py              # Apps, Swagger, banco, limite upload
│   └── urls.py                  # Rotas: /admin/, /webhook/, /api/docs/
│
└── webhook/                     # App do webhook
    ├── models.py                # Consumer, Inscricao, WebhookLog
    ├── views.py                 # Auth + 4 serviços + registro + callback
    ├── urls.py                  # 6 rotas (4 serviços + register + events)
    └── admin.py                 # Gerencia consumers, inscrições e logs
```

---

## Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/LGPDNOW/webhook_partner.git
cd webhook_partner

# 2. Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Crie o banco e aplique as migrações
python manage.py migrate

# 5. Crie o superusuário para o Django Admin
python manage.py createsuperuser
```

---

## Passo a passo para testar

### Passo 1 — Subir o servidor Django

```bash
source venv/bin/activate
python manage.py runserver
```

### Passo 2 — Subir o emitter (outro terminal)

```bash
source venv/bin/activate
python emitter.py
```

O emitter sobe:
- **Servidor de callback** na porta 9000 (4 rotas, uma por serviço)
- **Menu interativo** para cadastrar e chamar serviços

### Passo 3 — Cadastrar via menu

Escolha **C** no menu. O emitter pergunta nome, email, eventos e callback URLs:

```text
  📝 CADASTRO DE CONSUMER
  Nome da aplicação: Minha App
  Email: dev@empresa.com
  Eventos (separados por vírgula, ou ENTER para todos): ENTER
  Callback para 'gerar_primos' (ENTER para http://localhost:9000/primos/): ENTER
  Callback para 'pokemon' (ENTER para http://localhost:9000/pokemon/): ENTER
  ...

  ✅ CADASTRO REALIZADO COM SUCESSO!
  🔑 API_KEY    : 9f83137e02352894...
  🔐 SECRET_KEY : eccda6da04eb207f...
  ⚠️  GUARDE A SECRET_KEY — ELA NÃO SERÁ EXIBIDA NOVAMENTE!
```

As credenciais são salvas em `.credenciais.json` automaticamente.

### Passo 4 — Chamar um serviço

Escolha **1**, **2**, **3** ou **4** no menu:

```text
  WEBHOOK CONSUMER — [api_key=9f83137e…]
  C → 📝 Cadastrar como consumer
  E → 📋 Ver eventos disponíveis
  1 → 🔢 POST /webhook/primos/
  2 → 🐾 POST /webhook/pokemon/
  3 → 🗣️  POST /webhook/traduzir/
  4 → 📄 POST /webhook/converter-pdf/
  0 → Sair
```

### Passo 5 — Acompanhar o debug

**Terminal 1 (Django):**

```text
[14:30:01] [INFO] 📥 [POKEMON] Nova requisição recebida
[14:30:01] [DEBUG] 🔑 Autenticando — api_key=9f83137e…
[14:30:01] [INFO] ✅ Autenticado: Minha App (dev@empresa.com)
[14:30:01] [INFO] ⚙️  [WORKER] Thread iniciada para evento='pokemon'
[14:30:01] [INFO] 🐾 [POKEMON] Consultando PokéAPI para 'pikachu'…
[14:30:02] [INFO] 🐾 [POKEMON] Concluído! pikachu (#25)
[14:30:02] [INFO] 📤 [CALLBACK] Enviando para http://localhost:9000/pokemon/…
[14:30:02] [INFO] 📤 [CALLBACK] Entregue com sucesso! HTTP 200
```

**Terminal 2 (Emitter):**

```text
[14:30:01] 📤 POST http://localhost:8000/webhook/pokemon/
[14:30:01]    Api-Key: 9f83137e…
[14:30:01] 📨 HTTP 202: Processando. O resultado será enviado para http://localhost:9000/pokemon/
[14:30:01] ⏳ Aguardando callback…

════════════════════════════════════════════════════════════
  [14:30:02] 📥 CALLBACK RECEBIDO em /pokemon/
  [14:30:02] 📌 Evento: pokemon
════════════════════════════════════════════════════════════
[14:30:02] 🔒 Assinatura HMAC válida — resposta autêntica do servidor
[14:30:02] 🐾 Nome: pikachu (#25)
[14:30:02] 🐾 Tipos: ['electric']
[14:30:02] 🐾 Habilidades: ['static', 'lightning-rod']
```

### Passo 6 — Verificar no Admin

Acesse `http://localhost:8000/admin/` → **Logs de Webhook**:
- Qual consumer chamou
- Qual evento e inscrição
- Status: recebido → processando → concluído → callback_enviado
- Payload e resultado completos

---

## Testando com Swagger

Acesse `http://localhost:8000/api/docs/` com o servidor rodando.

O Swagger documenta todas as rotas com payloads de exemplo. Para testar os serviços autenticados:

1. Execute primeiro **POST /webhook/register/** para se cadastrar
2. Copie a `api_key` da resposta
3. Nas rotas de serviço, passe a `api_key` no header `X-Api-Key`

Para ver os resultados, o emitter precisa estar rodando (ele recebe os callbacks).

---

## Testando com Postman

### Importar a collection

1. Abra o Postman → **Import** → arraste `postman_collection.json`
2. Execute **"Cadastrar consumer"** primeiro — as credenciais são salvas automaticamente nas variáveis da collection
3. Todas as requisições seguintes já usam a `api_key` correta

### Requisições disponíveis

| Pasta | Requisição | Resultado |
|---|---|---|
| Rotas Públicas | Listar eventos | 200 |
| Rotas Públicas | Cadastrar consumer | 201 (auto-preenche api_key) |
| Serviços | Gerar 10 Primos | 202 |
| Serviços | Consultar Pokémon | 202 |
| Serviços | Traduzir para Yoda | 202 |
| Serviços | Converter PDF | 202 (upload de arquivo) |
| Testes de erro | API Key inválida | 401 |
| Testes de erro | Consumer não inscrito | 403 |
| Testes de erro | Email duplicado | 409 |

Para ver os resultados dos serviços, o emitter precisa estar rodando.

---

## Segurança — HMAC no callback

O HMAC é usado apenas no **callback** (servidor → consumer), seguindo o padrão de mercado:

```text
Quando o Django termina de processar, envia o resultado:

  POST http://localhost:9000/pokemon/
  Header: X-Hub-Signature-256: sha256=a1b2c3d4...
  Body: {"evento": "pokemon", "status": "concluido", "resultado": {...}}

O consumer (emitter) valida:

  1. Tem o secret_key (recebeu no cadastro, guardou localmente)
  2. Recalcula: HMAC-SHA256(secret_key, body) → "a1b2c3d4..."
  3. Compara com compare_digest (tempo constante)
  4. Iguais? → Autêntico ✓  (veio do servidor)
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
| Processamento PDF | Docling |
| Async (demo) | threading.Thread (produção: Celery+Redis) |
| Banco | SQLite (gerado automaticamente) |
| Emitter | http.server (stdlib Python) |
