"""Endpoints do cadastro de cidadão e do histórico municipal."""
from rest_framework import status
from django.http import FileResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.atendimentos import historico
from apps.cidadaos.models import Cidadao
from apps.cidadaos.serializers import (
    CidadaoNaListaSerializer,
    CidadaoSerializer,
    EntradaDoHistoricoSerializer,
    NovoCidadaoSerializer,
)
import uuid

from django.db import transaction
from django.utils import timezone

from apps.cidadaos import anexos as arquivos
from apps.cidadaos import pre_cadastro
from apps.contas.permissoes import EquipeDeAtendimento, PodeConsultar, Recepcao, Supervisao

LIMITE_DA_BUSCA = 50


@api_view(['GET'])
@permission_classes([PodeConsultar])
def buscar(request):
    """
    Busca por nome ou por documento.

    O cadastro do cidadão é municipal: a pessoa circula entre as unidades, e
    quem a recebe precisa encontrá-la. O escopo por unidade vale para o que é
    operacional — fila e casos em andamento —, não para o cadastro.

    Por documento, a busca usa o índice cego: compara HMAC com HMAC, sem
    decifrar nada. Por nome, é comparação direta na coluna em texto.
    """
    termo = (request.query_params.get('busca') or '').strip()
    if not termo:
        recentes = Cidadao.vigentes.order_by('-atualizado_em')[:LIMITE_DA_BUSCA]
        return Response(CidadaoNaListaSerializer(recentes, many=True).data)

    por_documento = Cidadao.vigentes.por_documento(termo)
    if por_documento.exists():
        encontrados = por_documento[:LIMITE_DA_BUSCA]
    else:
        encontrados = Cidadao.vigentes.filter(nome__icontains=termo)[:LIMITE_DA_BUSCA]

    return Response(CidadaoNaListaSerializer(encontrados, many=True).data)


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def detalhar(request, cidadao_id: str):
    """O prontuário completo. Recepção não entra aqui — ver `permissoes`."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)
    return Response(CidadaoSerializer(cidadao).data)


@api_view(['GET'])
@permission_classes([PodeConsultar])
def historico_do_cidadao(request, cidadao_id: str):
    """
    Linha do tempo de todas as unidades — o que a recepção consulta antes de
    conceder de novo.

    A recepção alcança este endpoint, ao contrário do prontuário: ela precisa
    saber que houve atendimento, onde e o quê, para decidir. O nome de quem
    atendeu é filtrado dentro do serviço, conforme o papel de quem lê.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    entradas = historico.do_cidadao(cidadao, request.user)
    return Response({
        'cidadao': CidadaoNaListaSerializer(cidadao).data,
        'entradas': EntradaDoHistoricoSerializer(entradas, many=True).data,
    })


@api_view(['POST'])
@permission_classes([Recepcao])
@transaction.atomic
def cadastrar(request):
    """
    Cadastro completo do cidadão, feito no balcão.

    O pré-cadastro no Tefé Cidadão roda depois de gravar e nunca derruba o
    cadastro: se o SSO estiver fora do ar, a pessoa já foi atendida e o registro
    dela existe. O resultado volta na resposta para o atendente saber o que
    dizer — inclusive quando faltou dado para criar a conta.
    """
    dados = NovoCidadaoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dict(dados.validated_data)

    quer_acesso = d.pop('criar_acesso_tefe_cidadao', True)
    consentiu = d.pop('consentimento', False)
    acao_id = (d.pop('acao_itinerante_id', None) or '').strip() or None

    agora = timezone.now()
    cidadao = Cidadao(
        id=str(uuid.uuid4()), **d,
        acao_itinerante_id=acao_id,
        consentiu_tefe_cidadao_em=agora if consentiu else None,
        criado_em=agora, atualizado_em=agora,
    )
    cidadao.save(force_insert=True)

    acesso = None
    if quer_acesso:
        operador = request.user
        unidade = operador.unidade.nome_qualificado() if operador.unidade_id else None
        resultado = pre_cadastro.criar(cidadao, unidade, operador.email)
        acesso = {
            'situacao': resultado.situacao,
            'mensagem': resultado.mensagem,
            'faltando': list(resultado.faltando),
        }

    return Response(
        {**CidadaoSerializer(cidadao).data, 'tefeCidadao': acesso},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'POST'])
@permission_classes([EquipeDeAtendimento])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def anexos(request, cidadao_id: str):
    """Lista e envia anexos do prontuário."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    lista = cidadao.anexos or []

    if request.method == 'GET':
        # O caminho no disco não sai daqui: é detalhe interno, e nome de arquivo
        # carrega dado pessoal com frequência.
        return Response([
            {k: v for k, v in a.items() if k not in ('arquivo', 'miniatura')}
            for a in lista
        ])

    arquivo = request.FILES.get('file')
    if arquivo is None:
        return Response({'file': 'Envie um arquivo'}, status=status.HTTP_400_BAD_REQUEST)

    tipo_documento = request.data.get('tipo_documento') or 'outro'
    try:
        anexo = arquivos.guardar(cidadao_id, arquivo, tipo_documento)
    except arquivos.ErroDeAnexo as erro:
        return Response({'file': str(erro)}, status=status.HTTP_400_BAD_REQUEST)

    cidadao.anexos = [*lista, anexo]
    cidadao.atualizado_em = timezone.now()
    cidadao.save(update_fields=['anexos', 'atualizado_em'])

    return Response(
        {k: v for k, v in anexo.items() if k not in ('arquivo', 'miniatura')},
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def baixar_anexo(request, cidadao_id: str, anexo_id: str):
    """
    Entrega o arquivo. `?miniatura=true` devolve a versão reduzida.

    O acesso passa pela API em vez de servir a pasta diretamente: assim o
    download respeita a permissão e entra na trilha de auditoria — servir o
    diretório deixaria qualquer um com o link ler documento de cidadão.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    anexo = next((a for a in (cidadao.anexos or []) if a.get('id') == anexo_id), None)
    if anexo is None:
        return Response({'detalhe': 'Anexo não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    quer_miniatura = request.query_params.get('miniatura') == 'true'
    try:
        caminho = arquivos.caminho(cidadao_id, anexo, miniatura=quer_miniatura)
    except arquivos.ErroDeAnexo as erro:
        return Response({'detalhe': str(erro)}, status=status.HTTP_404_NOT_FOUND)

    mime = 'image/jpeg' if quer_miniatura else anexo.get('mime', 'application/octet-stream')
    return FileResponse(caminho.open('rb'), content_type=mime)


@api_view(['DELETE'])
@permission_classes([Supervisao])
def remover_anexo(request, cidadao_id: str, anexo_id: str):
    """Remover documento do prontuário é ato de supervisão, não de rotina."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    lista = cidadao.anexos or []
    anexo = next((a for a in lista if a.get('id') == anexo_id), None)
    if anexo is None:
        return Response({'detalhe': 'Anexo não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    arquivos.remover(cidadao_id, anexo)
    cidadao.anexos = [a for a in lista if a.get('id') != anexo_id]
    cidadao.atualizado_em = timezone.now()
    cidadao.save(update_fields=['anexos', 'atualizado_em'])

    return Response(status=status.HTTP_204_NO_CONTENT)
