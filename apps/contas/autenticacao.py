"""
Autenticacao das requisicoes do DRF a partir da sessao.

A sessao e criada no retorno do Tefe Cidadao e guarda apenas o identificador do
operador. O papel e relido do banco a cada requisicao, e nao copiado para a
sessao: assim, retirar o acesso de alguem tem efeito imediato, em vez de valer
so quando a sessao dela expirar.
"""
from rest_framework import authentication, exceptions

from apps.contas.models import Operador

CHAVE_OPERADOR = 'operador_id'
CHAVE_ID_TOKEN = 'id_token'


class SessaoDoTefeCidadao(authentication.BaseAuthentication):
    def authenticate(self, request):
        operador_id = request.session.get(CHAVE_OPERADOR)
        if not operador_id:
            return None

        operador = (
            Operador.objects.select_related('unidade')
            .filter(id=operador_id, excluido_em__isnull=True)
            .first()
        )

        if operador is None:
            request.session.flush()
            raise exceptions.AuthenticationFailed('Sessão inválida')

        if not operador.ativo:
            # Desativado enquanto a sessao estava aberta: a sessao morre junto.
            request.session.flush()
            raise exceptions.AuthenticationFailed('Acesso desativado')

        return (operador, None)
