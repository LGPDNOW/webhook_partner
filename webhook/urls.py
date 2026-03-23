from django.urls import path
from . import views

urlpatterns = [
    # Rotas públicas
    path("register/", views.registrar, name="registrar"),
    path("events/", views.listar_eventos, name="listar_eventos"),

    # Rotas de serviços (autenticadas via HMAC)
    path("primos/", views.webhook_primos, name="webhook_primos"),
    path("pokemon/", views.webhook_pokemon, name="webhook_pokemon"),
    path("traduzir/", views.webhook_traduzir, name="webhook_traduzir"),
    path("converter-pdf/", views.webhook_converter_pdf, name="webhook_converter_pdf"),
]
