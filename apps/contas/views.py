"""Rotas de entrada e saida pelo Tefe Cidadao."""
from __future__ import annotations

import secrets
import logging

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.contas import keycloak
from apps.contas.autenticacao import CHAVE_ID_TOKEN, CHAVE_OPERADOR
from apps.contas.servicos import AcessoPendente, entrar, registrar_pedido

CHAVE_STATE = 'kc_state'
CHAVE_PEDIDO_ACESSO = 'pending_access_claims'
logger = logging.getLogger(__name__)


def _redirect_uri() -> str:
    return settings.KEYCLOAK_REDIRECT_URI


def _frontend(caminho: str) -> str:
    return f'{settings.FRONTEND_URL.rstrip("/")}{caminho}'


@require_GET
def login(request):
    """Manda a pessoa ao Tefé Cidadão, guardando o `state` na sessão."""
    state = secrets.token_urlsafe(32)
    request.session[CHAVE_STATE] = state
    logger.info('Login SGCAS iniciado via Keycloak. session_key=%s', request.session.session_key)
    return HttpResponseRedirect(keycloak.url_de_login(state, _redirect_uri()))


@require_GET
def callback(request):
    """
    Retorno do Tefé Cidadão.

    É um fluxo aberto no navegador: erro aqui não pode virar JSON cru na tela,
    então cada desfecho leva a pessoa a uma página que explica o que houve.
    """
    esperado = request.session.pop(CHAVE_STATE, None)
    if not esperado or esperado != request.GET.get('state'):
        logger.warning(
            'Callback Keycloak recusado: state invalido. tinha_state=%s session_key=%s',
            bool(esperado),
            request.session.session_key,
        )
        return HttpResponseRedirect(_frontend('/login?erro=estado-invalido'))

    codigo = request.GET.get('code')
    if not codigo:
        logger.warning('Callback Keycloak recusado: sem codigo. session_key=%s', request.session.session_key)
        return HttpResponseRedirect(_frontend('/login?erro=sem-codigo'))

    claims = {}
    try:
        tokens = keycloak.trocar_codigo_por_token(codigo, _redirect_uri())
        claims = keycloak.validar_token(tokens['access_token'])
        operador = entrar(tokens['access_token'], claims)
    except AcessoPendente:
        request.session[CHAVE_PEDIDO_ACESSO] = {
            'sub': claims.get('sub'),
            'email': claims.get('email'),
            'preferred_username': claims.get('preferred_username'),
            'name': claims.get('name'),
        }
        logger.warning('Login Keycloak pendente: usuario sem papel SGCAS no client.')
        return HttpResponseRedirect(_frontend('/waiting-approval'))
    except keycloak.ErroDoKeycloak as erro:
        logger.warning('Erro no login Keycloak: %s', erro)
        return HttpResponseRedirect(_frontend('/login?erro=sem-acesso'))

    request.session.cycle_key()
    request.session[CHAVE_OPERADOR] = operador.id
    request.session[CHAVE_ID_TOKEN] = tokens.get('id_token', '')
    logger.info('Login SGCAS concluido: operador=%s papel=%s email=%s', operador.id, operador.papel, operador.email)

    return HttpResponseRedirect(_frontend('/dashboard'))


@require_POST
@csrf_exempt
def reenviar_solicitacao(request):
    """Reenvia/reafirma o pedido criado quando a pessoa entrou sem papel."""
    claims = request.session.get(CHAVE_PEDIDO_ACESSO) or {}
    if not claims.get('sub'):
        return JsonResponse(
            {
                'sucesso': False,
                'detalhe': 'Não encontramos uma solicitação nesta sessão. Entre pelo Tefé Cidadão novamente.',
            },
            status=409,
        )

    registrar_pedido(claims)
    logger.info(
        'Solicitacao de acesso reenviada: email=%s keycloak_id=%s',
        claims.get('email') or claims.get('preferred_username'),
        claims.get('sub'),
    )
    return JsonResponse({
        'sucesso': True,
        'mensagem': 'Solicitação reenviada. Aguarde aprovação do coordenador ou administrador.',
    })


@require_POST
@csrf_exempt
def logout(request):
    """
    Encerra a sessão local e devolve a URL que encerra a do Tefé Cidadão.

    Parar na sessão local deixaria a do SSO viva, e a próxima entrada reabriria
    a conta anterior sem pedir credencial.
    """
    id_token = request.session.get(CHAVE_ID_TOKEN)
    request.session.flush()
    return JsonResponse({
        'sucesso': True,
        'urlDeLogout': keycloak.url_de_logout(id_token, _frontend('/login')),
    })
