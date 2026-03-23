import base64
import hashlib
import hmac
import json
import logging
import tempfile
import threading
import time
import urllib.request

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter

from .models import Consumer, Inscricao, WebhookLog

# ──────────────────────────────────────────────
# Logger com formato detalhado para debug
# ──────────────────────────────────────────────
logger = logging.getLogger("webhook")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "\n[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    ))
    logger.addHandler(handler)


# ═══════════════════════════════════════════════
# AUTENTICAÇÃO
# ═══════════════════════════════════════════════

def autenticar_consumer(request):
    """
    Autentica o consumer pela api_key (header X-Api-Key).

    Padrão de mercado:
      - IDA (consumer → servidor): autenticação por API Key (simples)
      - VOLTA (servidor → callback): autenticação por HMAC (servidor assina)
    """
    api_key = request.headers.get("X-Api-Key", "")

    logger.debug(f"🔑 Autenticando — api_key={api_key[:8]}…")

    if not api_key:
        logger.warning("❌ Header X-Api-Key ausente")
        return None

    try:
        consumer = Consumer.objects.get(api_key=api_key, ativo=True)
    except Consumer.DoesNotExist:
        logger.warning(f"❌ Consumer não encontrado ou inativo: {api_key[:8]}…")
        return None

    logger.info(f"✅ Autenticado: {consumer.nome} ({consumer.email})")
    return consumer


def verificar_inscricao(consumer, evento):
    """Verifica se o consumer está inscrito neste evento e retorna a Inscricao."""
    try:
        return Inscricao.objects.get(consumer=consumer, evento=evento, ativo=True)
    except Inscricao.DoesNotExist:
        logger.warning(f"❌ Consumer '{consumer.nome}' não inscrito em '{evento}'")
        return None


# ═══════════════════════════════════════════════
# SERVIÇOS (processam o evento e retornam o resultado)
# ═══════════════════════════════════════════════

def servico_gerar_primos(payload, log):
    """Gera os primeiros N números primos com delay visual."""
    quantidade = payload.get("quantidade", 10)
    logger.info(f"🔢 [PRIMOS] Iniciando geração de {quantidade} primos…")

    primos = []
    candidato = 2
    while len(primos) < quantidade:
        if all(candidato % p != 0 for p in primos):
            primos.append(candidato)
            if len(primos) % 10 == 0:
                logger.debug(f"🔢 [PRIMOS] Progresso: {len(primos)}/{quantidade} — último: {candidato}")
            time.sleep(0.5)
        candidato += 1

    logger.info(f"🔢 [PRIMOS] Concluído! {quantidade} primos gerados. Último: {primos[-1]}")
    return {"primos": primos, "total": quantidade}


def servico_pokemon(payload, log):
    """Consulta a PokéAPI e retorna dados do Pokémon."""
    pokemon = payload.get("pokemon", "pikachu").lower().strip()
    logger.info(f"🐾 [POKEMON] Consultando PokéAPI para '{pokemon}'…")

    url = f"https://pokeapi.co/api/v2/pokemon/{pokemon}"
    logger.debug(f"🐾 [POKEMON] GET {url}")

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            dados = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error(f"🐾 [POKEMON] Erro na PokéAPI: {e.code}")
        raise ValueError(f"Pokémon '{pokemon}' não encontrado (HTTP {e.code})")

    resultado = {
        "nome": dados["name"],
        "id": dados["id"],
        "tipos": [t["type"]["name"] for t in dados["types"]],
        "altura": dados["height"],
        "peso": dados["weight"],
        "habilidades": [a["ability"]["name"] for a in dados["abilities"]],
        "sprite": dados["sprites"]["front_default"],
    }

    logger.info(f"🐾 [POKEMON] Concluído! {resultado['nome']} (#{resultado['id']}) — tipos: {resultado['tipos']}")
    return resultado


def servico_traduzir(payload, log):
    """Traduz texto usando a Fun Translations API."""
    texto = payload.get("texto", "Hello world")
    idioma = payload.get("idioma", "yoda")
    logger.info(f"🗣️ [TRADUÇÃO] Traduzindo para '{idioma}': \"{texto[:50]}…\"")

    url = f"https://api.funtranslations.com/translate/{idioma}.json"
    dados = json.dumps({"text": texto}).encode()
    req = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    logger.debug(f"🗣️ [TRADUÇÃO] POST {url}")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resposta = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error(f"🗣️ [TRADUÇÃO] Erro na API: {e.code}")
        raise ValueError(f"Erro na Fun Translations API (HTTP {e.code}) — limite de 5 req/hora na versão gratuita")

    traduzido = resposta["contents"]["translated"]
    logger.info(f"🗣️ [TRADUÇÃO] Concluído! \"{traduzido[:80]}…\"")
    return {"original": texto, "traduzido": traduzido, "idioma": idioma}


