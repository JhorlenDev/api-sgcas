from django.urls import path

from apps.atendimentos import api

recepcao_urlpatterns = [
    path('atendimento', api.registrar_recepcao, name='recepcao-registrar'),
    path('atendimentos', api.atendimentos_da_recepcao, name='recepcao-atendimentos'),
    path('painel', api.painel_da_recepcao, name='recepcao-painel'),
]

fila_urlpatterns = [
    path('', api.fila, name='fila'),
    path('painel', api.painel_da_fila, name='fila-painel'),
    path('chamar-proximo', api.chamar_proximo, name='fila-chamar-proximo'),
    path('<str:senha_id>/nao-compareceu', api.nao_compareceu, name='fila-nao-compareceu'),
]

casos_urlpatterns = [
    path('', api.casos, name='casos'),
    path('<str:caso_id>/observacao', api.anotar_caso, name='caso-observacao'),
    path('<str:caso_id>/encaminhar', api.encaminhar, name='caso-encaminhar'),
    path('<str:caso_id>/concluir', api.concluir, name='caso-concluir'),
]

acoes_urlpatterns = [
    path('', api.acoes_itinerantes, name='acoes-itinerantes'),
    path('resumo', api.resumo_acoes_itinerantes, name='acoes-resumo'),
    path('<str:acao_id>/concluir', api.concluir_acao_itinerante, name='acao-concluir'),
    path('<str:acao_id>/balanco', api.balanco_acao_itinerante, name='acao-balanco'),
    path('<str:acao_id>/excluir', api.excluir_acao_itinerante, name='acao-excluir'),
]
