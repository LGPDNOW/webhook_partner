import json
import logging
import tempfile

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiExample, OpenApiParameter

from .models import Consumer, Inscricao, WebhookLog
from .tasks import TASK_MAP

# ──────────────────────────────────────────────
# Logger
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
    """Verifica se o consumer está inscrito neste evento."""
    try:
        return Inscricao.objects.get(consumer=consumer, evento=evento, ativo=True)
    except Inscricao.DoesNotExist:
        logger.warning(f"❌ Consumer '{consumer.nome}' não inscrito em '{evento}'")
        return None


# ═══════════════════════════════════════════════
# HANDLER GENÉRICO — autentica e enfileira no Celery
# ═══════════════════════════════════════════════

def processar_evento(request, evento):
    """Lógica comum: autentica → verifica inscrição → enfileira task no Celery."""
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
    logger.info(f"📥 [{evento.upper()}] Log #{log.pk} — enfileirando no Celery…")

    # Enfileira a task no Redis via Celery
    task = TASK_MAP[evento]
    task.delay(log.pk, payload, consumer.pk, inscricao.pk)

    logger.info(f"📥 [{evento.upper()}] Task enfileirada! Callback será enviado para {inscricao.callback_url}")

    return Response({
        "status": "aceito",
        "evento": evento,
        "mensagem": f"Processando. O resultado será enviado para {inscricao.callback_url}",
        "log_id": log.pk,
    }, status=202)


# ═══════════════════════════════════════════════
# Swagger — parâmetros e respostas comuns
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
        "description": "Evento aceito e enfileirado no Celery. Resultado será enviado via callback assinado com HMAC.",
    },
    401: {"description": "api_key inválida ou ausente"},
    403: {"description": "Consumer não inscrito neste evento"},
}


# ═══════════════════════════════════════════════
# 4 ROTAS DE EVENTOS
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
    return processar_evento(request, "gerar_primos")


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
    return processar_evento(request, "pokemon")


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
    return processar_evento(request, "traduzir")


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
    """View dedicada para upload de PDF."""
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

    # Enfileira no Celery
    task = TASK_MAP[evento]
    task.delay(log.pk, payload, consumer.pk, inscricao.pk)

    logger.info(f"📥 [{evento.upper()}] Task enfileirada no Celery!")

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
        201: {"type": "object", "description": "Consumer cadastrado com sucesso"},
        400: {"description": "Dados inválidos ou campos ausentes"},
        409: {"description": "Email já cadastrado"},
    },
    examples=[
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

    for insc in inscricoes:
        evento = insc.get("evento", "")
        callback = insc.get("callback_url", "")
        if not evento or not callback:
            return Response({"erro": "Cada inscrição precisa de 'evento' e 'callback_url'"}, status=400)
        if evento not in EVENTOS_VALIDOS:
            return Response({"erro": f"Evento '{evento}' inválido. Disponíveis: {EVENTOS_VALIDOS}"}, status=400)

    consumer = Consumer(nome=nome, email=email)
    consumer.save()

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
                "descricao": "Converte PDF para Markdown usando Docling (upload multipart/form-data)",
                "payload_exemplo": {"arquivo": "(upload PDF)"},
            },
        ],
    })
