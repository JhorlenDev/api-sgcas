"""Consulta da trilha — restrita a quem administra."""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.auditoria.models import RegistroDeAuditoria
from apps.contas.permissoes import SomenteAdmin


@api_view(['GET'])
@permission_classes([SomenteAdmin])
def registros(request):
    consulta = RegistroDeAuditoria.objects.select_related('operador')

    if entidade := request.query_params.get('entidade'):
        consulta = consulta.filter(entidade=entidade)
    if alvo := request.query_params.get('registro'):
        consulta = consulta.filter(entidade_id=alvo)

    return Response([
        {
            'id': r.id,
            'quando': r.criado_em,
            'quem': r.operador.nome if r.operador_id else None,
            'acao': r.acao,
            'entidade': r.entidade,
            'registro': r.entidade_id,
            'dados': r.dados_depois,
            'ip': r.endereco_ip,
        }
        for r in consulta[:200]
    ])
