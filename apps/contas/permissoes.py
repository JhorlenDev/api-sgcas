"""
Permissões por papel.

O corte é por papel, não por unidade: o escopo de unidade filtra *quais dados*
aparecem, e vive em `apps.contas.escopo`. Aqui se decide *quem pode chamar*.
"""
from rest_framework.permissions import BasePermission

from apps.contas.papeis import Papel


class TemPapel(BasePermission):
    """
    Base para as permissões abaixo. Sem papéis declarados, nega.

    Negar por omissão é deliberado: uma view nova que esqueça de declarar quem
    pode usá-la fica fechada, em vez de aberta a qualquer autenticado. Foi o
    contrário disso que, no sistema anterior, deixou um endpoint de escrita
    aceitando chamada de perfil somente-leitura.
    """

    papeis: tuple[str, ...] = ()

    def has_permission(self, request, view):
        operador = getattr(request, 'user', None)
        if operador is None or not getattr(operador, 'is_authenticated', False):
            return False
        return operador.papel in self.papeis


class SomenteAdmin(TemPapel):
    papeis = (Papel.ADMIN,)


class Supervisao(TemPapel):
    papeis = (Papel.ADMIN, Papel.COORDENADOR)


class EquipeDeAtendimento(TemPapel):
    papeis = (
        Papel.ADMIN,
        Papel.COORDENADOR,
        Papel.ASSISTENTE_SOCIAL,
        Papel.TECNICO,
    )


class Recepcao(TemPapel):
    """Quem opera o balcão: cadastra, consulta histórico e encaminha à fila."""

    papeis = (
        Papel.ADMIN,
        Papel.COORDENADOR,
        Papel.ASSISTENTE_SOCIAL,
        Papel.TECNICO,
        Papel.RECEPCIONISTA,
    )


class PodeConsultar(TemPapel):
    """
    Leitura do cadastro e do histórico.

    Inclui o VISUALIZADOR, que existe justamente para consultar sem alterar —
    era o comportamento do sistema anterior e foi mantido por decisão. Escrita
    continua fora do alcance dele.
    """

    papeis = (
        Papel.ADMIN,
        Papel.COORDENADOR,
        Papel.ASSISTENTE_SOCIAL,
        Papel.TECNICO,
        Papel.RECEPCIONISTA,
        Papel.VISUALIZADOR,
    )


class QualquerOperador(TemPapel):
    papeis = tuple(vars(Papel)[n] for n in dir(Papel) if not n.startswith('_'))
