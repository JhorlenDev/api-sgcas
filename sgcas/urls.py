"""Rotas do SGCAS. O prefixo /api espelha o backend anterior."""
from django.urls import include, path

from apps.atendimentos.urls import (
    acoes_urlpatterns,
    casos_urlpatterns,
    fila_urlpatterns,
    recepcao_urlpatterns,
)
from apps.contas.urls import operadores_urlpatterns, pedidos_urlpatterns

urlpatterns = [
    path('api/auth/', include('apps.contas.urls')),
    path('api/users/', include((operadores_urlpatterns, 'operadores'))),
    path('api/access-requests/', include((pedidos_urlpatterns, 'pedidos'))),
    path('api/citizens/', include('apps.cidadaos.urls')),
    path('api/institutional/', include('apps.institucional.urls')),
    path('api/reports/', include('apps.relatorios.urls')),
    path('api/auditoria/', include('apps.auditoria.urls')),
    path('api/reception/', include((recepcao_urlpatterns, 'recepcao'))),
    path('api/queues/', include((fila_urlpatterns, 'fila'))),
    path('api/cases/', include((casos_urlpatterns, 'casos'))),
    path('api/itinerant-actions/', include((acoes_urlpatterns, 'acoes'))),
]
