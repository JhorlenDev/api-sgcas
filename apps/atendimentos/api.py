"""Recepção, fila e atendimento — o fluxo do balcão até a conclusão."""
from __future__ import annotations

import uuid

from django.db import models, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.atendimentos import historico
from apps.atendimentos.models import (
    AcaoItinerante,
    AtendimentoDeRecepcao,
    Caso,
    Encaminhamento,
    SenhaDaFila,
)
from apps.atendimentos.serializers import (
    AcaoItineranteSerializer,
    AtendimentoDeRecepcaoSerializer,
    CasoSerializer,
    ConclusaoSerializer,
    EncaminhamentoSerializer,
    NaoCompareceuSerializer,
    NovaAcaoItineranteSerializer,
    NovoEncaminhamentoSerializer,
    ObservacaoDoCasoSerializer,
    RegistroDeRecepcaoSerializer,
    SenhaSerializer,
)
from apps.cidadaos.models import Cidadao
from apps.institucional.models import Servico, Unidade
from apps.cidadaos.serializers import CidadaoSerializer, EntradaDoHistoricoSerializer
from apps.contas.escopo import pode_acessar_unidade, resolver_filtro
from apps.contas.permissoes import EquipeDeAtendimento, PodeConsultar, Recepcao


def _protocolo() -> str:
    agora = timezone.localtime(timezone.now())
    return f'{agora:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}'


def _prefixo_da_senha(prioridade: str) -> str:
    return {
        Caso.Prioridade.URGENTE: 'UR',
        Caso.Prioridade.ALTA: 'PR',
        Caso.Prioridade.NORMAL: 'NR',
        Caso.Prioridade.BAIXA: 'BX',
    }.get(prioridade, 'NR')


def _proxima_senha(unidade_id: str, prioridade: str) -> str:
    hoje = timezone.localtime(timezone.now()).date()
    prefixo = _prefixo_da_senha(prioridade)
    atendidos = SenhaDaFila.objects.filter(
        unidade_id=unidade_id,
        criado_em__date=hoje,
        senha__startswith=prefixo,
    ).count()
    return f'{prefixo}{atendidos + 1:03d}'


def _ordem_de_prioridade():
    return models.Case(
        models.When(prioridade=Caso.Prioridade.URGENTE, then=models.Value(0)),
        models.When(prioridade=Caso.Prioridade.ALTA, then=models.Value(1)),
        models.When(prioridade=Caso.Prioridade.NORMAL, then=models.Value(2)),
        models.When(prioridade=Caso.Prioridade.BAIXA, then=models.Value(3)),
        default=models.Value(4),
        output_field=models.IntegerField(),
    )


