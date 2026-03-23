"""
emitter.py — Simulador de sistema consumer de webhook

Dois serviços em um:
  1. SERVIDOR HTTP (porta 9000) — rotas de callback por evento
  2. CLIENTE — menu interativo para chamar os serviços

Rotas de callback (cada evento recebe na sua rota):
  POST /primos/        → recebe resultado de gerar_primos
  POST /pokemon/       → recebe resultado de pokemon
  POST /traduzir/      → recebe resultado de traduzir
  POST /converter-pdf/ → recebe resultado de converter_pdf

Uso:
    python emitter.py
"""

import hashlib
import hmac
import json
import os
import sys
import threading
import urllib.request
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ──────────────────────────────────────────────────────────────────
# Configuração
# ──────────────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8000"
REGISTER_URL = f"{BASE_URL}/webhook/register/"
EVENTS_URL = f"{BASE_URL}/webhook/events/"
CALLBACK_PORT = 9000
CALLBACK_BASE = f"http://localhost:{CALLBACK_PORT}"

# Mapa de evento → rota no Django e rota de callback local
SERVICOS = {
    "gerar_primos": {
        "rota_django": f"{BASE_URL}/webhook/primos/",
        "callback": f"{CALLBACK_BASE}/primos/",
    },
    "pokemon": {
        "rota_django": f"{BASE_URL}/webhook/pokemon/",
        "callback": f"{CALLBACK_BASE}/pokemon/",
    },
    "traduzir": {
        "rota_django": f"{BASE_URL}/webhook/traduzir/",
        "callback": f"{CALLBACK_BASE}/traduzir/",
    },
    "converter_pdf": {
        "rota_django": f"{BASE_URL}/webhook/converter-pdf/",
        "callback": f"{CALLBACK_BASE}/converter-pdf/",
    },
}

# Credenciais — preenchidas ao se cadastrar
API_KEY = ""
SECRET_KEY = ""
CREDENCIAIS_ARQUIVO = ".credenciais.json"
"""
[23:21:34]   🔑 API_KEY    : eaa667b3bc335c2f9b83728b456f087d
[23:21:34]   🔐 SECRET_KEY : 0c6fe4e27bcfd0e70836509eadaa971cc1cb5e4f778339c2262
"""

