"""Endpoints do cadastro de cidadão e do histórico municipal.

Inclui endpoints LGPD (Art. 18):
- Exportação de dados pessoais (PDF)
- Eliminação de dados pessoais (soft delete + anonimização)
- Revogação de consentimento de uso de imagem
"""
import json

from django.http import HttpResponse
from rest_framework import status
from django.http import FileResponse
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.atendimentos.models import (
    AtendimentoDeRecepcao,
    BeneficioEventual,
    Caso,
    Encaminhamento,
    SenhaDaFila,
)
from apps.atendimentos.serializers import (
    AtendimentoDeRecepcaoSerializer,
    BeneficioEventualSerializer,
    CasoSerializer,
    EncaminhamentoSerializer,
    NovoBeneficioEventualSerializer,
    NovoEncaminhamentoDoCidadaoSerializer,
    SenhaSerializer,
)
from apps.atendimentos import historico
from apps.auditoria.redacao import redigir
from apps.cidadaos.models import Cidadao
from apps.cidadaos.serializers import (
    CidadaoNaListaSerializer,
    CidadaoSerializer,
    EntradaDoHistoricoSerializer,
    NovoCidadaoSerializer,
)
import uuid

from django.db import transaction
from django.utils.html import escape
from django.utils import timezone

from apps.cidadaos import anexos as arquivos
from apps.cidadaos import pre_cadastro
from apps.contas.permissoes import EquipeDeAtendimento, PodeConsultar, Recepcao, Supervisao
from apps.institucional.models import Unidade

LIMITE_DA_BUSCA = 50


def _registrar_auditoria(request, acao, entidade, entidade_id, dados_novos=None, dados_antes=None):
    """Registra ação LGPD na trilha de auditoria."""
    from apps.auditoria.models import RegistroDeAuditoria

    operador = getattr(request, 'user', None)
    RegistroDeAuditoria(
        id=str(uuid.uuid4()),
        operador=operador if getattr(operador, 'is_authenticated', False) else None,
        acao=acao,
        entidade=entidade,
        entidade_id=entidade_id,
        dados_antes=redigir(dados_antes) if dados_antes else None,
        dados_depois=redigir(dados_novos) if dados_novos else None,
        endereco_ip=_ip(request),
        navegador=(request.META.get('HTTP_USER_AGENT') or '')[:400] or None,
        criado_em=timezone.now(),
    ).save(force_insert=True)


