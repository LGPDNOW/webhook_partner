# Webhook com Django — Exemplo Instrucional

Projeto didático que demonstra como webhooks funcionam na prática,
replicando o modelo usado por **Stripe**, **GitHub** e outros serviços do mercado.

---

## O que vai aprender aqui

- O que é um webhook e quando usar
- Autenticação via HMAC-SHA256 (como Stripe/GitHub fazem)
- Fluxo assíncrono: aceita o pedido, processa em background, notifica via callback
- Como um consumer se cadastra, recebe credenciais e consome o serviço

---

## Arquitetura

O projeto tem **dois processos** que conversam entre si:

```text
┌──────────────────────────────┐       ┌──────────────────────────────┐
│     EMITTER (porta 9000)     │       │     DJANGO (porta 8000)      │
│     Simula o consumer        │       │     Servidor do webhook      │
│                              │       │                              │
│  ┌────────────────────────┐  │       │  ┌────────────────────────┐  │
│  │ Menu interativo        │  │       │  │ POST /webhook/         │  │
│  │ (escolhe o serviço)    │──┼──────►│  │ Valida HMAC            │  │
│  └────────────────────────┘  │       │  │ Responde 202           │  │
│                              │       │  └──────────┬─────────────┘  │
│  ┌────────────────────────┐  │       │             │ (thread)       │
│  │ POST /callback/        │◄─┼───────┼─────────────┘               │
│  │ Recebe o resultado     │  │       │  Processa em background:    │
│  │ Valida HMAC            │  │       │  - gera primos              │
│  │ Exibe na tela          │  │       │  - consulta PokéAPI         │
│  └────────────────────────┘  │       │  - traduz texto             │
│                              │       │  - converte PDF → Markdown  │
└──────────────────────────────┘       └──────────────────────────────┘
```

**Isso é exatamente como funciona no mercado:**

| Analogia            | Neste projeto        | No Stripe                     |
|---------------------|----------------------|-------------------------------|
| Você (consumer)     | `emitter.py`         | Sua aplicação                 |
| Se cadastrar        | Django Admin         | Dashboard do Stripe           |
| Receber credenciais | api_key + secret_key | API Key + Webhook Secret      |
| Informar callback   | callback_url         | Endpoint URL no dashboard     |
| Fazer um pedido     | POST /webhook/       | Criar um pagamento            |
| Receber aviso       | POST /callback/      | Stripe chama seu endpoint     |

---

## Eventos disponíveis (4 serviços)

| Evento           | O que faz                              | Payload                                         |
|------------------|----------------------------------------|-------------------------------------------------|
| `gerar_primos`   | Gera os N primeiros números primos     | `{"quantidade": 10}`                            |
| `pokemon`        | Consulta dados na PokéAPI              | `{"pokemon": "pikachu"}`                        |
| `traduzir`       | Traduz texto (Yoda, Pirata, Minion...) | `{"texto": "...", "idioma": "yoda"}`            |
| `converter_pdf`  | Converte PDF para Markdown (Docling)   | `{"pdf_base64": "...", "nome_arquivo": "x.pdf"}`|

---

## Fluxo completo de uma requisição

```text
1. Consumer envia POST /webhook/
   Headers:
     X-Api-Key: <identifica quem é>
     X-Hub-Signature-256: sha256=<prova que é ele — HMAC do body>
     X-Event-Type: gerar_primos

2. Django:
   a) Busca consumer pela api_key ─── "quem é?"
   b) Valida HMAC com secret_key ─── "é realmente ele?"
   c) Verifica se está inscrito ──── "tem permissão?"
   d) Responde 202 Accepted ──────── "ok, recebi"
   e) Dispara thread em background

3. Thread processa o serviço (pode demorar)

4. Quando termina, Django faz POST no callback_url do consumer
   Headers:
     X-Hub-Signature-256: sha256=<HMAC assinado com o secret do consumer>
     X-Event-Type: gerar_primos

5. Consumer recebe o callback:
   a) Valida HMAC ─── "veio mesmo do servidor?"
   b) Exibe o resultado
```

---

## Estrutura do Projeto

```text
webhook/
├── manage.py                    # CLI do Django
├── emitter.py                   # Consumer simulado (servidor callback + menu)
├── requirements.txt             # Dependências (pip freeze)
├── postman_collection.json      # Collection para testar no Postman
├── README.md                    # Este arquivo
│
├── venv/                        # Ambiente virtual Python
│
├── core/                        # Projeto Django
│   ├── settings.py              # Apps, Swagger, banco
│   └── urls.py                  # Rotas: /admin/, /webhook/, /api/docs/
│
└── webhook/                     # App do webhook
    ├── models.py                # Consumer + WebhookLog
    ├── views.py                 # Autenticação + 4 serviços + callback
    ├── urls.py                  # POST /webhook/
    └── admin.py                 # Gerencia consumers e logs
```

