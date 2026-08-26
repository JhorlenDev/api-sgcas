"""
Histórico municipal do cidadão — o que a recepção vê antes de conceder.

Existe por um motivo concreto: a pessoa retira cesta básica no CRAS Centro e
pede a mesma coisa no CRAS Sul. Sem uma visão que atravesse as unidades, o
segundo atendimento não tem como saber do primeiro.

Três regras moldam este módulo, e cada uma resolve um problema diferente:

1. **Atravessa unidades.** O escopo por unidade vale para o que é operacional —
   fila, casos em andamento. Não vale aqui: as unidades precisam conversar entre
   si, senão a duplicidade nunca aparece.

2. **Avisa, não bloqueia.** A pessoa pode estar voltando por outra demanda.
   Barrar automaticamente travaria quem tem necessidade nova por causa de
   atendimento antigo, e ninguém saberia por quê. Quem decide é quem atende — e
   a decisão fica registrada.

3. **Quem atendeu só aparece para coordenador e admin.** O nome é sempre
   gravado, porque a responsabilização não depende de quem consegue ler. O que
   se restringe é a exposição rotineira do nome do servidor entre unidades.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.atendimentos.models import AtendimentoDeRecepcao, BeneficioEventual, Caso
from apps.cidadaos.models import Cidadao
from apps.contas.models import Operador

# Janela padrão da consulta. O mês corrente vem destacado, porque é nele que a
# duplicidade costuma acontecer — mas os 12 meses ficam visíveis para o caso de
# benefícios com intervalo mais longo, como auxílio natalidade.
MESES_DE_HISTORICO = 12


@dataclass(frozen=True)
class Entrada:
    """
    Uma linha da timeline.

    `quando` é sempre com fuso. As tabelas herdadas guardam `timestamp` sem
    fuso e as novas guardam `timestamptz`; misturar os dois na ordenação
    levantaria erro. A conversão acontece na entrada, num lugar só, em vez de
    espalhar verificação por cada comparação.
    """

    quando: datetime
    unidade: str
    o_que: str
    detalhe: str | None
    quem_atendeu: str | None  # None quando o leitor não pode ver
    no_mes_corrente: bool

    @property
    def e_de_outra_unidade(self) -> bool:
        return self._outra_unidade

    _outra_unidade: bool = False


def _inicio_da_janela():
    agora = timezone.now()
    ano, mes = agora.year, agora.month - MESES_DE_HISTORICO
    while mes <= 0:
        mes += 12
        ano -= 1
    return agora.replace(year=ano, month=mes, day=1, hour=0, minute=0, second=0, microsecond=0)


def _com_fuso(momento: datetime) -> datetime:
    """
    Garante data com fuso antes de comparar.

    As colunas herdadas são `timestamp without time zone` — o ORM anterior não
    gerava coluna com fuso. Os valores chegam ingênuos, e compará-los com
    `timezone.now()` levantaria erro. Assumimos que o gravado está no fuso do
    projeto, que é o que o sistema antigo fazia na prática.

    Pendência de esquema: migrar essas colunas para `timestamptz`. Enquanto isso
    não acontece, uma unidade em fuso diferente gravaria a hora errada — em
    Tefé não muda nada, mas é dívida a pagar antes de a rede crescer.
    """
    if timezone.is_naive(momento):
        return timezone.make_aware(momento, timezone.get_current_timezone())
    return timezone.localtime(momento)


def _mesmo_mes(momento: datetime) -> bool:
    agora = timezone.localtime(timezone.now())
    local = _com_fuso(momento)
    return (local.year, local.month) == (agora.year, agora.month)


def do_cidadao(cidadao: Cidadao, leitor: Operador) -> list[Entrada]:
    """
    Linha do tempo de todas as unidades, do mais recente para o mais antigo.

    `leitor` não filtra o *conteúdo* — o histórico é municipal por decisão. Ele
    determina apenas se o nome de quem atendeu aparece.
    """
    desde = _inicio_da_janela()
    mostra_quem = leitor.ve_quem_atendeu
    unidade_do_leitor = leitor.unidade_id

    entradas: list[Entrada] = []

    beneficios = (
        BeneficioEventual.vigentes.filter(cidadao=cidadao, criado_em__gte=desde)
        .select_related('unidade', 'registrado_por')
    )
    for b in beneficios:
        rotulo = dict(BeneficioEventual.Tipo.choices).get(b.tipo, b.tipo)
        entradas.append(Entrada(
            quando=_com_fuso(b.criado_em),
            unidade=b.unidade.nome if b.unidade else 'Unidade não informada',
            o_que=f'Benefício concedido: {rotulo}',
            detalhe=b.descricao,
            quem_atendeu=b.registrado_por.nome if mostra_quem and b.registrado_por else None,
            no_mes_corrente=_mesmo_mes(b.criado_em),
            _outra_unidade=bool(b.unidade_id) and b.unidade_id != unidade_do_leitor,
        ))

    casos = (
        Caso.vigentes.filter(cidadao=cidadao, aberto_em__gte=desde)
        .select_related('unidade', 'tecnico', 'servico')
    )
    for c in casos:
        situacao = dict(Caso.Situacao.choices).get(c.situacao, c.situacao)
        servico = c.servico.nome if c.servico_id and c.servico else None
        detalhe = c.descricao
        if servico:
            detalhe = f'{servico} — {detalhe}' if detalhe else servico
        entradas.append(Entrada(
            quando=_com_fuso(c.aberto_em),
            unidade=c.unidade.nome,
            o_que=f'Caso {situacao.lower()}',
            detalhe=detalhe,
            quem_atendeu=c.tecnico.nome if mostra_quem and c.tecnico else None,
            no_mes_corrente=_mesmo_mes(c.aberto_em),
            _outra_unidade=c.unidade_id != unidade_do_leitor,
        ))

    recepcoes = (
        AtendimentoDeRecepcao.objects.filter(cidadao=cidadao, criado_em__gte=desde)
        .select_related('unidade', 'atendido_por', 'caso', 'caso__unidade')
    )
    for r in recepcoes:
        finalizado = r.desfecho == AtendimentoDeRecepcao.Desfecho.FINALIZADO
        observacao = r.motivo
        destino = None
        if not finalizado and r.caso_id and r.caso:
            observacao = r.caso.descricao or r.motivo
            destino = r.caso.unidade.nome if r.caso.unidade_id else None
        detalhe = observacao
        if destino:
            detalhe = f'Encaminhado para {destino}. {observacao}' if observacao else f'Encaminhado para {destino}.'
        entradas.append(Entrada(
            quando=_com_fuso(r.criado_em),
            unidade=r.unidade.nome,
            o_que=(
                f'Finalizado no balcão — {r.demanda}'
                if finalizado else
                f'Recepção encaminhou para atendimento — {r.demanda}'
            ),
            # O motivo da negativa é a informação que a próxima unidade precisa:
            # sem ela, a pessoa refaz o mesmo pedido e ninguém sabe o que houve.
            detalhe=detalhe,
            quem_atendeu=r.atendido_por.nome if mostra_quem else None,
            no_mes_corrente=_mesmo_mes(r.criado_em),
            _outra_unidade=r.unidade_id != unidade_do_leitor,
        ))

    return sorted(entradas, key=lambda e: e.quando, reverse=True)


def alerta_de_duplicidade(cidadao: Cidadao, tipo_pedido: str) -> BeneficioEventual | None:
    """
    Devolve a concessão do mesmo tipo no mês corrente, se houver.

    É um aviso para quem atende, não um impedimento: quem decide é a pessoa no
    balcão, que sabe se o pedido de hoje tem ou não relação com o anterior.
    """
    agora = timezone.localtime(timezone.now())
    inicio_do_mes = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    return (
        BeneficioEventual.vigentes.filter(
            cidadao=cidadao, tipo=tipo_pedido, criado_em__gte=inicio_do_mes
        )
        .select_related('unidade')
        .order_by('-criado_em')
        .first()
    )
