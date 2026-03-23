from django.contrib import admin
from .models import Consumer, Inscricao, WebhookLog


class InscricaoInline(admin.TabularInline):
    """Mostra as inscrições dentro do Consumer."""
    model = Inscricao
    extra = 0
    readonly_fields = ("criado_em",)


@admin.register(Consumer)
class ConsumerAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "api_key", "ativo", "total_inscricoes", "criado_em")
    list_filter = ("ativo",)
    search_fields = ("nome", "email")
    readonly_fields = ("api_key", "secret_key", "criado_em")
    inlines = [InscricaoInline]

    fieldsets = (
        ("Identificação", {
            "fields": ("nome", "email", "ativo")
        }),
        ("Credenciais (geradas automaticamente)", {
            "fields": ("api_key", "secret_key"),
            "description": (
                "A api_key identifica o consumer nas requisições. "
                "A secret_key é usada para assinar o payload via HMAC."
            ),
        }),
        ("Auditoria", {
            "fields": ("criado_em",)
        }),
    )

    def total_inscricoes(self, obj):
        return obj.inscricoes.filter(ativo=True).count()
    total_inscricoes.short_description = "Inscrições ativas"


@admin.register(Inscricao)
class InscricaoAdmin(admin.ModelAdmin):
    list_display = ("consumer", "evento", "callback_url", "ativo", "criado_em")
    list_filter = ("evento", "ativo")
    search_fields = ("consumer__nome", "evento")


@admin.register(WebhookLog)
class WebhookLogAdmin(admin.ModelAdmin):
    list_display = ("consumer", "evento", "status", "assinatura_valida", "recebido_em")
    list_filter = ("evento", "status", "assinatura_valida", "consumer")
    search_fields = ("evento", "consumer__nome")
    readonly_fields = ("consumer", "inscricao", "evento", "payload", "status", "resultado", "recebido_em", "assinatura_valida")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