---

## Instalação

```bash
# 1. Clone ou acesse o diretório do projeto
cd webhook/

# 2. Crie e ative o ambiente virtual
python3 -m venv venv
source venv/bin/activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Crie o banco e aplique as migrações
python manage.py migrate

# 5. Crie o superusuário para o admin
python manage.py createsuperuser
```

---

## Acessos

| O que             | URL                              | Método |
|-------------------|----------------------------------|--------|
| Webhook endpoint  | `http://localhost:8000/webhook/`  | POST   |
| Django Admin      | `http://localhost:8000/admin/`    | GET    |
| Swagger UI        | `http://localhost:8000/api/docs/` | GET    |
| ReDoc             | `http://localhost:8000/api/redoc/`| GET    |
| OpenAPI Schema    | `http://localhost:8000/api/schema/`| GET   |
| Callback (emitter)| `http://localhost:9000/callback/` | POST   |

**Admin padrão:** `admin` / `admin123`

---

## Passo a passo para testar

### Passo 1 — Cadastrar um Consumer no Admin

1. Acesse `http://localhost:8000/admin/`
2. Vá em **Consumers** → **Adicionar**
3. Preencha:
   - **Nome:** `Sistema Teste`
   - **Email:** `teste@empresa.com`
   - **Callback URL:** `http://localhost:9000/callback/`
   - **Eventos inscritos:** `["gerar_primos", "pokemon", "traduzir", "converter_pdf"]`
4. Salve — o sistema gera automaticamente:
   - `api_key` — identificador público
   - `secret_key` — chave para assinar (NUNCA exponha publicamente)

### Passo 2 — Configurar o Emitter

Abra `emitter.py` e cole as credenciais do consumer:

```python
API_KEY    = "cole_a_api_key_aqui"
SECRET_KEY = "cole_a_secret_key_aqui"
```

### Passo 3 — Subir os dois processos

**Terminal 1** — Servidor Django:
```bash
source venv/bin/activate
python manage.py runserver
```

**Terminal 2** — Emitter (consumer simulado):
```bash
source venv/bin/activate
python emitter.py
```

O emitter sobe dois serviços:
- **Servidor HTTP na porta 9000** — rota `/callback/` esperando notificações
- **Menu interativo** — para escolher qual serviço chamar

### Passo 4 — Escolher um serviço no menu

```text
──────────────────────────────────────────────────────────
  WEBHOOK CONSUMER — Escolha o serviço:
──────────────────────────────────────────────────────────
  1 → Gerar Números Primos
  2 → Consultar Pokémon (PokéAPI)
  3 → Traduzir Texto (Fun Translations)
  4 → Converter PDF → Markdown (Docling)
  0 → Sair
──────────────────────────────────────────────────────────
```

### Passo 5 — Acompanhar o debug

**No Terminal 1 (Django)** você verá:
```text
[14:30:01] [INFO] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[14:30:01] [INFO] 📥 [WEBHOOK] Nova requisição recebida
[14:30:01] [DEBUG] 🔑 Autenticando — api_key=9f83137e…
[14:30:01] [INFO] ✅ Autenticado: Sistema Teste (teste@empresa.com)
[14:30:01] [INFO] 📥 [WEBHOOK] Evento='pokemon' | Consumer=Sistema Teste
[14:30:01] [INFO] ⚙️  [WORKER] Thread iniciada para evento='pokemon'
[14:30:01] [INFO] 🐾 [POKEMON] Consultando PokéAPI para 'pikachu'…
[14:30:02] [INFO] 🐾 [POKEMON] Concluído! pikachu (#25)
[14:30:02] [INFO] 📤 [CALLBACK] Enviando para http://localhost:9000/callback/…
[14:30:02] [INFO] 📤 [CALLBACK] Entregue com sucesso! HTTP 200
```

**No Terminal 2 (Emitter)** você verá:
```text
[14:30:01] 📤 Enviando evento 'pokemon' para http://localhost:8000/webhook/
[14:30:01] 📨 Resposta HTTP 202: {"status": "aceito", ...}
[14:30:01] ⏳ Processamento em andamento… aguardando callback…

════════════════════════════════════════════════════════════
  [14:30:02] 📥 CALLBACK RECEBIDO!
════════════════════════════════════════════════════════════
[14:30:02] 🔒 Assinatura HMAC válida — resposta autêntica do servidor
[14:30:02] 📌 Evento: pokemon
[14:30:02] 🐾 Nome: pikachu (#25)
[14:30:02] 🐾 Tipos: ['electric']
[14:30:02] 🐾 Habilidades: ['static', 'lightning-rod']
```

### Passo 6 — Verificar no Admin

Acesse **Logs de Webhook** no admin e veja:
- Qual consumer chamou
- Qual evento
- Status (recebido → processando → concluído → callback_enviado)
- Payload completo
- Resultado

