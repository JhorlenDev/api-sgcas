"""Cadastro institucional: coordenações e unidades da rede."""
import uuid

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.contas.permissoes import PodeConsultar, Supervisao
from apps.institucional.models import Coordenacao, Demanda, Servico, Unidade
from apps.institucional.serializers import (
    CoordenacaoSerializer,
    DemandaSerializer,
    NovaUnidadeSerializer,
    NovoServicoSerializer,
    ServicoSerializer,
    UnidadeSerializer,
)


@api_view(['GET', 'POST'])
@permission_classes([PodeConsultar])
def unidades(request):
    """
    Todas as unidades da rede.

    Não é filtrado por unidade de propósito: a lista alimenta seletores — para
    onde encaminhar um caso, em que unidade lotar alguém — e um operador
    precisa enxergar a rede inteira para escolher o destino. O escopo restringe
    os *dados* de cada unidade, não a existência delas.
    """
    if request.method == 'GET':
        consulta = Unidade.ativas.select_related('coordenacao__superior')
        return Response(UnidadeSerializer(consulta, many=True).data)

    if not Supervisao().has_permission(request, None):
        return Response({'detalhe': 'Sem permissão para cadastrar unidade'}, status=status.HTTP_403_FORBIDDEN)

    dados = NovaUnidadeSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dict(dados.validated_data)
    coordenacao_id = (d.pop('coordenacao_id', None) or '').strip() or None

    if coordenacao_id and not Coordenacao.ativas.filter(id=coordenacao_id).exists():
        return Response({'coordenacao_id': 'Coordenação não encontrada'}, status=status.HTTP_400_BAD_REQUEST)

    agora = timezone.now()
    unidade = Unidade(
        id=str(uuid.uuid4()),
        coordenacao_id=coordenacao_id,
        criada_em=agora,
        atualizada_em=agora,
        **d,
    )

    try:
        unidade.save(force_insert=True)
    except IntegrityError:
        return Response({'sigla': 'Já existe uma unidade com esta sigla'}, status=status.HTTP_400_BAD_REQUEST)

    return Response(UnidadeSerializer(unidade).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([PodeConsultar])
def coordenacoes(request):
    consulta = Coordenacao.ativas.select_related('superior')
    return Response(CoordenacaoSerializer(consulta, many=True).data)


@api_view(['GET'])
@permission_classes([PodeConsultar])
def demandas(request):
    """Catálogo do que a recepção pode classificar."""
    return Response(DemandaSerializer(Demanda.objects.filter(ativa=True), many=True).data)


@api_view(['GET', 'POST'])
@permission_classes([PodeConsultar])
def servicos(request):
    """
    Serviços ofertados. Sem filtro, devolve os da unidade de quem pergunta.

    Ver os serviços de outra unidade é permitido — é assim que a recepção
    descobre para onde encaminhar alguém. O que não se permite é *marcar* um
    serviço de outra unidade como atendimento da sua; essa checagem fica no
    registro da recepção, onde a decisão acontece.
    """
    if request.method == 'POST':
        if not Supervisao().has_permission(request, None):
            return Response({'detalhe': 'Sem permissão para cadastrar serviço'}, status=status.HTTP_403_FORBIDDEN)

        dados = NovoServicoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        d = dict(dados.validated_data)
        unidade_id = d.pop('unidade_id')
        demanda_id = (d.pop('demanda_id', None) or '').strip() or None

        if not Unidade.ativas.filter(id=unidade_id).exists():
            return Response({'unidade_id': 'Unidade não encontrada'}, status=status.HTTP_400_BAD_REQUEST)
        if demanda_id and not Demanda.objects.filter(id=demanda_id, ativa=True).exists():
            return Response({'demanda_id': 'Demanda não encontrada'}, status=status.HTTP_400_BAD_REQUEST)

        servico = Servico(id=str(uuid.uuid4()), unidade_id=unidade_id, demanda_id=demanda_id, **d)
        try:
            servico.save(force_insert=True)
        except IntegrityError:
            return Response({'nome': 'Esta unidade já possui um serviço com este nome'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ServicoSerializer(servico).data, status=status.HTTP_201_CREATED)

    consulta = Servico.objects.filter(ativo=True).select_related('unidade', 'demanda')

    unidade = request.query_params.get('unidade')
    if unidade == 'todas':
        pass
    elif unidade:
        consulta = consulta.filter(unidade_id=unidade)
    else:
        consulta = consulta.filter(unidade_id=request.user.unidade_id)

    return Response(ServicoSerializer(consulta, many=True).data)
