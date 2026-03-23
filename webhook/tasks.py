import hashlib
import hmac
import json
import logging
import time
import urllib.request

from celery import shared_task

logger = logging.getLogger("webhook")


# ═══════════════════════════════════════════════
# SERVIÇOS — cada um é uma Celery task
# ═══════════════════════════════════════════════

@shared_task(bind=True, name="webhook.gerar_primos")
def task_gerar_primos(self, log_id, payload, consumer_id, inscricao_id):
    """Gera os primeiros N números primos com delay visual."""
    return _executar(log_id, payload, consumer_id, inscricao_id, _servico_gerar_primos)


@shared_task(bind=True, name="webhook.pokemon")
def task_pokemon(self, log_id, payload, consumer_id, inscricao_id):
    """Consulta a PokéAPI."""
    return _executar(log_id, payload, consumer_id, inscricao_id, _servico_pokemon)


@shared_task(bind=True, name="webhook.traduzir")
def task_traduzir(self, log_id, payload, consumer_id, inscricao_id):
    """Traduz texto via Fun Translations API."""
    return _executar(log_id, payload, consumer_id, inscricao_id, _servico_traduzir)


@shared_task(bind=True, name="webhook.converter_pdf")
def task_converter_pdf(self, log_id, payload, consumer_id, inscricao_id):
    """Converte PDF para Markdown usando Docling."""
    return _executar(log_id, payload, consumer_id, inscricao_id, _servico_converter_pdf)


# Mapa de evento → task (usado pela view)
TASK_MAP = {
    "gerar_primos": task_gerar_primos,
    "pokemon": task_pokemon,
    "traduzir": task_traduzir,
    "converter_pdf": task_converter_pdf,
}


# ═══════════════════════════════════════════════
# EXECUTOR GENÉRICO — roda dentro do worker Celery
# ═══════════════════════════════════════════════

def _executar(log_id, payload, consumer_id, inscricao_id, servico_fn):
    """Busca os objetos do banco, executa o serviço e envia o callback."""
    from .models import Consumer, Inscricao, WebhookLog

    log = WebhookLog.objects.get(pk=log_id)
    consumer = Consumer.objects.get(pk=consumer_id)
    inscricao = Inscricao.objects.get(pk=inscricao_id)

    evento = log.evento
    logger.info(f"⚙️  [CELERY WORKER] Task iniciada: evento='{evento}' | consumer={consumer.nome}")

    log.status = "processando"
    log.save()

    try:
        resultado = servico_fn(payload)

        log.status = "concluido"
        log.resultado = resultado
        log.save()
        logger.info(f"⚙️  [CELERY WORKER] Evento '{evento}' processado com sucesso!")

        _enviar_callback(consumer, inscricao, log, resultado)

    except Exception as e:
        logger.error(f"⚙️  [CELERY WORKER] Erro ao processar '{evento}': {e}")
        log.status = "erro"
        log.resultado = {"erro": str(e)}
        log.save()

        _enviar_callback(consumer, inscricao, log, {"erro": str(e)})


# ═══════════════════════════════════════════════
# CALLBACK — envia o resultado assinado com HMAC
# ═══════════════════════════════════════════════

def _enviar_callback(consumer, inscricao, log, resultado):
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
# LÓGICA DOS SERVIÇOS (funções puras)
# ═══════════════════════════════════════════════

def _servico_gerar_primos(payload):
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


def _servico_pokemon(payload):
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


def _servico_traduzir(payload):
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


def _servico_converter_pdf(payload):
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
