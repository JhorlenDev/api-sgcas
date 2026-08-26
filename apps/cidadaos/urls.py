from django.urls import path

from apps.cidadaos import api

urlpatterns = [
    path('', api.buscar, name='cidadaos-buscar'),
    path('novo', api.cadastrar, name='cidadao-cadastrar'),
    path('<str:cidadao_id>', api.detalhar, name='cidadao-detalhe'),
    path('<str:cidadao_id>/historico', api.historico_do_cidadao, name='cidadao-historico'),
    path('<str:cidadao_id>/anexos', api.anexos, name='cidadao-anexos'),
    path('<str:cidadao_id>/anexos/<str:anexo_id>', api.baixar_anexo, name='anexo-baixar'),
    path('<str:cidadao_id>/anexos/<str:anexo_id>/remover', api.remover_anexo, name='anexo-remover'),
]
