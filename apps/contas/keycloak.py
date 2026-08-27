"""
Conversa com o Tefe Cidadao (Keycloak).

Duas naturezas diferentes vivem aqui, de proposito separadas:

- o fluxo de entrada da pessoa, que troca codigo por token;
- a conta de servico, que concede e retira papeis em nome do sistema.

A segunda existe para que ninguem precise abrir o console do Keycloak: a decisao
de quem entra e tomada na tela do SGCAS, e este modulo traduz a decisao em
atribuicao de client role no realm.
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

import jwt
import requests
from django.conf import settings

TEMPO_LIMITE = 15


class ErroDoKeycloak(RuntimeError):
    """Falha ao falar com o Tefe Cidadao. A mensagem e mostravel ao operador."""


def _base_realm() -> str:
    return f'{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}'


def _base_admin() -> str:
    return f'{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}'


# ─── Entrada da pessoa ──────────────────────────────────────────────

def url_de_login(state: str, redirect_uri: str) -> str:
    parametros = {
        'response_type': 'code',
        'client_id': settings.KEYCLOAK_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': 'openid profile email',
        'state': state,
        'prompt': 'login',
    }
    return f'{_base_realm()}/protocol/openid-connect/auth?{urlencode(parametros)}'


def url_de_logout(id_token: str | None, pos_logout: str) -> str:
    """
    Encerra a sessao da pessoa no proprio Tefe Cidadao.

    Sem passar por aqui, sair do SGCAS limparia so a sessao local: a do Keycloak
    seguiria aberta, e a proxima entrada reabriria a conta anterior sem pedir
    credencial. Em um CRAS, onde varios servidores usam o mesmo computador,
    isso e risco de entrar com a conta do colega.
    """
    parametros = {'post_logout_redirect_uri': pos_logout}
    if id_token:
        parametros['id_token_hint'] = id_token
    else:
        parametros['client_id'] = settings.KEYCLOAK_CLIENT_ID
    return f'{_base_realm()}/protocol/openid-connect/logout?{urlencode(parametros)}'


def trocar_codigo_por_token(codigo: str, redirect_uri: str) -> dict:
    resposta = requests.post(
        f'{_base_realm()}/protocol/openid-connect/token',
        data={
            'grant_type': 'authorization_code',
            'client_id': settings.KEYCLOAK_CLIENT_ID,
            'client_secret': settings.KEYCLOAK_CLIENT_SECRET,
            'code': codigo,
            'redirect_uri': redirect_uri,
        },
        timeout=TEMPO_LIMITE,
    )
    if resposta.status_code != 200:
        raise ErroDoKeycloak('Não foi possível concluir o acesso pelo Tefé Cidadão')
    return resposta.json()


# ─── Validacao do token ─────────────────────────────────────────────

_jwks: dict = {'cliente': None, 'expira_em': 0.0}


def _cliente_de_chaves() -> jwt.PyJWKClient:
    """
    Cliente de chaves publicas do realm, com cache curto.

    Buscar o JWKS a cada requisicao colocaria o Keycloak no caminho critico de
    todo acesso; nunca renovar impediria a rotacao de chaves. Uma hora e o
    meio-termo usual.
    """
    agora = time.monotonic()
    if _jwks['cliente'] is None or agora > _jwks['expira_em']:
        _jwks['cliente'] = jwt.PyJWKClient(
            f'{_base_realm()}/protocol/openid-connect/certs',
            headers={'User-Agent': 'SGCAS/1.0'},
            timeout=TEMPO_LIMITE,
        )
        _jwks['expira_em'] = agora + 3600
    return _jwks['cliente']


def validar_token(access_token: str) -> dict:
    """
    Confere assinatura, emissor, audiencia e validade — e devolve as claims.

    A audiencia e verificada contra 'account' (padrao do Keycloak para o fluxo
    de authorization code). A amarracao ao client especifico e feita depois via
    `resource_access` no servicos.py.
    """
    try:
        chave = _cliente_de_chaves().get_signing_key_from_jwt(access_token)
        return jwt.decode(
            access_token,
            chave.key,
            algorithms=['RS256'],
            audience='account',
            issuer=_base_realm(),
            leeway=60,
        )
    except jwt.PyJWTError as erro:
        raise ErroDoKeycloak(f'Token do Tefé Cidadão inválido: {erro}') from erro


# ─── Conta de servico ───────────────────────────────────────────────

def _token_de_servico() -> str:
    resposta = requests.post(
        f'{_base_realm()}/protocol/openid-connect/token',
        data={
            'grant_type': 'client_credentials',
            'client_id': settings.KEYCLOAK_CLIENT_ID,
            'client_secret': settings.KEYCLOAK_CLIENT_SECRET,
        },
        timeout=TEMPO_LIMITE,
    )
    if resposta.status_code != 200:
        raise ErroDoKeycloak(
            'O SGCAS não consegue falar com o Tefé Cidadão para conceder acesso. '
            'Habilite "Service accounts roles" no client e conceda view-users, '
            'manage-users e view-clients do realm-management.'
        )
    return resposta.json()['access_token']


def _uuid_do_client(token: str) -> str:
    resposta = requests.get(
        f'{_base_admin()}/clients',
        headers={'Authorization': f'Bearer {token}'},
        params={'clientId': settings.KEYCLOAK_CLIENT_ID},
        timeout=TEMPO_LIMITE,
    )
    clients = resposta.json() if resposta.status_code == 200 else []

    # Sem `view-clients` o Keycloak nao responde 403: devolve 200 com lista
    # vazia. A leitura ingenua disso vira "o client nao existe", e manda quem
    # investigar procurar no lugar errado.
    if not clients:
        raise ErroDoKeycloak(
            f'Não foi possível ler o client {settings.KEYCLOAK_CLIENT_ID} no Tefé Cidadão. '
            'Conceda também view-clients (realm-management) à conta de serviço — sem ela o '
            'Keycloak devolve lista vazia em vez de negar, e o client parece inexistente.'
        )
    return clients[0]['id']


def definir_papel(keycloak_user_id: str, papel: str) -> None:
    """
    Concede um papel do client, retirando antes os demais.

    `users.role` e coluna unica: deixar dois papeis no realm faria a precedencia
    decidir em silencio qual vale, e a tela mostraria algo diferente do que o
    administrador acabou de escolher.
    """
    token = _token_de_servico()
    uuid = _uuid_do_client(token)
    cabecalho = {'Authorization': f'Bearer {token}'}
    rota = f'{_base_admin()}/users/{keycloak_user_id}/role-mappings/clients/{uuid}'

    atuais = requests.get(rota, headers=cabecalho, timeout=TEMPO_LIMITE).json()
    if atuais:
        requests.delete(rota, headers=cabecalho, json=atuais, timeout=TEMPO_LIMITE)

    disponivel = requests.get(
        f'{_base_admin()}/clients/{uuid}/roles/{papel}',
        headers=cabecalho,
        timeout=TEMPO_LIMITE,
    )
    if disponivel.status_code != 200:
        raise ErroDoKeycloak(f'O papel {papel} não existe no client do Tefé Cidadão')

    papel_json = disponivel.json()
    requests.post(
        rota,
        headers=cabecalho,
        json=[{'id': papel_json['id'], 'name': papel_json['name']}],
        timeout=TEMPO_LIMITE,
    )


def remover_papeis(keycloak_user_id: str) -> None:
    """
    Retira todos os papeis do client.

    Usado ao desativar alguem. Sem isso a desativacao dura ate o proximo login:
    o papel continua no realm, o acesso o le de volta e a pessoa reaparece
    ativa, como se tivesse sido aprovada por alguem.
    """
    token = _token_de_servico()
    uuid = _uuid_do_client(token)
    cabecalho = {'Authorization': f'Bearer {token}'}
    rota = f'{_base_admin()}/users/{keycloak_user_id}/role-mappings/clients/{uuid}'

    atuais = requests.get(rota, headers=cabecalho, timeout=TEMPO_LIMITE).json()
    if atuais:
        requests.delete(rota, headers=cabecalho, json=atuais, timeout=TEMPO_LIMITE)
