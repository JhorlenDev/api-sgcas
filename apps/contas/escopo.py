"""
Escopo por unidade nas consultas operacionais.

Vale para fila, casos em andamento e indicadores da unidade. Nao vale para o
cadastro do cidadao nem para o historico de atendimentos: a pessoa circula entre
as unidades, e quem a atende precisa saber quem ela e — o corte ali e por papel,
nao por unidade.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet

from apps.contas.models import Operador

# Marcador para quem nao tem unidade definida.
#
# Nao e um id valido, entao nenhum registro casa com ele e a consulta devolve
# lista vazia. A alternativa — filtro vazio — daria acesso a *todas* as unidades
# justamente a quem nao tem nenhuma. Conta criada por SSO nasce sem unidade, e a
# aprovacao pode ocorrer antes de alguem preencher: falhar fechado e o unico
# padrao seguro.
SEM_UNIDADE = '__sem_unidade__'


def escopo_de(operador: Operador) -> dict:
    """Filtro de unidade a ser aplicado nas consultas operacionais."""
    if operador.ve_todas_as_unidades:
        return {}
    return {'unidade_id': operador.unidade_id or SEM_UNIDADE}


def restringir(consulta: QuerySet, operador: Operador) -> QuerySet:
    return consulta.filter(**escopo_de(operador))


def pode_acessar_unidade(operador: Operador, unidade_id: str) -> bool:
    if operador.ve_todas_as_unidades:
        return True
    return bool(operador.unidade_id) and operador.unidade_id == unidade_id


def resolver_filtro(operador: Operador, unidade_pedida: str | None = None) -> dict:
    """
    Filtro final quando a consulta aceita `unidade` por parametro.

    O parametro existe para quem enxerga varias unidades poder escolher uma. Sem
    validacao, qualquer autenticado poderia envia-lo e ler dados de outra
    unidade. Pedir unidade alheia e recusado de forma explicita, em vez de
    silenciosamente ignorado — o pedido fica visivel no log em vez de virar um
    resultado confuso na tela.
    """
    if unidade_pedida and not pode_acessar_unidade(operador, unidade_pedida):
        raise PermissionDenied('Sem permissão para consultar dados de outra unidade')

    if operador.ve_todas_as_unidades:
        return {'unidade_id': unidade_pedida} if unidade_pedida else {}

    return escopo_de(operador)
