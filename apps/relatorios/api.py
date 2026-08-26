"""Indicadores do painel e relatórios de ações itinerantes."""
from django.db.models import Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.atendimentos.models import AcaoItinerante, BeneficioEventual, Caso, SenhaDaFila
from apps.cidadaos.models import Cidadao
from apps.contas.escopo import resolver_filtro
from apps.contas.permissoes import PodeConsultar, Supervisao


@api_view(['GET'])
@permission_classes([PodeConsultar])
def painel(request):
    """
    Números da primeira tela.

    Casos e fila são operacionais: respeitam o escopo por unidade, então cada
    equipe vê o próprio movimento. Cidadãos, não — o cadastro é municipal, e o
    total da rede é o número que faz sentido ali.
    """
    escopo = resolver_filtro(request.user, request.query_params.get('unidade'))
    casos = Caso.vigentes.filter(**escopo)

    por_situacao = dict(
        casos.values_list('situacao').annotate(total=Count('id')).values_list('situacao', 'total')
    )

    return Response({
        'casosTotal': casos.count(),
        'casosEmTriagem': por_situacao.get(Caso.Situacao.EM_TRIAGEM, 0),
        'casosEmAtendimento': por_situacao.get(Caso.Situacao.EM_ATENDIMENTO, 0),
        'casosConcluidos': por_situacao.get(Caso.Situacao.CONCLUIDO, 0),
        'casosEncaminhados': por_situacao.get(Caso.Situacao.ENCAMINHADO, 0),
        'filaAguardando': SenhaDaFila.objects.filter(
            situacao=SenhaDaFila.Situacao.AGUARDANDO, **escopo
        ).count(),
        'cidadaosTotal': Cidadao.vigentes.count(),
        'beneficiosNoPeriodo': BeneficioEventual.vigentes.filter(**escopo).count(),
    })


@api_view(['GET'])
@permission_classes([Supervisao])
def acoes_itinerantes(request):
    """
    Balanço das ações em campo — o relatório do mutirão.

    Os números vêm da contagem dos vínculos, não de um total digitado: é o que
    permite auditar de volta até o registro individual, que é o que prestação
    de contas exige.
    """
    acoes = AcaoItinerante.vigentes.select_related('unidade', 'responsavel')
    return Response([
        {
            'id': acao.id,
            'titulo': acao.titulo,
            'local': acao.local,
            'data': acao.data,
            'unidade': acao.unidade.nome,
            'responsavel': acao.responsavel.nome,
            **acao.balanco(),
        }
        for acao in acoes
    ])
