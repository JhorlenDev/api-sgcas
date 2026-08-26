"""
Entrada pelo Tefe Cidadao: quem entra, quem fica na fila, e o que se grava.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.contas import keycloak
from apps.contas.models import Operador, PedidoDeAcesso
from apps.contas.papeis import papeis_do_token, papel_efetivo


class AcessoPendente(Exception):
    """
    O pedido foi registrado e aguarda decisao.

    Distinto de uma recusa definitiva: quem chama leva a pessoa para a tela de
    espera, em vez de devolve-la ao login com uma mensagem de erro.
    """


def registrar_pedido(claims: dict) -> None:
    _registrar_pedido(claims)


@transaction.atomic
def entrar(access_token: str, claims: dict) -> Operador:
    """
    Resolve o operador a partir do token, ou registra um pedido de acesso.

    O papel vem do realm, nao daqui. Antes, quem chegava por SSO recebia um
    papel de leitura e ficava numa fila de aprovacao manual: qualquer cidadao
    com conta no Tefe Cidadao virava usuario so por clicar no botao, e a
    autorizacao real era um checkbox decidido por quem via apenas nome e e-mail.
    """
    papel = papel_efetivo(papeis_do_token(access_token, settings.KEYCLOAK_CLIENT_ID))

    if papel is None:
        _registrar_pedido(claims)
        raise AcessoPendente()

    email = claims.get('email') or claims.get('preferred_username') or ''
    nome = claims.get('name') or claims.get('preferred_username') or email
    keycloak_id = claims['sub']

    existente = Operador.objects.filter(email=email).first()
    agora = timezone.now()

    if existente is None:
        operador = Operador(
            id=str(uuid.uuid4()),
            email=email,
            nome=nome,
            papel=papel,
            ativo=True,
            keycloak_id=keycloak_id,
            criado_em=agora,
            atualizado_em=agora,
        )
        operador.save(force_insert=True)
        return operador

    # O papel e espelhado a cada entrada: o realm e a fonte da verdade, e a
    # coluna local serve as consultas e a referencia da auditoria.
    existente.papel = papel
    existente.ativo = True
    existente.keycloak_id = existente.keycloak_id or keycloak_id
    existente.excluido_em = None
    existente.atualizado_em = agora
    existente.save(update_fields=['papel', 'ativo', 'keycloak_id', 'excluido_em', 'atualizado_em'])
    return existente


def _registrar_pedido(claims: dict) -> None:
    """
    Registra que alguem sem papel tentou entrar.

    Um pedido ja pendente e reaproveitado: reentrar na tela de login nao pode
    multiplicar linhas na fila de quem decide. Quem foi recusado antes pode
    pedir de novo — abre-se um pedido novo, e o recusado permanece no historico
    em vez de ser sobrescrito.
    """
    keycloak_id = claims['sub']
    if PedidoDeAcesso.objects.filter(
        keycloak_id=keycloak_id, situacao=PedidoDeAcesso.Situacao.PENDENTE
    ).exists():
        return

    email = claims.get('email') or claims.get('preferred_username') or ''
    PedidoDeAcesso(
        id=str(uuid.uuid4()),
        keycloak_id=keycloak_id,
        email=email,
        nome=claims.get('name') or claims.get('preferred_username') or email,
        situacao=PedidoDeAcesso.Situacao.PENDENTE,
        pedido_em=timezone.now(),
    ).save(force_insert=True)


def desativar(operador: Operador) -> None:
    """
    Desliga o acesso — no realm antes do banco.

    Mexer so no registro local dura ate o proximo login: o papel continua no
    realm, a entrada o le de volta e a pessoa reaparece ativa, como se tivesse
    sido aprovada por alguem. Retirar la primeiro garante que, se o Tefe Cidadao
    estiver fora do ar, nada muda aqui e o erro aparece na tela — em vez de uma
    desativacao que se desfaz sozinha depois.
    """
    if operador.keycloak_id:
        keycloak.remover_papeis(operador.keycloak_id)

    operador.ativo = False
    operador.atualizado_em = timezone.now()
    operador.save(update_fields=['ativo', 'atualizado_em'])