def servico_converter_pdf(payload, log):
    """Converte PDF para Markdown usando Docling. Recebe caminho do arquivo temporário."""
    caminho_pdf = payload["caminho_pdf"]
    nome_arquivo = payload["nome_arquivo"]
    tamanho = payload["tamanho_bytes"]

    logger.info(f"📄 [PDF→MD] Iniciando conversão: {nome_arquivo} ({tamanho} bytes)")
    logger.info("📄 [PDF→MD] Processando com Docling (pode demorar)…")

    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    resultado = converter.convert(caminho_pdf)
    markdown = resultado.document.export_to_markdown()

    logger.info(f"📄 [PDF→MD] Concluído! {len(markdown)} caracteres de Markdown gerados")
    return {"nome_arquivo": nome_arquivo, "markdown": markdown, "tamanho_chars": len(markdown)}


# ═══════════════════════════════════════════════
# CALLBACK — envia o resultado de volta ao consumer
# ═══════════════════════════════════════════════

def enviar_callback(consumer, inscricao, log, resultado):
    """Envia o resultado assinado para o callback_url da inscrição."""
    callback_url = inscricao.callback_url
    logger.info(f"📤 [CALLBACK] Enviando para {callback_url}…")

    corpo = json.dumps({
        "evento": log.evento,
        "status": "concluido",
        "resultado": resultado,
    }).encode()

    assinatura = "sha256=" + hmac.new(
        consumer.secret_key.encode(),
        corpo,
        hashlib.sha256,
    ).hexdigest()

    req = urllib.request.Request(
        url=callback_url,
        data=corpo,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": assinatura,
            "X-Event-Type": log.evento,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logger.info(f"📤 [CALLBACK] Entregue com sucesso! HTTP {resp.status}")
            log.status = "callback_enviado"
    except Exception as e:
        logger.error(f"📤 [CALLBACK] Falhou: {e}")
        log.status = "callback_falhou"

    log.save()


# ═══════════════════════════════════════════════
# PROCESSAMENTO EM BACKGROUND (thread)
# ═══════════════════════════════════════════════

def processar_em_background(consumer, inscricao, log, payload, servico_fn):
    """Executa o serviço e envia o callback — roda em thread separada."""
    evento = log.evento
    logger.info(f"⚙️  [WORKER] Thread iniciada para evento='{evento}' | consumer={consumer.nome}")

    log.status = "processando"
    log.save()

    try:
        resultado = servico_fn(payload, log)

        log.status = "concluido"
        log.resultado = resultado
        log.save()
        logger.info(f"⚙️  [WORKER] Evento '{evento}' processado com sucesso!")

        enviar_callback(consumer, inscricao, log, resultado)

    except Exception as e:
        logger.error(f"⚙️  [WORKER] Erro ao processar '{evento}': {e}")
        log.status = "erro"
        log.resultado = {"erro": str(e)}
        log.save()

        enviar_callback(consumer, inscricao, log, {"erro": str(e)})


# ═══════════════════════════════════════════════
# HANDLER GENÉRICO — usado por cada rota de evento
# ═══════════════════════════════════════════════

def processar_evento(request, evento, servico_fn):
    """Lógica comum: autentica → verifica inscrição → dispara background."""
    logger.info("━" * 60)
    logger.info(f"📥 [{evento.upper()}] Nova requisição recebida")

    consumer = autenticar_consumer(request)

    if not consumer:
        WebhookLog.objects.create(
            consumer=None, evento=evento,
            payload={}, assinatura_valida=False,
        )
        return Response({"erro": "Não autorizado."}, status=401)

    inscricao = verificar_inscricao(consumer, evento)

    if not inscricao:
        return Response({
            "erro": f"Consumer '{consumer.nome}' não inscrito no evento '{evento}'. Cadastre-se em POST /webhook/register/",
        }, status=403)

    payload = request.data
    log = WebhookLog.objects.create(
        consumer=consumer, inscricao=inscricao,
        evento=evento, payload=payload,
    )
    logger.info(f"📥 [{evento.upper()}] Log #{log.pk} — callback será enviado para {inscricao.callback_url}")

    thread = threading.Thread(
        target=processar_em_background,
        args=(consumer, inscricao, log, payload, servico_fn),
    )
    thread.start()

    return Response({
        "status": "aceito",
        "evento": evento,
        "mensagem": f"Processando. O resultado será enviado para {inscricao.callback_url}",
        "log_id": log.pk,
    }, status=202)


# ═══════════════════════════════════════════════
# Decoradores comuns
# ═══════════════════════════════════════════════

AUTH_HEADERS = [
    OpenApiParameter(name="X-Api-Key", location="header", required=True, type=str,
                     description="api_key do consumer (obtida no cadastro via POST /webhook/register/)"),
]

RESPOSTAS_COMUNS = {
    202: {
        "type": "object",
        "properties": {
            "status": {"type": "string", "example": "aceito"},
            "evento": {"type": "string"},
            "mensagem": {"type": "string"},
            "log_id": {"type": "integer", "example": 1},
        },
        "description": "Evento aceito. Resultado será enviado via callback assinado com HMAC.",
    },
    401: {"description": "api_key inválida ou ausente"},
    403: {"description": "Consumer não inscrito neste evento"},
}


# ═══════════════════════════════════════════════
# 4 ROTAS DE EVENTOS — cada uma com sua view
# ═══════════════════════════════════════════════

@extend_schema(
    summary="Gerar números primos",
    description=(
        "Gera os primeiros N números primos. O processamento tem delay de 0.5s "
        "por primo para demonstrar o comportamento assíncrono.\n\n"
        "O resultado será enviado para o callback_url cadastrado para este evento."
    ),
    parameters=AUTH_HEADERS,
    request={"application/json": {
        "type": "object",
        "properties": {
            "quantidade": {"type": "integer", "example": 10, "description": "Quantidade de primos a gerar (padrão: 10)"},
        },
    }},
    responses=RESPOSTAS_COMUNS,
    tags=["Serviços"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def webhook_primos(request):
    return processar_evento(request, "gerar_primos", servico_gerar_primos)


@extend_schema(
    summary="Consultar Pokémon",
    description=(
        "Consulta dados de um Pokémon na PokéAPI.\n\n"
        "Retorna: nome, id, tipos, habilidades, altura, peso e sprite."
    ),
    parameters=AUTH_HEADERS,
    request={"application/json": {
        "type": "object",
        "properties": {
            "pokemon": {"type": "string", "example": "pikachu", "description": "Nome do Pokémon"},
        },
    }},
    responses=RESPOSTAS_COMUNS,
    tags=["Serviços"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def webhook_pokemon(request):
    return processar_evento(request, "pokemon", servico_pokemon)


@extend_schema(
    summary="Traduzir texto",
    description=(
        "Traduz texto para idiomas fictícios via Fun Translations API.\n\n"
        "Idiomas: yoda, pirate, minion, shakespeare, dothraki.\n\n"
        "**Nota:** API gratuita tem limite de 5 requisições/hora."
    ),
    parameters=AUTH_HEADERS,
    request={"application/json": {
        "type": "object",
        "properties": {
            "texto": {"type": "string", "example": "The force is strong with this one"},
            "idioma": {"type": "string", "example": "yoda", "description": "yoda, pirate, minion, shakespeare, dothraki"},
        },
    }},
    responses=RESPOSTAS_COMUNS,
    tags=["Serviços"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def webhook_traduzir(request):
    return processar_evento(request, "traduzir", servico_traduzir)


@extend_schema(
    summary="Converter PDF para Markdown",
    description=(
        "Converte um PDF para Markdown usando Docling.\n\n"
        "O PDF deve ser enviado como **upload de arquivo** (multipart/form-data).\n\n"
        "**Campo do formulário:**\n"
        "- `arquivo`: O arquivo PDF (obrigatório)\n\n"
        "**Autenticação:** header `X-Api-Key` com a api_key do consumer.\n\n"
        "Processamento pesado — pode demorar de 10s a vários minutos.\n"
        "O resultado será enviado via callback assinado com HMAC."
    ),
    parameters=AUTH_HEADERS,
    request={"multipart/form-data": {
        "type": "object",
        "required": ["arquivo"],
        "properties": {
            "arquivo": {"type": "string", "format": "binary", "description": "Arquivo PDF para converter"},
        },
    }},
    responses=RESPOSTAS_COMUNS,
    tags=["Serviços"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def webhook_converter_pdf(request):
    """View dedicada para upload de PDF — não usa processar_evento genérico."""
    evento = "converter_pdf"
    logger.info("━" * 60)
    logger.info(f"📥 [{evento.upper()}] Nova requisição recebida (multipart/form-data)")

    consumer = autenticar_consumer(request)

    if not consumer:
        WebhookLog.objects.create(
            consumer=None, evento=evento,
            payload={"erro": "autenticação falhou"}, assinatura_valida=False,
        )
        return Response({"erro": "Não autorizado."}, status=401)

    inscricao = verificar_inscricao(consumer, evento)
    if not inscricao:
        return Response({
            "erro": f"Consumer '{consumer.nome}' não inscrito no evento '{evento}'.",
        }, status=403)

    # Valida o arquivo
    arquivo = request.FILES.get("arquivo")
    if not arquivo:
        return Response({"erro": "Campo 'arquivo' é obrigatório (envie um PDF)."}, status=400)

    if not arquivo.name.lower().endswith(".pdf"):
        return Response({"erro": "Apenas arquivos .pdf são aceitos."}, status=400)

    # Salva em arquivo temporário
    pdf_bytes = arquivo.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        caminho_pdf = tmp.name

    logger.info(f"📥 [{evento.upper()}] Arquivo: {arquivo.name} ({len(pdf_bytes)} bytes) → {caminho_pdf}")

    payload = {
        "caminho_pdf": caminho_pdf,
        "nome_arquivo": arquivo.name,
        "tamanho_bytes": len(pdf_bytes),
    }

    log = WebhookLog.objects.create(
        consumer=consumer, inscricao=inscricao,
        evento=evento, payload={"nome_arquivo": arquivo.name, "tamanho_bytes": len(pdf_bytes)},
    )

    thread = threading.Thread(
        target=processar_em_background,
        args=(consumer, inscricao, log, payload, servico_converter_pdf),
    )
    thread.start()

    return Response({
        "status": "aceito",
        "evento": evento,
        "arquivo": arquivo.name,
        "tamanho_bytes": len(pdf_bytes),
        "mensagem": f"PDF recebido. O Markdown será enviado para {inscricao.callback_url}",
        "log_id": log.pk,
    }, status=202)


# ═══════════════════════════════════════════════
# REGISTRO DE CONSUMER — rota pública
# ═══════════════════════════════════════════════

EVENTOS_VALIDOS = ["gerar_primos", "pokemon", "traduzir", "converter_pdf"]


@extend_schema(
    summary="Cadastrar novo consumer",
    description=(
        "Rota pública para auto-cadastro.\n\n"
        "O consumer informa seus dados e as inscrições (evento + callback_url para cada).\n"
        "Recebe de volta api_key + secret_key. A **secret_key só é exibida uma vez**."
    ),
    request={"application/json": {
        "type": "object",
        "required": ["nome", "email", "inscricoes"],
        "properties": {
            "nome": {"type": "string", "example": "Minha Aplicação"},
            "email": {"type": "string", "format": "email", "example": "dev@empresa.com"},
            "inscricoes": {
                "type": "array",
                "description": "Lista de eventos com callback_url individual",
                "items": {
                    "type": "object",
                    "required": ["evento", "callback_url"],
                    "properties": {
                        "evento": {"type": "string", "enum": EVENTOS_VALIDOS},
                        "callback_url": {"type": "string", "format": "uri"},
                    },
                },
                "example": [
                    {"evento": "gerar_primos", "callback_url": "http://localhost:9000/primos/"},
                    {"evento": "pokemon", "callback_url": "http://localhost:9000/pokemon/"},
                ],
            },
        },
    }},
    responses={
        201: {
            "type": "object",
            "description": "Consumer cadastrado com sucesso",
        },
        400: {"description": "Dados inválidos ou campos ausentes"},
        409: {"description": "Email já cadastrado"},
    },
    examples=[
        OpenApiExample(
            "Cadastro com 2 eventos",
            value={
                "nome": "Minha Aplicação",
                "email": "dev@empresa.com",
                "inscricoes": [
                    {"evento": "gerar_primos", "callback_url": "http://localhost:9000/primos/"},
                    {"evento": "pokemon", "callback_url": "http://localhost:9000/pokemon/"},
                ],
            },
            request_only=True,
        ),
        OpenApiExample(
            "Cadastro com todos os eventos",
            value={
                "nome": "Sistema Parceiro",
                "email": "parceiro@empresa.com",
                "inscricoes": [
                    {"evento": "gerar_primos", "callback_url": "http://localhost:9000/primos/"},
                    {"evento": "pokemon", "callback_url": "http://localhost:9000/pokemon/"},
                    {"evento": "traduzir", "callback_url": "http://localhost:9000/traduzir/"},
                    {"evento": "converter_pdf", "callback_url": "http://localhost:9000/converter-pdf/"},
                ],
            },
            request_only=True,
        ),
    ],
    tags=["Registro"],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def registrar(request):
    logger.info("━" * 60)
    logger.info("📝 [REGISTRO] Nova solicitação de cadastro")

    dados = request.data
    nome = dados.get("nome", "").strip()
    email = dados.get("email", "").strip()
    inscricoes = dados.get("inscricoes", [])

    if not nome or not email:
        return Response({"erro": "Campos obrigatórios: nome, email"}, status=400)

    if not inscricoes:
        return Response({"erro": "Informe pelo menos uma inscrição com evento e callback_url"}, status=400)

    if Consumer.objects.filter(email=email).exists():
        return Response({"erro": f"Email '{email}' já está cadastrado"}, status=409)

    # Valida cada inscrição
    for insc in inscricoes:
        evento = insc.get("evento", "")
        callback = insc.get("callback_url", "")
        if not evento or not callback:
            return Response({"erro": "Cada inscrição precisa de 'evento' e 'callback_url'"}, status=400)
        if evento not in EVENTOS_VALIDOS:
            return Response({"erro": f"Evento '{evento}' inválido. Disponíveis: {EVENTOS_VALIDOS}"}, status=400)

    # Cria consumer
    consumer = Consumer(nome=nome, email=email)
    consumer.save()

    # Cria inscrições
    inscricoes_criadas = []
    for insc in inscricoes:
        obj = Inscricao.objects.create(
            consumer=consumer,
            evento=insc["evento"],
            callback_url=insc["callback_url"],
        )
        inscricoes_criadas.append({
            "evento": obj.evento,
            "callback_url": obj.callback_url,
            "rota": f"/webhook/{obj.evento.replace('_', '-')}/",
        })

    logger.info(f"📝 [REGISTRO] Consumer criado: {consumer.nome} | {len(inscricoes_criadas)} inscrições")

    return Response({
        "status": "cadastrado",
        "consumer": {
            "nome": consumer.nome,
            "email": consumer.email,
            "api_key": consumer.api_key,
            "secret_key": consumer.secret_key,
            "inscricoes": inscricoes_criadas,
        },
        "aviso": "GUARDE a secret_key — ela não será exibida novamente!",
    }, status=201)


# ═══════════════════════════════════════════════
# LISTAR EVENTOS DISPONÍVEIS — rota pública
# ═══════════════════════════════════════════════

@extend_schema(
    summary="Listar eventos disponíveis",
    description="Retorna todos os eventos com suas rotas, descrição e payload esperado.",
    responses={200: {"type": "object"}},
    tags=["Registro"],
)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def listar_eventos(request):
    return Response({
        "eventos": [
            {
                "nome": "gerar_primos",
                "rota": "/webhook/primos/",
                "metodo": "POST",
                "descricao": "Gera os primeiros N números primos (delay 0.5s cada para demonstração)",
                "payload_exemplo": {"quantidade": 10},
            },
            {
                "nome": "pokemon",
                "rota": "/webhook/pokemon/",
                "metodo": "POST",
                "descricao": "Consulta dados de um Pokémon na PokéAPI",
                "payload_exemplo": {"pokemon": "pikachu"},
            },
            {
                "nome": "traduzir",
                "rota": "/webhook/traduzir/",
                "metodo": "POST",
                "descricao": "Traduz texto para idiomas fictícios via Fun Translations API",
                "payload_exemplo": {"texto": "The force is strong", "idioma": "yoda"},
                "idiomas_disponiveis": ["yoda", "pirate", "minion", "shakespeare", "dothraki"],
            },
            {
                "nome": "converter_pdf",
                "rota": "/webhook/converter-pdf/",
                "metodo": "POST",
                "descricao": "Converte PDF para Markdown usando Docling",
                "payload_exemplo": {"pdf_base64": "<base64 do PDF>", "nome_arquivo": "doc.pdf"},
            },
        ],
    })
