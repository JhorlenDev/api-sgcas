from django.urls import path

from apps.contas import api, views

urlpatterns = [
    path('keycloak/login', views.login, name='login'),
    path('keycloak/callback', views.callback, name='callback'),
    path('access-request/resend', views.reenviar_solicitacao, name='reenviar-solicitacao'),
    path('logout', views.logout, name='logout'),
    path('me', api.eu, name='eu'),
]

pedidos_urlpatterns = [
    path('', api.pedidos_pendentes, name='pedidos-pendentes'),
    path('historico', api.historico_de_pedidos, name='pedidos-historico'),
    path('<str:pedido_id>/aprovar', api.aprovar, name='pedido-aprovar'),
    path('<str:pedido_id>/recusar', api.recusar, name='pedido-recusar'),
]

operadores_urlpatterns = [
    path('', api.listar_operadores, name='operadores'),
    path('<str:operador_id>', api.detalhar_operador, name='operador-detalhe'),
    path('<str:operador_id>/atualizar', api.atualizar_operador, name='operador-atualizar'),
    path('<str:operador_id>/perfil', api.alterar_perfil, name='operador-alterar-perfil'),
    path('<str:operador_id>/desligar', api.desligar_operador, name='operador-desligar'),
]
