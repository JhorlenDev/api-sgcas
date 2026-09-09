"""Consulta da trilha — restrita a quem administra."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.auditoria.models import RegistroDeAuditoria
from apps.auditoria.serializers import RegistroDeAuditoriaSerializer
from apps.comum.consultas import filtrar_iguais, filtrar_periodo, ordenar, paginar
from apps.contas.permissoes import SomenteAdmin

ORDENACOES = {
    '-criado_em': ('-criado_em',),
    'criado_em': ('criado_em',),
}


@api_view(['GET'])
@permission_classes([SomenteAdmin])
def registros(request):
    """
    A trilha, paginada e filtrável.

    Antes a consulta devolvia os 200 mais recentes e parava aí. Numa base com
    centenas de milhares de registros, isso responde "o que aconteceu na última
    hora" — e nunca "quem consultou os dados desta pessoa", que é a pergunta
    para a qual a trilha existe. Daí os filtros por operador, por registro
    alvo e por período.
    """
    consulta = RegistroDeAuditoria.objects.select_related('operador')

    consulta = filtrar_iguais(consulta, request, {
        'entidade': 'entidade',
        'registro': 'entidade_id',
        'acao': 'acao',
        'operador': 'operador_id',
    })
    consulta = filtrar_periodo(consulta, request, 'criado_em')
    consulta = ordenar(consulta, request, ORDENACOES, '-criado_em')

    return Response(paginar(consulta, request, RegistroDeAuditoriaSerializer, padrao=50))