def _ip(request):
    encaminhado = request.META.get('HTTP_X_FORWARDED_FOR')
    if encaminhado:
        return encaminhado.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _protocolo_do_prontuario():
    agora = timezone.localtime()
    return f'PR-{agora:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}'


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


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def prontuario(request, cidadao_id: str):
    """Resumo completo do prontuário para a tela de detalhe do cidadão."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    casos = (
        Caso.vigentes.filter(cidadao=cidadao)
        .select_related('cidadao', 'unidade', 'tecnico', 'servico')
        .order_by('-aberto_em')[:50]
    )
    atendimentos = (
        AtendimentoDeRecepcao.objects.filter(cidadao=cidadao)
        .select_related('cidadao', 'unidade', 'atendido_por', 'caso', 'caso__unidade')
        .order_by('-criado_em')[:50]
    )
    beneficios = (
        BeneficioEventual.vigentes.filter(cidadao=cidadao)
        .select_related('cidadao', 'unidade', 'registrado_por')
        .order_by('-criado_em')[:50]
    )
    encaminhamentos = (
        Encaminhamento.objects.filter(caso__cidadao=cidadao)
        .select_related('caso', 'unidade_destino', 'encaminhado_por')
        .order_by('-criado_em')[:50]
    )
    senhas = (
        SenhaDaFila.objects.filter(cidadao=cidadao)
        .select_related('cidadao', 'unidade', 'atendido_por')
        .order_by('-criado_em')[:50]
    )
    entradas = historico.do_cidadao(cidadao, request.user)

    anexos = [
        {k: v for k, v in anexo.items() if k not in ('arquivo', 'miniatura')}
        for anexo in (cidadao.anexos or [])
    ]

    return Response({
        'cidadao': CidadaoSerializer(cidadao).data,
        'historico': EntradaDoHistoricoSerializer(entradas, many=True).data,
        'casos': CasoSerializer(casos, many=True).data,
        'atendimentos_recepcao': AtendimentoDeRecepcaoSerializer(atendimentos, many=True).data,
        'beneficios_eventuais': BeneficioEventualSerializer(beneficios, many=True).data,
        'encaminhamentos': EncaminhamentoSerializer(encaminhamentos, many=True).data,
        'senhas': SenhaSerializer(senhas, many=True).data,
        'anexos': anexos,
        'membros_da_familia': cidadao.membros_da_familia or [],
        'socioeconomico': cidadao.socioeconomico or {},
        'documentos': cidadao.documentos or {},
        'endereco_detalhado': cidadao.endereco_detalhado or {},
    })


def _linha_html(rotulo, valor):
    if valor in (None, ''):
        return ''
    return f'<div class="linha"><span>{escape(rotulo)}</span><strong>{escape(str(valor))}</strong></div>'


def _data_curta(valor):
    if not valor:
        return ''
    return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M') if hasattr(valor, 'hour') else valor.strftime('%d/%m/%Y')


def _rotulo(valor, escolhas):
    return dict(escolhas).get(valor, valor)


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def imprimir_prontuario(request, cidadao_id: str):
    """Gera uma versão HTML limpa para impressão/salvar em PDF pelo navegador."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    casos = (
        Caso.vigentes.filter(cidadao=cidadao)
        .select_related('unidade', 'tecnico', 'servico')
        .order_by('-aberto_em')[:20]
    )
    atendimentos = (
        AtendimentoDeRecepcao.objects.filter(cidadao=cidadao)
        .select_related('unidade', 'atendido_por', 'caso')
        .order_by('-criado_em')[:20]
    )
    beneficios = (
        BeneficioEventual.vigentes.filter(cidadao=cidadao)
        .select_related('unidade', 'registrado_por')
        .order_by('-criado_em')[:20]
    )
    encaminhamentos = (
        Encaminhamento.objects.filter(caso__cidadao=cidadao)
        .select_related('unidade_destino', 'encaminhado_por')
        .order_by('-criado_em')[:20]
    )

    def item(titulo, detalhe=''):
        return f'<li><strong>{escape(titulo)}</strong>{f"<p>{escape(detalhe)}</p>" if detalhe else ""}</li>'

    casos_html = ''.join(item(
        f'{caso.protocolo} · {_rotulo(caso.situacao, Caso.Situacao.choices)}',
        ' · '.join(filter(None, [
            caso.servico.nome if caso.servico_id else 'Serviço não informado',
            caso.unidade.nome if caso.unidade_id else '',
            _data_curta(caso.aberto_em),
            caso.descricao or '',
        ])),
    ) for caso in casos) or '<li class="vazio">Sem casos registrados.</li>'

    atendimentos_html = ''.join(item(
        f'{_rotulo(atendimento.desfecho, AtendimentoDeRecepcao.Desfecho.choices)} · {atendimento.demanda}',
        ' · '.join(filter(None, [
            atendimento.unidade.nome if atendimento.unidade_id else '',
            atendimento.atendido_por.nome if atendimento.atendido_por_id else '',
            _data_curta(atendimento.criado_em),
            atendimento.motivo or '',
        ])),
    ) for atendimento in atendimentos) or '<li class="vazio">Sem atendimentos registrados.</li>'

    beneficios_html = ''.join(item(
        f'{beneficio.get_tipo_display() if beneficio.tipo in dict(BeneficioEventual.Tipo.choices) else beneficio.tipo} · {beneficio.nome_da_pessoa}',
        ' · '.join(filter(None, [
            beneficio.unidade.nome if beneficio.unidade_id else '',
            beneficio.registrado_por.nome if beneficio.registrado_por_id else '',
            _data_curta(beneficio.criado_em),
            beneficio.descricao or '',
        ])),
    ) for beneficio in beneficios) or '<li class="vazio">Sem benefícios registrados.</li>'

    encaminhamentos_html = ''.join(item(
        f'{encaminhamento.unidade_destino.nome if encaminhamento.unidade_destino_id else encaminhamento.destino_externo} · {_rotulo(encaminhamento.situacao, Encaminhamento.Situacao.choices)}',
        ' · '.join(filter(None, [
            encaminhamento.encaminhado_por.nome if encaminhamento.encaminhado_por_id else '',
            _data_curta(encaminhamento.criado_em),
            encaminhamento.motivo,
            encaminhamento.observacoes or '',
        ])),
    ) for encaminhamento in encaminhamentos) or '<li class="vazio">Sem encaminhamentos registrados.</li>'

    socio = cidadao.socioeconomico or {}
    familia = cidadao.membros_da_familia or []
    familia_html = ''.join(item(
        str(membro.get('nome_membro') or membro.get('nome') or 'Membro familiar'),
        ' · '.join(filter(None, [
            str(membro.get('parentesco') or ''),
            f"CPF: {membro.get('cpf_membro')}" if membro.get('cpf_membro') else '',
            f"Nascimento: {membro.get('data_nascimento')}" if membro.get('data_nascimento') else '',
        ])),
    ) for membro in familia if isinstance(membro, dict)) or '<li class="vazio">Sem composição familiar cadastrada.</li>'

    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <title>Prontuário - {escape(cidadao.nome)}</title>
  <style>
    :root {{ color: #182230; font-family: Arial, Helvetica, sans-serif; }}
    body {{ margin: 0; background: #f4f7fb; }}
    main {{ max-width: 920px; margin: 0 auto; padding: 32px; background: white; min-height: 100vh; }}
    header {{ border-bottom: 3px solid #1d6fd7; padding-bottom: 18px; margin-bottom: 22px; }}
    .marca {{ color: #1d6fd7; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; font-size: 12px; }}
    h1 {{ margin: 8px 0 4px; font-size: 28px; }}
    h2 {{ margin: 22px 0 10px; font-size: 16px; color: #1d6fd7; border-bottom: 1px solid #d8e2ef; padding-bottom: 6px; }}
    .sub {{ color: #5d6b7c; font-size: 13px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }}
    .linha {{ background: #f7f9fc; border: 1px solid #e6edf5; border-radius: 10px; padding: 9px 11px; }}
    .linha span {{ display: block; color: #667085; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }}
    .linha strong {{ display: block; margin-top: 3px; font-size: 13px; font-weight: 700; }}
    ul {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }}
    li {{ border: 1px solid #e6edf5; border-radius: 10px; padding: 10px 12px; }}
    li strong {{ font-size: 13px; }}
    li p {{ margin: 5px 0 0; color: #536171; font-size: 12px; line-height: 1.45; }}
    .vazio {{ color: #667085; font-size: 13px; }}
    footer {{ margin-top: 28px; color: #667085; font-size: 11px; border-top: 1px solid #d8e2ef; padding-top: 12px; }}
    @media print {{ body {{ background: white; }} main {{ padding: 0; }} .no-print {{ display: none; }} }}
  </style>
</head>
<body>
  <main>
    <button class="no-print" onclick="window.print()" style="float:right;border:0;background:#1d6fd7;color:white;border-radius:999px;padding:10px 16px;font-weight:700;cursor:pointer">Imprimir / salvar PDF</button>
    <header>
      <div class="marca">SGCAS · Prontuário do cidadão</div>
      <h1>{escape(cidadao.nome)}</h1>
      <div class="sub">Gerado em {_data_curta(timezone.now())} por {escape(getattr(request.user, 'nome', '') or getattr(request.user, 'email', 'operador'))}</div>
    </header>

    <h2>Dados pessoais</h2>
    <section class="grid">
      {_linha_html('CPF', cidadao.cpf)}
      {_linha_html('NIS', cidadao.nis)}
      {_linha_html('RG', cidadao.rg)}
      {_linha_html('Nascimento', cidadao.nascimento.strftime('%d/%m/%Y') if cidadao.nascimento else '')}
      {_linha_html('Telefone', cidadao.telefone)}
      {_linha_html('E-mail', cidadao.email)}
      {_linha_html('Endereço', ', '.join(filter(None, [cidadao.endereco, cidadao.bairro, cidadao.cidade, cidadao.uf])))}
      {_linha_html('CEP', cidadao.cep)}
    </section>

    <h2>Socioeconômico</h2>
    <section class="grid">
      {_linha_html('Renda total', socio.get('renda_total'))}
      {_linha_html('Pessoas na residência', socio.get('quantidade_pessoas_residencia'))}
      {_linha_html('Recebe benefício', 'Sim' if socio.get('recebe_beneficio') else 'Não' if 'recebe_beneficio' in socio else '')}
      {_linha_html('Observações', socio.get('observacoes_gerais'))}
    </section>

    <h2>Composição familiar</h2>
    <ul>{familia_html}</ul>

    <h2>Casos e acompanhamentos</h2>
    <ul>{casos_html}</ul>

    <h2>Atendimentos de recepção</h2>
    <ul>{atendimentos_html}</ul>

    <h2>Benefícios eventuais</h2>
    <ul>{beneficios_html}</ul>

    <h2>Encaminhamentos</h2>
    <ul>{encaminhamentos_html}</ul>

    <footer>Documento gerado pelo SGCAS para uso administrativo. Dados pessoais devem ser tratados conforme a LGPD.</footer>
  </main>
</body>
</html>"""

    _registrar_auditoria(
        request,
        'EXPORT',
        'cidadao',
        cidadao.id,
        dados_novos={'acao': 'impressao_prontuario'},
    )

    return HttpResponse(html, content_type='text/html; charset=utf-8')


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def registrar_beneficio(request, cidadao_id: str):
    """Registra benefício eventual diretamente no prontuário do cidadão."""
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    dados = NovoBeneficioEventualSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dados.validated_data
    agora = timezone.now()

    beneficio = BeneficioEventual(
        id=str(uuid.uuid4()),
        cidadao=cidadao,
        nome_da_pessoa=(d.get('nome_da_pessoa') or cidadao.nome).strip(),
        tipo=d['tipo'],
        tipo_outro=(d.get('tipo_outro') or '').strip() or None,
        descricao=(d.get('descricao') or '').strip() or None,
        registrado_por=request.user,
        unidade=getattr(request.user, 'unidade', None),
        criado_em=agora,
        atualizado_em=agora,
    )
    beneficio.save(force_insert=True)

    _registrar_auditoria(
        request,
        'CRIAR',
        'BeneficioEventual',
        beneficio.id,
        dados_novos=BeneficioEventualSerializer(beneficio).data,
    )

    return Response(BeneficioEventualSerializer(beneficio).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
@transaction.atomic
def registrar_encaminhamento(request, cidadao_id: str):
    """
    Registra encaminhamento pelo prontuário.

    Se o operador não informar um caso existente, o sistema abre um caso simples
    para manter rastreabilidade do encaminhamento no acompanhamento.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    operador = request.user
    if not getattr(operador, 'unidade_id', None):
        return Response(
            {'detalhe': 'O operador precisa estar vinculado a uma unidade para registrar encaminhamento.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    dados = NovoEncaminhamentoDoCidadaoSerializer(data=request.data)
    dados.is_valid(raise_exception=True)
    d = dados.validated_data

    unidade_destino = None
    unidade_destino_id = (d.get('unidade_destino_id') or '').strip()
    if unidade_destino_id:
        unidade_destino = Unidade.ativas.filter(id=unidade_destino_id).first()
        if unidade_destino is None:
            return Response({'unidade_destino_id': 'Unidade de destino não encontrada.'}, status=status.HTTP_400_BAD_REQUEST)

    agora = timezone.now()
    caso_id = (d.get('caso_id') or '').strip()
    caso = None
    if caso_id:
        caso = Caso.vigentes.filter(id=caso_id, cidadao=cidadao).first()
        if caso is None:
            return Response({'caso_id': 'Caso não encontrado para este cidadão.'}, status=status.HTTP_400_BAD_REQUEST)
    else:
        caso = Caso(
            id=str(uuid.uuid4()),
            protocolo=_protocolo_do_prontuario(),
            situacao=Caso.Situacao.ENCAMINHADO,
            prioridade=Caso.Prioridade.NORMAL,
            descricao=(d.get('motivo') or '').strip(),
            cidadao=cidadao,
            unidade=operador.unidade,
            aberto_em=agora,
            fechado_em=agora,
            ativo=True,
            criado_em=agora,
            atualizado_em=agora,
        )
        caso.save(force_insert=True)

    destino_externo = (d.get('destino_externo') or '').strip()
    encaminhamento = Encaminhamento(
        id=str(uuid.uuid4()),
        caso=caso,
        encaminhado_por=operador,
        unidade_destino=unidade_destino,
        destino_externo=destino_externo or (unidade_destino.nome if unidade_destino else ''),
        motivo=(d.get('motivo') or '').strip(),
        observacoes=(d.get('observacoes') or '').strip() or None,
        situacao=Encaminhamento.Situacao.PENDENTE,
        criado_em=agora,
        atualizado_em=agora,
    )
    encaminhamento.save(force_insert=True)

    if unidade_destino is not None:
        caso.unidade = unidade_destino
        caso.situacao = Caso.Situacao.ENCAMINHADO
        caso.atualizado_em = agora
        caso.save(update_fields=['unidade', 'situacao', 'atualizado_em'])

    _registrar_auditoria(
        request,
        'CRIAR',
        'Encaminhamento',
        encaminhamento.id,
        dados_novos=EncaminhamentoSerializer(encaminhamento).data,
    )

    return Response(EncaminhamentoSerializer(encaminhamento).data, status=status.HTTP_201_CREATED)


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


# ─── Endpoints LGPD (Art. 18 da Lei 13.709/2018) ───────────────────────


@api_view(['GET'])
@permission_classes([EquipeDeAtendimento])
def exportar_dados(request, cidadao_id: str):
    """
    Exporta dados pessoais do cidadão em JSON (Art. 18, V — portabilidade).

    O cidadão tem direito de receber seus dados em formato estruturado e
    legível. O endpoint devolve JSON com todos os campos pessoais, incluindo
    histórico de consentimentos.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    dados = {
        'id': cidadao.id,
        'nome': cidadao.nome,
        'cpf': cidadao.cpf,
        'nis': cidadao.nis,
        'rg': cidadao.rg,
        'email': cidadao.email,
        'telefone': cidadao.telefone,
        'endereco': cidadao.endereco,
        'nascimento': cidadao.nascimento.isoformat() if cidadao.nascimento else None,
        'sexo': cidadao.sexo,
        'naturalidade': cidadao.naturalidade,
        'escolaridade': cidadao.escolaridade,
        'identidade_de_genero': cidadao.identidade_de_genero,
        'raca': cidadao.raca,
        'tem_deficiencia': cidadao.tem_deficiencia,
        'estado_civil': cidadao.estado_civil,
        'bairro': cidadao.bairro,
        'cidade': cidadao.cidade,
        'uf': cidadao.uf,
        'cep': cidadao.cep,
        'documentos': cidadao.documentos,
        'endereco_detalhado': cidadao.endereco_detalhado,
        'socioeconomico': cidadao.socioeconomico,
        'membros_da_familia': cidadao.membros_da_familia,
        'observacoes': cidadao.observacoes,
        'consentimentos': {
            'autoriza_imagem': cidadao.autoriza_imagem,
            'imagem_aceita_em': cidadao.imagem_aceita_em.isoformat() if cidadao.imagem_aceita_em else None,
            'imagem_revogada_em': cidadao.imagem_revogada_em.isoformat() if cidadao.imagem_revogada_em else None,
            'consentiu_tefe_cidadao_em': cidadao.consentiu_tefe_cidadao_em.isoformat() if cidadao.consentiu_tefe_cidadao_em else None,
        },
        'criado_em': cidadao.criado_em.isoformat(),
        'atualizado_em': cidadao.atualizado_em.isoformat(),
    }

    _registrar_auditoria(
        request, 'EXPORT', 'cidadao', cidadao.id,
        dados_novos={'acao': 'exportacao_lgpd'},
    )

    response = HttpResponse(
        json.dumps(dados, ensure_ascii=False, indent=2),
        content_type='application/json; charset=utf-8',
    )
    response['Content-Disposition'] = f'attachment; filename="dados_{cidadao.id}.json"'
    return response


@api_view(['DELETE'])
@permission_classes([Supervisao])
@transaction.atomic
def eliminar_dados_pessoais(request, cidadao_id: str):
    """
    Elimina dados pessoais com anonimização (Art. 18, VI).

    Soft delete: marca excluido_em e anonimiza dados sensíveis (CPF, email,
    telefone, endereço). O registro permanece para integridade referencial,
    mas torna-se inacessível nas consultas normais (filtrado por excluido_em).
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    agora = timezone.now()

    # Anonimiza dados sensíveis antes de marcar como excluído
    cidadao.cpf = None
    cidadao.cpf_indice = None
    cidadao.nis = None
    cidadao.nis_indice = None
    cidadao.email = None
    cidadao.email_indice = None
    cidadao.rg = None
    cidadao.telefone = None
    cidadao.endereco = None
    cidadao.nome = f'Cidadão excluído {cidadao.id[:8]}'
    cidadao.excluido_em = agora
    cidadao.atualizado_em = agora
    cidadao.save()

    _registrar_auditoria(
        request, 'ERASURE', 'cidadao', cidadao.id,
        dados_novos={'acao': 'eliminacao_lgpd'},
    )

    return Response({'mensagem': 'Dados pessoais eliminados com sucesso'}, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
def revogar_consentimento_imagem(request, cidadao_id: str):
    """
    Revoga consentimento de uso de imagem (Art. 18, IX).

    O consentimento de imagem pode ser revogado a qualquer momento. A
    revogação não afeta atendimentos anteriores onde a imagem já foi usada,
    mas impede uso futuro.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    cidadao.autoriza_imagem = False
    cidadao.imagem_revogada_em = timezone.now()
    cidadao.atualizado_em = timezone.now()
    cidadao.save(update_fields=['autoriza_imagem', 'imagem_revogada_em', 'atualizado_em'])

    _registrar_auditoria(
        request, 'CONSENT_REVOKED', 'cidadao', cidadao.id,
        dados_novos={'imagem_revogada_em': str(cidadao.imagem_revogada_em)},
    )

    return Response({'mensagem': 'Consentimento de uso de imagem revogado com sucesso'})


@api_view(['POST'])
@permission_classes([EquipeDeAtendimento])
def registrar_consentimento_imagem(request, cidadao_id: str):
    """
    Registra consentimento de uso de imagem (Art. 8, §6).

    Grava o timestamp do consentimento para demonstrar que foi dado de forma
    válida, livre e informada.
    """
    cidadao = Cidadao.vigentes.filter(id=cidadao_id).first()
    if cidadao is None:
        return Response({'detalhe': 'Cidadão não encontrado'}, status=status.HTTP_404_NOT_FOUND)

    cidadao.autoriza_imagem = True
    cidadao.imagem_aceita_em = timezone.now()
    cidadao.imagem_revogada_em = None  # Limpa revogação anterior
    cidadao.atualizado_em = timezone.now()
    cidadao.save(update_fields=['autoriza_imagem', 'imagem_aceita_em', 'imagem_revogada_em', 'atualizado_em'])

    _registrar_auditoria(
        request, 'CONSENT_GIVEN', 'cidadao', cidadao.id,
        dados_novos={'imagem_aceita_em': str(cidadao.imagem_aceita_em)},
    )

    return Response({'mensagem': 'Consentimento de uso de imagem registrado com sucesso'})