---

## Testando com Postman

### Importar a collection

1. Abra o Postman
2. **Import** → arraste `postman_collection.json`
3. A collection já tem as credenciais e o Pre-request Script que calcula o HMAC automaticamente

### Requisições disponíveis

| #  | Nome                          | Resultado esperado |
|----|-------------------------------|--------------------|
| 1  | Gerar 10 Primos              | 202 Accepted       |
| 2  | Consultar Pokémon (charizard) | 202 Accepted       |
| 3  | Traduzir para Yoda           | 202 Accepted       |
| 4  | Converter PDF para Markdown  | 202 Accepted       |
| 5  | Assinatura Inválida          | 401 Unauthorized   |
| 6  | Evento não existente         | 400 Bad Request    |

**Importante:** para ver o resultado dos eventos 1-4 no Postman, o emitter.py
precisa estar rodando (é ele que recebe o callback). O Postman só verá o 202.

### Para o evento converter_pdf no Postman

Gere o base64 do PDF no terminal:

```bash
# macOS
base64 -i documento.pdf | pbcopy

# Linux
base64 documento.pdf | xclip -selection clipboard
```

Cole no campo `pdf_base64` do body.

---

## Swagger (documentação interativa)

Com o servidor rodando, acesse:

- **Swagger UI:** `http://localhost:8000/api/docs/`
- **ReDoc:** `http://localhost:8000/api/redoc/`

A documentação mostra:
- Endpoint disponível (POST /webhook/)
- Headers obrigatórios (X-Api-Key, X-Hub-Signature-256, X-Event-Type)
- Payload de cada evento com exemplos
- Códigos de resposta (202, 400, 401, 403)

---

## Rotas do Emitter (callback)

O emitter é um servidor HTTP simples que expõe **uma rota**:

| Rota         | Método | Descrição                                         |
|--------------|--------|----------------------------------------------------|
| `/callback/` | POST   | Recebe a notificação do Django com o resultado     |

**Headers que o Django envia no callback:**

| Header                 | Descrição                                      |
|------------------------|-------------------------------------------------|
| `X-Hub-Signature-256`  | HMAC-SHA256 do body, assinado com o secret_key  |
| `X-Event-Type`         | Tipo do evento (gerar_primos, pokemon, etc.)    |
| `Content-Type`         | application/json                                |

**Body do callback:**

```json
{
    "evento": "pokemon",
    "status": "concluido",
    "resultado": {
        "nome": "pikachu",
        "id": 25,
        "tipos": ["electric"],
        "habilidades": ["static", "lightning-rod"],
        "altura": 4,
        "peso": 60,
        "sprite": "https://raw.githubusercontent.com/.../25.png"
    }
}
```

O emitter valida o HMAC do callback da mesma forma que o Django valida o do consumer — **a autenticação é bidirecional**.

---

## Segurança — HMAC explicado

```text
HMAC = Hash-based Message Authentication Code

Quem ENVIA:
  body = '{"pokemon": "pikachu"}'
  secret = "eccda6da04eb207f..."
  hash = HMAC-SHA256(secret, body) → "a1b2c3d4..."
  Envia: header X-Hub-Signature-256: sha256=a1b2c3d4...

Quem RECEBE:
  Tem o MESMO secret no banco de dados
  Recalcula: HMAC-SHA256(secret, body) → "a1b2c3d4..."
  Compara com compare_digest (tempo constante)
  Iguais? → Autêntico ✓
  Diferentes? → 401 ✗

O secret NUNCA trafega na rede — só o hash.
Sem o secret, é impossível forjar a assinatura.
```

---

## Tecnologias

| Componente        | Tecnologia                                |
|-------------------|-------------------------------------------|
| Servidor          | Django 5.x                                |
| API docs          | drf-spectacular (Swagger / ReDoc)         |
| Processamento PDF | Docling                                   |
| Async (demo)      | threading.Thread (produção: Celery+Redis) |
| Banco             | SQLite (gerado automaticamente)           |
| Emitter           | http.server (stdlib Python)               |






{
  "status": "cadastrado",
  "consumer": {
    "nome": "Maelson",
    "email": "mml@empresa.com",
    "api_key": "7728161a797252fed283ac27d811af32",
    "secret_key": "03ba7766778cc7c1c63297a35a4a40fb26fe61601455dafdb960ee43206f24da",
    "inscricoes": [
      {
        "evento": "gerar_primos",
        "callback_url": "http://localhost:9000/primos/",
        "rota": "/webhook/gerar-primos/"
      },
      {
        "evento": "pokemon",
        "callback_url": "http://localhost:9000/pokemon/",
        "rota": "/webhook/pokemon/"
      }
    ]
  },
  "aviso": "GUARDE a secret_key — ela não será exibida novamente!"
}