def log(msg):
    """Log com timestamp."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def salvar_credenciais():
    """Salva credenciais em arquivo local."""
    with open(CREDENCIAIS_ARQUIVO, "w") as f:
        json.dump({"api_key": API_KEY, "secret_key": SECRET_KEY}, f)
    log(f"💾 Credenciais salvas em {CREDENCIAIS_ARQUIVO}")


def carregar_credenciais() -> bool:
    """Carrega credenciais salvas."""
    global API_KEY, SECRET_KEY
    if os.path.exists(CREDENCIAIS_ARQUIVO):
        with open(CREDENCIAIS_ARQUIVO) as f:
            dados = json.load(f)
        API_KEY = dados["api_key"]
        SECRET_KEY = dados["secret_key"]
        log(f"🔑 Credenciais carregadas — api_key={API_KEY[:8]}…")
        return True
    return False


# ═══════════════════════════════════════════════
# SERVIDOR DE CALLBACK (porta 9000)
# ═══════════════════════════════════════════════

# Mapa de path → nome do evento para exibição
CALLBACK_ROTAS = {
    "/primos/": "gerar_primos",
    "/pokemon/": "pokemon",
    "/traduzir/": "traduzir",
    "/converter-pdf/": "converter_pdf",
}


class CallbackHandler(BaseHTTPRequestHandler):
    """Recebe callbacks do Django — uma rota por evento."""

    def do_POST(self):
        ts = datetime.now().strftime("%H:%M:%S")
        path = self.path

        # Identifica qual evento pela rota
        evento_nome = CALLBACK_ROTAS.get(path, "desconhecido")

        tamanho = int(self.headers.get("Content-Length", 0))
        corpo = self.rfile.read(tamanho)

        print(f"\n{'=' * 60}")
        print(f"  [{ts}] 📥 CALLBACK RECEBIDO em {path}")
        print(f"  [{ts}] 📌 Evento: {evento_nome}")
        print(f"{'=' * 60}")

        # Valida HMAC
        assinatura_recebida = self.headers.get("X-Hub-Signature-256", "")
        assinatura_esperada = "sha256=" + hmac.new(
            SECRET_KEY.encode(), corpo, hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(assinatura_recebida, assinatura_esperada):
            log("🔒 Assinatura HMAC válida — resposta autêntica do servidor")
        else:
            log("⚠️  Assinatura HMAC INVÁLIDA — resposta pode ser forjada!")

        dados = json.loads(corpo)
        status = dados.get("status", "?")
        resultado = dados.get("resultado", {})

        log(f"📌 Status: {status}")

        if "erro" in resultado:
            log(f"❌ Erro: {resultado['erro']}")
        elif evento_nome == "gerar_primos":
            log(f"🔢 Total: {resultado['total']} primos")
            log(f"🔢 Primos: {resultado['primos']}")
        elif evento_nome == "pokemon":
            log(f"🐾 Nome: {resultado['nome']} (#{resultado['id']})")
            log(f"🐾 Tipos: {resultado['tipos']}")
            log(f"🐾 Habilidades: {resultado['habilidades']}")
            log(f"🐾 Altura: {resultado['altura']} | Peso: {resultado['peso']}")
            log(f"🐾 Sprite: {resultado['sprite']}")
        elif evento_nome == "traduzir":
            log(f"🗣️  Idioma: {resultado['idioma']}")
            log(f"🗣️  Original: {resultado['original']}")
            log(f"🗣️  Traduzido: {resultado['traduzido']}")
        elif evento_nome == "converter_pdf":
            log(f"📄 Arquivo: {resultado['nome_arquivo']}")
            log(f"📄 Tamanho: {resultado['tamanho_chars']} caracteres")
            log(f"📄 Markdown (primeiros 500 chars):")
            print("-" * 40)
            print(resultado["markdown"][:500])
            print("-" * 40)

        print(f"\n{'=' * 60}")
        log("✅ Callback processado! Aguardando próximo evento…")
        print(f"{'=' * 60}\n")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def iniciar_servidor_callback():
    """Sobe o servidor HTTP com rotas de callback por evento."""
    servidor = HTTPServer(("0.0.0.0", CALLBACK_PORT), CallbackHandler)
    log(f"🖥️  Servidor de callback rodando na porta {CALLBACK_PORT}")
    log("   Rotas registradas:")
    for path, evento in CALLBACK_ROTAS.items():
        log(f"     POST {CALLBACK_BASE}{path} → {evento}")
    servidor.serve_forever()


# ═══════════════════════════════════════════════
# CADASTRO — auto-registro via API
# ═══════════════════════════════════════════════

def cadastrar():
    """Cadastra o consumer via POST /webhook/register/."""
    global API_KEY, SECRET_KEY

    print("\n" + "─" * 60)
    print("  📝 CADASTRO DE CONSUMER")
    print("─" * 60)

    nome = input("  Nome da aplicação: ").strip()
    email = input("  Email: ").strip()

    if not nome or not email:
        log("❌ Nome e email são obrigatórios")
        return False

    # Mostra eventos disponíveis
    log("📋 Consultando eventos disponíveis…")
    try:
        with urllib.request.urlopen(EVENTS_URL, timeout=5) as resp:
            dados = json.loads(resp.read())
        print()
        for ev in dados["eventos"]:
            print(f"    • {ev['nome']:20s} — {ev['descricao']}")
            print(f"      Rota: {ev['rota']}")
        print()
    except Exception as e:
        log(f"⚠️  Não foi possível listar eventos: {e}")

    eventos_input = input("  Eventos (separados por vírgula, ou ENTER para todos): ").strip()
    if eventos_input:
        eventos_escolhidos = [e.strip() for e in eventos_input.split(",") if e.strip()]
    else:
        eventos_escolhidos = list(SERVICOS.keys())

    # Para cada evento, pergunta o callback ou usa o padrão
    inscricoes = []
    for evento in eventos_escolhidos:
        if evento not in SERVICOS:
            log(f"⚠️  Evento '{evento}' inválido, pulando…")
            continue
        padrao = SERVICOS[evento]["callback"]
        callback_input = input(f"  Callback para '{evento}' (ENTER para {padrao}): ").strip()
        callback = callback_input or padrao
        inscricoes.append({"evento": evento, "callback_url": callback})

    if not inscricoes:
        log("❌ Nenhuma inscrição válida")
        return False

    payload = {"nome": nome, "email": email, "inscricoes": inscricoes}
    corpo = json.dumps(payload).encode()
    req = urllib.request.Request(
        url=REGISTER_URL, data=corpo, method="POST",
        headers={"Content-Type": "application/json"},
    )

    log(f"📤 Enviando cadastro para {REGISTER_URL}…")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            dados = json.loads(resp.read())

        consumer = dados["consumer"]
        API_KEY = consumer["api_key"]
        SECRET_KEY = consumer["secret_key"]

        print(f"\n{'=' * 60}")
        log("✅ CADASTRO REALIZADO COM SUCESSO!")
        print(f"{'=' * 60}")
        log(f"  Nome      : {consumer['nome']}")
        log(f"  Email     : {consumer['email']}")
        print(f"{'─' * 60}")
        log(f"  🔑 API_KEY    : {consumer['api_key']}")
        log(f"  🔐 SECRET_KEY : {consumer['secret_key']}")
        print(f"{'─' * 60}")
        log("  Inscrições:")
        for insc in consumer["inscricoes"]:
            log(f"    {insc['evento']:20s} → {insc['rota']}")
            log(f"    {'':20s}    callback: {insc['callback_url']}")
        print(f"{'─' * 60}")
        log("  ⚠️  GUARDE A SECRET_KEY — ELA NÃO SERÁ EXIBIDA NOVAMENTE!")
        print(f"{'=' * 60}\n")

        salvar_credenciais()
        return True

    except urllib.error.HTTPError as e:
        corpo_erro = json.loads(e.read())
        log(f"❌ Erro {e.code}: {corpo_erro.get('erro', corpo_erro)}")
        return False
    except Exception as e:
        log(f"❌ Erro: {e}")
        return False


# ═══════════════════════════════════════════════
# CLIENTE — envia requisições para o webhook
# ═══════════════════════════════════════════════

def enviar_webhook(evento: str, payload: dict):
    """Envia o POST JSON autenticado por API Key para a rota do evento."""
    if not API_KEY:
        log("❌ Sem credenciais! Faça o cadastro primeiro (opção C).")
        return

    servico = SERVICOS.get(evento)
    if not servico:
        log(f"❌ Evento '{evento}' desconhecido")
        return

    url = servico["rota_django"]
    corpo = json.dumps(payload).encode()

    req = urllib.request.Request(
        url=url, data=corpo, method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": API_KEY,
        },
    )

    print()
    log(f"📤 POST {url}")
    log(f"   Payload: {str(payload)[:100]}…")
    log(f"   Api-Key: {API_KEY[:8]}…")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            dados = json.loads(resp.read())
            log(f"📨 HTTP {resp.status}: {dados['mensagem']}")
            log("⏳ Aguardando callback…")
    except urllib.error.HTTPError as e:
        corpo_erro = e.read().decode()
        log(f"❌ Erro HTTP {e.code}: {corpo_erro}")
    except Exception as e:
        log(f"❌ Erro: {e}")


def enviar_upload_pdf(caminho: str):
    """Envia PDF via multipart/form-data autenticado por API Key."""
    if not API_KEY:
        log("❌ Sem credenciais! Faça o cadastro primeiro (opção C).")
        return

    url = SERVICOS["converter_pdf"]["rota_django"]

    with open(caminho, "rb") as f:
        pdf_bytes = f.read()

    nome_arquivo = os.path.basename(caminho)

    # Monta multipart/form-data manualmente (stdlib pura)
    boundary = "----WebhookBoundary"
    corpo = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="arquivo"; filename="{nome_arquivo}"\r\n'
        f"Content-Type: application/pdf\r\n"
        f"\r\n"
    ).encode() + pdf_bytes + f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        url=url, data=corpo, method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "X-Api-Key": API_KEY,
        },
    )

    print()
    log(f"📤 POST {url} (multipart upload)")
    log(f"   Arquivo: {nome_arquivo} ({len(pdf_bytes)} bytes)")
    log(f"   Api-Key: {API_KEY[:8]}…")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            dados = json.loads(resp.read())
            log(f"📨 HTTP {resp.status}: {dados['mensagem']}")
            log("⏳ Aguardando callback…")
    except urllib.error.HTTPError as e:
        corpo_erro = e.read().decode()
        log(f"❌ Erro HTTP {e.code}: {corpo_erro}")
    except Exception as e:
        log(f"❌ Erro: {e}")


# ═══════════════════════════════════════════════
# MENU INTERATIVO
# ═══════════════════════════════════════════════

def menu():
    """Menu para escolher o evento a disparar."""
    while True:
        status = f"api_key={API_KEY[:8]}…" if API_KEY else "NÃO CADASTRADO"

        print("\n" + "─" * 60)
        print(f"  WEBHOOK CONSUMER — [{status}]")
        print("─" * 60)
        print("  C → 📝 Cadastrar como consumer")
        print("  E → 📋 Ver eventos disponíveis")
        print("─" * 60)
        print("  1 → 🔢 POST /webhook/primos/")
        print("  2 → 🐾 POST /webhook/pokemon/")
        print("  3 → 🗣️  POST /webhook/traduzir/")
        print("  4 → 📄 POST /webhook/converter-pdf/")
        print("  0 → Sair")
        print("─" * 60)

        opcao = input("  Opção: ").strip().upper()

        if opcao == "C":
            cadastrar()

        elif opcao == "E":
            log("📋 Consultando eventos disponíveis…")
            try:
                with urllib.request.urlopen(EVENTS_URL, timeout=5) as resp:
                    dados = json.loads(resp.read())
                print()
                for ev in dados["eventos"]:
                    print(f"    • {ev['rota']:30s} {ev['metodo']:6s} — {ev['descricao']}")
                    print(f"      Payload: {ev['payload_exemplo']}")
                    if "idiomas_disponiveis" in ev:
                        print(f"      Idiomas: {ev['idiomas_disponiveis']}")
                    print()
            except Exception as e:
                log(f"❌ Erro: {e}")

        elif opcao == "1":
            qtd = input("  Quantidade de primos (ex: 10): ").strip()
            enviar_webhook("gerar_primos", {"quantidade": int(qtd or 10)})

        elif opcao == "2":
            nome = input("  Nome do Pokémon (ex: pikachu): ").strip()
            enviar_webhook("pokemon", {"pokemon": nome or "pikachu"})

        elif opcao == "3":
            texto = input("  Texto para traduzir: ").strip()
            print("  Idiomas: yoda, pirate, minion, shakespeare, dothraki")
            idioma = input("  Idioma (ex: yoda): ").strip()
            enviar_webhook("traduzir", {
                "texto": texto or "The force is strong with this one",
                "idioma": idioma or "yoda",
            })

        elif opcao == "4":
            caminho = input("  Caminho do PDF (ex: /path/doc.pdf): ").strip()
            if not caminho:
                log("❌ Caminho do PDF é obrigatório")
                continue
            if not os.path.exists(caminho):
                log(f"❌ Arquivo não encontrado: {caminho}")
                continue
            enviar_upload_pdf(caminho)

        elif opcao == "0":
            log("👋 Encerrando…")
            sys.exit(0)

        else:
            log("❌ Opção inválida")


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("═" * 60)
    print("  WEBHOOK CONSUMER — Sistema Emissor")
    print("═" * 60)

    # Tenta carregar credenciais salvas
    if not carregar_credenciais():
        log("ℹ️  Nenhuma credencial encontrada.")
        log("   Use a opção C no menu para se cadastrar.")

    # Sobe o servidor de callback em thread separada
    thread_servidor = threading.Thread(target=iniciar_servidor_callback, daemon=True)
    thread_servidor.start()

    menu()
