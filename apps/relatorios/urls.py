from django.urls import path

from apps.relatorios import api

urlpatterns = [
    path('dashboard', api.painel, name='painel'),
    path('acoes-itinerantes', api.acoes_itinerantes, name='relatorio-acoes'),
]
