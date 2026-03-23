import secrets

from django.db import models


class Consumer(models.Model):
    """
    Representa um sistema externo autorizado a consumir o webhook.

    Cada consumer recebe:
      - api_key    → identifica quem é (enviada no header)
      - secret_key → usada para assinar o payload via HMAC (nunca exposta)

    As inscrições em eventos ficam no model Inscricao (1 por evento,
    cada uma com seu próprio callback_url).
    """

    nome = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    api_key = models.CharField(max_length=64, unique=True, editable=False)
    secret_key = models.CharField(max_length=64, editable=False)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Consumer"
        verbose_name_plural = "Consumers"

    def save(self, *args, **kwargs):
        if not self.pk:
            self.api_key = secrets.token_hex(16)
            self.secret_key = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nome} ({self.email})"


class Inscricao(models.Model):
    """
    Vincula um consumer a um evento específico com seu callback_url.

    Cada evento tem sua própria URL de callback — porque a resposta
    de cada serviço é diferente e pode precisar de tratamento distinto.
    """

    EVENTOS = [
        ("gerar_primos", "Gerador de Números Primos"),
        ("pokemon", "Consulta PokéAPI"),
        ("traduzir", "Fun Translations (Yoda, Pirata, Minion)"),
        ("converter_pdf", "Converter PDF → Markdown (Docling)"),
    ]

    consumer = models.ForeignKey(Consumer, on_delete=models.CASCADE, related_name="inscricoes")
    evento = models.CharField(max_length=50, choices=EVENTOS)
    callback_url = models.URLField(
        help_text="URL onde o resultado DESTE evento será enviado"
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("consumer", "evento")
        ordering = ["evento"]
        verbose_name = "Inscrição"
        verbose_name_plural = "Inscrições"

    def __str__(self):
        return f"{self.consumer.nome} → {self.get_evento_display()} → {self.callback_url}"


class WebhookLog(models.Model):
    """Registra cada chamada ao webhook."""

    STATUS_CHOICES = [
        ("recebido", "Recebido"),
        ("processando", "Processando"),
        ("concluido", "Concluído"),
        ("erro", "Erro"),
        ("callback_enviado", "Callback Enviado"),
        ("callback_falhou", "Callback Falhou"),
    ]

    consumer = models.ForeignKey(
        Consumer, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="logs",
    )
    inscricao = models.ForeignKey(
        Inscricao, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="logs",
    )
    evento = models.CharField(max_length=100)
    payload = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="recebido")
    resultado = models.JSONField(null=True, blank=True)
    recebido_em = models.DateTimeField(auto_now_add=True)
    assinatura_valida = models.BooleanField(default=True)

    class Meta:
        ordering = ["-recebido_em"]
        verbose_name = "Log de Webhook"
        verbose_name_plural = "Logs de Webhook"

    def __str__(self):
        origem = self.consumer.nome if self.consumer else "desconhecido"
        return f"[{origem}] {self.evento} ({self.status}) — {self.recebido_em:%d/%m/%Y %H:%M:%S}"