@api_view(['POST'])
@permission_classes([Recepcao])
@transaction.atomic
def registrar_recepcao(request):
    """
    Conclui o atendimento de balcão: encaminha para a fila ou finaliza aqui.

    Os dois caminhos geram registro. Finalizar sem registrar o motivo faria a
    pessoa refazer o mesmo pedido em outra unidade sem que ninguém soubesse do
    primeiro — que é justamente o problema que o histórico municipal resolve.
    """
    dados = RegistroDeRecepcaoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dados.validated_data

    cidadao = Cidadao.vigentes.filter(id=d['cidadao_id']).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    servico = (
        Servico.objects.filter(id=d['servico_id'], ativo=True)
        .select_related('unidade', 'demanda').first()
    )
    if servico is None:
        return Response({'servico_id': 'Serviço não encontrado'},
                        status=status.HTTP_400_BAD_REQUEST)

    operador = request.user
    if operador.unidade_id is None:
        return Response(
            {'detalhe': 'Seu usuário não tem unidade de lotação definida. Procure o administrador.'},
            status=status.HTTP_409_CONFLICT,
        )

    # Onde o atendimento vai acontecer: a própria unidade, ou outra quando a
    # recepção encaminha de imediato.
    destino_id = (d.get('unidade_destino_id') or '').strip() or operador.unidade_id

    # A recepção pode *ver* os serviços de outra unidade — é assim que descobre
    # para onde mandar alguém. O que não pode é marcar serviço alheio como
    # atendimento da própria unidade: o serviço tem de pertencer ao destino.
    if servico.unidade_id != destino_id:
        return Response(
            {'servico_id': f'O serviço "{servico.nome}" é ofertado pelo '
                           f'{servico.unidade.nome}. Selecione essa unidade como destino '
                           f'ou escolha um serviço da sua unidade.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    agora = timezone.now()
    caso = None
    senha = None

    if d['desfecho'] == AtendimentoDeRecepcao.Desfecho.ENCAMINHADO:
        prioridade = d.get('prioridade') or Caso.Prioridade.NORMAL
        caso = Caso(
            id=str(uuid.uuid4()), protocolo=_protocolo(),
            situacao=Caso.Situacao.EM_TRIAGEM, prioridade=prioridade,
            descricao=d.get('observacao') or servico.nome, cidadao=cidadao,
            unidade_id=destino_id, servico=servico,
            demanda_id=servico.demanda_id,
            acao_itinerante_id=d.get('acao_itinerante_id') or None,
            aberto_em=agora, criado_em=agora, atualizado_em=agora,
        )
        caso.save(force_insert=True)

        senha = SenhaDaFila(
            id=str(uuid.uuid4()), senha=_proxima_senha(destino_id, prioridade),
            cidadao=cidadao, unidade_id=destino_id,
            prioridade=prioridade, situacao=SenhaDaFila.Situacao.AGUARDANDO,
            servico=servico.nome,
            criado_em=agora, atualizado_em=agora,
        )
        senha.save(force_insert=True)

    AtendimentoDeRecepcao(
        id=str(uuid.uuid4()), cidadao=cidadao, unidade_id=operador.unidade_id,
        atendido_por=operador, demanda=servico.nome, desfecho=d['desfecho'],
        motivo=d.get('motivo') or None, caso=caso,
        acao_itinerante_id=d.get('acao_itinerante_id') or None,
    ).save(force_insert=True)

    return Response({
        'desfecho': d['desfecho'],
        'caso': CasoSerializer(caso).data if caso else None,
        'senha': SenhaSerializer(senha).data if senha else None,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([Recepcao])
def atendimentos_da_recepcao(request):
    """Últimos registros feitos pela recepção logada."""
    consulta = (
        AtendimentoDeRecepcao.objects.filter(atendido_por=request.user)
        .select_related('cidadao', 'unidade', 'atendido_por', 'caso', 'caso__unidade')[:20]
    )
    return Response(AtendimentoDeRecepcaoSerializer(consulta, many=True).data)


@api_view(['GET'])
@permission_classes([Recepcao])
def painel_da_recepcao(request):
    """Resumo do balcão no dia: volume, fila e últimos registros."""
    hoje = timezone.localtime(timezone.now()).date()
    unidade_id = request.user.unidade_id

    atendimentos_hoje = AtendimentoDeRecepcao.objects.filter(
        atendido_por=request.user, criado_em__date=hoje,
    )
    fila_da_unidade = SenhaDaFila.objects.filter(unidade_id=unidade_id) if unidade_id else SenhaDaFila.objects.none()
    ultimos = (
        AtendimentoDeRecepcao.objects.filter(atendido_por=request.user)
        .select_related('cidadao', 'unidade', 'atendido_por', 'caso', 'caso__unidade')[:8]
    )

    return Response({
        'atendimentos_hoje': atendimentos_hoje.count(),
        'finalizados_no_balcao': atendimentos_hoje.filter(
            desfecho=AtendimentoDeRecepcao.Desfecho.FINALIZADO
        ).count(),
        'encaminhados_para_fila': atendimentos_hoje.filter(
            desfecho=AtendimentoDeRecepcao.Desfecho.ENCAMINHADO
        ).count(),
        'aguardando_na_fila': fila_da_unidade.filter(
            situacao=SenhaDaFila.Situacao.AGUARDANDO
        ).count(),
        'em_atendimento': fila_da_unidade.filter(
            situacao=SenhaDaFila.Situacao.EM_ATENDIMENTO
        ).count(),
        'ultimos_atendimentos': AtendimentoDeRecepcaoSerializer(ultimos, many=True).data,
    })


@api_view(['GET'])
@permission_classes([Recepcao])
def fila(request):
    """Quem está aguardando na unidade. Estritamente operacional, por unidade."""
    escopo = resolver_filtro(request.user, request.query_params.get('unidade'))
    aguardando = (
        SenhaDaFila.objects.filter(situacao=SenhaDaFila.Situacao.AGUARDANDO, **escopo)
        .select_related('cidadao')
        .annotate(ordem_prioridade=_ordem_de_prioridade())
        .order_by('ordem_prioridade', 'criado_em')
    )
    return Response(SenhaSerializer(aguardando, many=True).data)


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def painel_da_fila(request):
    """Resumo da mesa do atendente."""
    hoje = timezone.localtime(timezone.now()).date()
    unidade_id = request.user.unidade_id
    fila_da_unidade = SenhaDaFila.objects.filter(unidade_id=unidade_id) if unidade_id else SenhaDaFila.objects.none()
    casos_da_unidade = Caso.vigentes.filter(unidade_id=unidade_id) if unidade_id else Caso.vigentes.none()

    ultimos_casos = (
        casos_da_unidade.filter(tecnico=request.user)
        .select_related('cidadao', 'unidade', 'tecnico', 'servico')
        .order_by('-atualizado_em')[:8]
    )

    return Response({
        'atendidos_hoje': fila_da_unidade.filter(
            atendido_por=request.user,
            situacao=SenhaDaFila.Situacao.ATENDIDO,
            finalizado_em__date=hoje,
        ).count(),
        'aguardando_na_fila': fila_da_unidade.filter(
            situacao=SenhaDaFila.Situacao.AGUARDANDO
        ).count(),
        'em_atendimento': fila_da_unidade.filter(
            situacao=SenhaDaFila.Situacao.EM_ATENDIMENTO
        ).count(),
        'finalizados_hoje': casos_da_unidade.filter(
            tecnico=request.user,
            fechado_em__date=hoje,
            situacao__in=[Caso.Situacao.CONCLUIDO, Caso.Situacao.ENCAMINHADO],
        ).count(),
        'casos_em_acompanhamento': casos_da_unidade.exclude(
            situacao__in=[Caso.Situacao.CONCLUIDO, Caso.Situacao.CANCELADO]
        ).count(),
        'ultimos_atendimentos': CasoSerializer(ultimos_casos, many=True).data,
    })


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def chamar_proximo(request):
    """
    Chama o próximo e devolve o atendimento já montado.

    É a mudança central do fluxo novo: antes, chamar apenas mudava o estado da
    senha, e quem atendia procurava a pessoa de novo em outra tela. Aqui volta
    tudo o que se precisa para atender — quem é, por que veio, o que já
    aconteceu — sem uma segunda busca.
    """
    operador = request.user
    if operador.unidade_id is None:
        return Response(
            {'detalhe': 'Seu usuário não tem unidade de lotação definida.'},
            status=status.HTTP_409_CONFLICT,
        )

    proxima = (
        SenhaDaFila.objects.select_for_update(skip_locked=True)
        .filter(situacao=SenhaDaFila.Situacao.AGUARDANDO, unidade_id=operador.unidade_id)
        .annotate(ordem_prioridade=_ordem_de_prioridade())
        .order_by('ordem_prioridade', 'criado_em')
        .first()
    )
    if proxima is None:
        return Response({'detalhe': 'Não há ninguém aguardando'}, status=status.HTTP_404_NOT_FOUND)

    agora = timezone.now()
    proxima.situacao = SenhaDaFila.Situacao.EM_ATENDIMENTO
    proxima.atendido_por = operador
    proxima.chamado_em = agora
    proxima.atualizado_em = agora
    proxima.save(update_fields=['situacao', 'atendido_por', 'chamado_em', 'atualizado_em'])

    cidadao = proxima.cidadao
    caso = (
        Caso.vigentes.filter(cidadao=cidadao, unidade_id=operador.unidade_id)
        .exclude(situacao__in=[Caso.Situacao.CONCLUIDO, Caso.Situacao.CANCELADO])
        .order_by('-aberto_em')
        .first()
    )
    if caso:
        caso.situacao = Caso.Situacao.EM_ATENDIMENTO
        caso.tecnico = operador
        caso.atualizado_em = agora
        caso.save(update_fields=['situacao', 'tecnico', 'atualizado_em'])

    return Response({
        'senha': SenhaSerializer(proxima).data,
        'cidadao': CidadaoSerializer(cidadao).data,
        'caso': CasoSerializer(caso).data if caso else None,
        'historico': EntradaDoHistoricoSerializer(
            historico.do_cidadao(cidadao, operador), many=True
        ).data,
    })


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def nao_compareceu(request, senha_id: str):
    """Marca a senha chamada como desistência/não comparecimento."""
    dados = NaoCompareceuSerializer(data=request.data)
    dados.is_valid(raise_exception=True)

    senha = SenhaDaFila.objects.select_for_update().filter(
        id=senha_id,
        atendido_por=request.user,
        situacao=SenhaDaFila.Situacao.EM_ATENDIMENTO,
    ).first()
    if senha is None:
        return Response(
            {'detalhe': 'Senha em atendimento não encontrada para este operador.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    agora = timezone.now()
    motivo = (dados.validated_data.get('motivo') or '').strip()
    texto = motivo or 'Cidadão chamado, mas não compareceu ao atendimento.'

    senha.situacao = SenhaDaFila.Situacao.DESISTIU
    senha.finalizado_em = agora
    senha.atualizado_em = agora
    senha.save(update_fields=['situacao', 'finalizado_em', 'atualizado_em'])

    caso = (
        Caso.vigentes.filter(
            cidadao=senha.cidadao,
            unidade=senha.unidade,
            tecnico=request.user,
            situacao=Caso.Situacao.EM_ATENDIMENTO,
        )
        .order_by('-aberto_em')
        .first()
    )
    if caso:
        marca = timezone.localtime(agora).strftime('%d/%m/%Y %H:%M')
        anotacao = f'[{marca}] {request.user.nome}: Não compareceu. {texto}'
        caso.descricao = f'{caso.descricao}\n\n{anotacao}' if caso.descricao else anotacao
        caso.situacao = Caso.Situacao.CANCELADO
        caso.fechado_em = agora
        caso.atualizado_em = agora
        caso.save(update_fields=['descricao', 'situacao', 'fechado_em', 'atualizado_em'])

    return Response({
        'senha': SenhaSerializer(senha).data,
        'caso': CasoSerializer(caso).data if caso else None,
    })


@api_view(['GET'])
@permission_classes([PodeConsultar])
def casos(request):
    escopo = resolver_filtro(request.user, request.query_params.get('unidade'))
    consulta = Caso.vigentes.filter(**escopo).select_related('cidadao', 'unidade', 'tecnico')

    situacao = request.query_params.get('situacao')
    if situacao:
        consulta = consulta.filter(situacao=situacao)

    cidadao = request.query_params.get('cidadao')
    if cidadao:
        consulta = consulta.filter(cidadao_id=cidadao)

    return Response(CasoSerializer(consulta[:100], many=True).data)


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def encaminhar(request, caso_id: str):
    """
    Encaminha o caso para outra unidade da rede ou para um serviço externo.

    Encaminhar para dentro da rede muda a unidade do caso: ele passa a aparecer
    para a equipe de destino. Sem isso o encaminhamento seria um bilhete que
    ninguém do outro lado leria — que é o problema que ele deveria resolver.
    """
    dados = NovoEncaminhamentoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dados.validated_data

    caso = Caso.vigentes.filter(id=caso_id).first()
    if caso is None:
        return Response({'detalhe': 'Caso não encontrado'}, status=status.HTTP_404_NOT_FOUND)
    if not pode_acessar_unidade(request.user, caso.unidade_id):
        return Response({'detalhe': 'Caso de outra unidade'}, status=status.HTTP_403_FORBIDDEN)

    destino_id = (d.get('unidade_destino_id') or '').strip() or None
    if destino_id and not Unidade.ativas.filter(id=destino_id).exists():
        return Response({'unidade_destino_id': 'Unidade não encontrada'},
                        status=status.HTTP_400_BAD_REQUEST)

    agora = timezone.now()
    destino = Unidade.ativas.filter(id=destino_id).first() if destino_id else None

    encaminhamento = Encaminhamento(
        id=str(uuid.uuid4()), caso=caso, encaminhado_por=request.user,
        unidade_destino=destino,
        destino_externo=destino.nome if destino else d['destino_externo'].strip(),
        motivo=d['motivo'], observacoes=d.get('observacoes') or None,
        criado_em=agora, atualizado_em=agora,
    )
    encaminhamento.save(force_insert=True)

    caso.situacao = Caso.Situacao.ENCAMINHADO
    campos = ['situacao', 'atualizado_em']
    if destino:
        caso.unidade = destino
        campos.append('unidade')
    caso.atualizado_em = agora
    caso.save(update_fields=campos)

    SenhaDaFila.objects.filter(
        cidadao_id=caso.cidadao_id,
        atendido_por=request.user,
        situacao=SenhaDaFila.Situacao.EM_ATENDIMENTO,
    ).update(situacao=SenhaDaFila.Situacao.ATENDIDO, finalizado_em=agora, atualizado_em=agora)

    return Response(EncaminhamentoSerializer(encaminhamento).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def anotar_caso(request, caso_id: str):
    """Registra observação de atendimento sem encerrar o caso."""
    dados = ObservacaoDoCasoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)

    caso = Caso.vigentes.filter(id=caso_id).first()
    if caso is None:
        return Response({'detalhe': 'Caso não encontrado'}, status=status.HTTP_404_NOT_FOUND)
    if not pode_acessar_unidade(request.user, caso.unidade_id):
        return Response({'detalhe': 'Caso de outra unidade'}, status=status.HTTP_403_FORBIDDEN)

    observacao = dados.validated_data['observacao'].strip()
    agora = timezone.now()
    marca = timezone.localtime(agora).strftime('%d/%m/%Y %H:%M')
    anotacao = f'[{marca}] {request.user.nome}: {observacao}'
    caso.descricao = f'{caso.descricao}\n\n{anotacao}' if caso.descricao else anotacao
    caso.tecnico = request.user
    caso.atualizado_em = agora
    caso.save(update_fields=['descricao', 'tecnico', 'atualizado_em'])

    return Response(CasoSerializer(caso).data)


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def concluir(request, caso_id: str):
    """
    Encerra o atendimento e libera a senha da fila.

    Fechar o caso sem fechar a senha deixaria a pessoa marcada como "em
    atendimento" para sempre, e a fila do dia seguinte começaria suja.
    """
    dados = ConclusaoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)

    caso = Caso.vigentes.filter(id=caso_id).first()
    if caso is None:
        return Response({'detalhe': 'Caso não encontrado'}, status=status.HTTP_404_NOT_FOUND)
    if not pode_acessar_unidade(request.user, caso.unidade_id):
        return Response({'detalhe': 'Caso de outra unidade'}, status=status.HTTP_403_FORBIDDEN)

    agora = timezone.now()
    caso.situacao = dados.validated_data['situacao']
    caso.descricao = dados.validated_data['relato']
    caso.tecnico = request.user
    caso.fechado_em = agora
    caso.atualizado_em = agora
    caso.save(update_fields=['situacao', 'descricao', 'tecnico', 'fechado_em', 'atualizado_em'])

    SenhaDaFila.objects.filter(
        cidadao_id=caso.cidadao_id, unidade_id=caso.unidade_id,
        situacao=SenhaDaFila.Situacao.EM_ATENDIMENTO,
    ).update(situacao=SenhaDaFila.Situacao.ATENDIDO, finalizado_em=agora, atualizado_em=agora)

    return Response(CasoSerializer(caso).data)


@api_view(['GET', 'POST'])
@permission_classes([EquipeDeAtendimento])
def acoes_itinerantes(request):
    """Ações em campo da unidade — listar e criar."""
    if request.method == 'GET':
        escopo = resolver_filtro(request.user, request.query_params.get('unidade'))
        consulta = AcaoItinerante.vigentes.filter(**escopo).select_related('unidade', 'responsavel')
        return Response(AcaoItineranteSerializer(consulta, many=True).data)

    if request.user.unidade_id is None:
        return Response({'detalhe': 'Seu usuário não tem unidade de lotação definida.'},
                        status=status.HTTP_409_CONFLICT)

    dados = NovaAcaoItineranteSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    agora = timezone.now()

    acao = AcaoItinerante(
        id=str(uuid.uuid4()), **dados.validated_data,
        responsavel=request.user, unidade_id=request.user.unidade_id,
        criada_em=agora, atualizada_em=agora,
    )
    acao.save(force_insert=True)
    return Response(AcaoItineranteSerializer(acao).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@permission_classes([EquipeDeAtendimento])
def concluir_acao_itinerante(request, acao_id):
    """Conclui uma ação itinerante registrando métricas finais."""
    try:
        acao = AcaoItinerante.vigentes.get(id=acao_id)
    except AcaoItinerante.DoesNotExist:
        return Response({'detalhe': 'Ação não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    if not pode_acessar_unidade(request.user, str(acao.unidade_id)):
        return Response({'detalhe': 'Sem permissão para alterar ação de outra unidade.'},
                        status=status.HTTP_403_FORBIDDEN)

    cidadaos = request.data.get('cidadaos_atendidos')
    participantes = request.data.get('participantes', 0)
    beneficios = request.data.get('beneficios_concedidos', 0)
    casos = request.data.get('casos_abertos', 0)

    if cidadaos is None:
        return Response({'detalhe': 'Informe o número de cidadãos atendidos.'},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        cidadaos = int(cidadaos)
        participantes = int(participantes)
        beneficios = int(beneficios)
        casos = int(casos)
    except (TypeError, ValueError):
        return Response({'detalhe': 'Valores inválidos.'},
                        status=status.HTTP_400_BAD_REQUEST)

    acao.cidadaos_atendidos = cidadaos
    acao.participantes = participantes
    acao.beneficios_concedidos = beneficios
    acao.casos_abertos = casos
    acao.concluida = True
    acao.atualizada_em = timezone.now()
    acao.save(update_fields=[
        'cidadaos_atendidos', 'participantes', 'beneficios_concedidos',
        'casos_abertos', 'concluida', 'atualizada_em',
    ])

    return Response(AcaoItineranteSerializer(acao).data)


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def balanco_acao_itinerante(request, acao_id):
    """Dashboard de uma ação com métricas e vínculos."""
    try:
        acao = AcaoItinerante.vigentes.select_related('unidade', 'responsavel').get(id=acao_id)
    except AcaoItinerante.DoesNotExist:
        return Response({'detalhe': 'Ação não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    if not pode_acessar_unidade(request.user, str(acao.unidade_id)):
        return Response({'detalhe': 'Sem permissão para acessar ação de outra unidade.'},
                        status=status.HTTP_403_FORBIDDEN)

    dados = AcaoItineranteSerializer(acao).data
    dados['balanco'] = acao.balanco()
    return Response(dados)


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def resumo_acoes_itinerantes(request):
    """Totais acumulados de todas as ações para o card de balanço."""
    escopo = resolver_filtro(request.user, request.query_params.get('unidade'))
    acoes = AcaoItinerante.vigentes.filter(**escopo)
    totais = acoes.aggregate(
        total_cidadaos=models.Sum('cidadaos_atendidos', default=0),
        total_casos=models.Sum('casos_abertos', default=0),
        total_beneficios=models.Sum('beneficios_concedidos', default=0),
    )
    total_acoes = acoes.count()
    total_concluidas = acoes.filter(concluida=True).count()

    return Response({
        'total_cidadaos': totais['total_cidadaos'],
        'total_casos': totais['total_casos'],
        'total_beneficios': totais['total_beneficios'],
        'total_acoes': total_acoes,
        'total_concluidas': total_concluidas,
    })


@api_view(['DELETE'])
@permission_classes([EquipeDeAtendimento])
def excluir_acao_itinerante(request, acao_id):
    """Exclui (soft delete) uma ação itinerante."""
    try:
        acao = AcaoItinerante.vigentes.get(id=acao_id)
    except AcaoItinerante.DoesNotExist:
        return Response({'detalhe': 'Ação não encontrada.'}, status=status.HTTP_404_NOT_FOUND)

    if not pode_acessar_unidade(request.user, str(acao.unidade_id)):
        return Response({'detalhe': 'Sem permissão para excluir ação de outra unidade.'},
                        status=status.HTTP_403_FORBIDDEN)

    acao.excluida_em = timezone.now()
    acao.save(update_fields=['excluida_em'])

    return Response(status=status.HTTP_204_NO_CONTENT)
