from django.urls import path

from apps.cidadaos import api

urlpatterns = [
    path('', api.buscar, name='cidadaos-buscar'),
    path('novo', api.cadastrar, name='cidadao-cadastrar'),
    path('<str:cidadao_id>', api.detalhar, name='cidadao-detalhe'),
    path('<str:cidadao_id>/prontuario', api.prontuario, name='cidadao-prontuario'),
    path('<str:cidadao_id>/beneficios', api.registrar_beneficio, name='cidadao-registrar-beneficio'),
    path('<str:cidadao_id>/encaminhamentos', api.registrar_encaminhamento, name='cidadao-registrar-encaminhamento'),
    path('<str:cidadao_id>/historico', api.historico_do_cidadao, name='cidadao-historico'),
    path('<str:cidadao_id>/anexos', api.anexos, name='cidadao-anexos'),
    path('<str:cidadao_id>/anexos/<str:anexo_id>', api.baixar_anexo, name='anexo-baixar'),
    path('<str:cidadao_id>/anexos/<str:anexo_id>/remover', api.remover_anexo, name='anexo-remover'),
    # LGPD (Art. 18)
    path('<str:cidadao_id>/exportar', api.exportar_dados, name='cidadao-exportar'),
    path('<str:cidadao_id>/dados-pessoais', api.eliminar_dados_pessoais, name='cidadao-eliminar-dados'),
    path('<str:cidadao_id>/consentimento-imagem', api.revogar_consentimento_imagem, name='cidadao-revogar-imagem'),
    path('<str:cidadao_id>/consentimento-imagem/registrar', api.registrar_consentimento_imagem, name='cidadao-registrar-imagem'),
]
