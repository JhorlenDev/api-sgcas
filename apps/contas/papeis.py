"""
Os papeis do SGCAS e como eles saem do token do Tefe Cidadao.

O SGCAS nao decide papel. Ele le o que o realm concedeu dentro do client do
sistema e espelha na conta local — que existe para as consultas e para a
trilha de auditoria referenciar alguem.
"""
from __future__ import annotations

import base64
import json


class Papel:
    ADMIN = 'ADMIN'
    COORDENADOR = 'COORDENADOR'
    ASSISTENTE_SOCIAL = 'ASSISTENTE_SOCIAL'
    TECNICO = 'TECNICO'
    RECEPCIONISTA = 'RECEPCIONISTA'
    GESTOR_ACOES_ITINERANTES = 'GESTOR_ACOES_ITINERANTES'
    VISUALIZADOR = 'VISUALIZADOR'


# Ordem de precedencia, do mais forte para o mais fraco.
#
# `users.role` e uma coluna unica, mas nada impede o realm de atribuir dois
# papeis a mesma pessoa. Recusar a entrada puniria o operador por um erro de
# quem administra; assumir o mais forte por acaso concederia poder sem decisao.
# Vale o primeiro desta lista que a pessoa tiver — a escolha fica explicita
# aqui, e nao na ordem em que o Keycloak devolveu o array.
PRECEDENCIA = (
    Papel.ADMIN,
    Papel.COORDENADOR,
    Papel.ASSISTENTE_SOCIAL,
    Papel.TECNICO,
    Papel.RECEPCIONISTA,
    Papel.GESTOR_ACOES_ITINERANTES,
    Papel.VISUALIZADOR,
)

# Quem enxerga dados de todas as unidades no que e operacional.
VE_TODAS_AS_UNIDADES = frozenset({Papel.ADMIN})

# Quem pode ver o nome do servidor que atendeu em outra unidade.
#
# O nome e sempre gravado — a responsabilizacao nao depende de quem consegue
# ler. O que se restringe e a exposicao rotineira entre unidades: a recepcao
# precisa saber que houve atendimento, onde e o que foi concedido, nao por quem.
VE_QUEM_ATENDEU = frozenset({Papel.ADMIN, Papel.COORDENADOR})


def _decodificar_payload(token: str) -> dict:
    """Le o corpo do JWT sem validar assinatura. Ver `papeis_do_token`."""
    try:
        payload = token.split('.')[1]
        faltando = '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload + faltando))
    except (IndexError, ValueError, TypeError):
        return {}


def papeis_do_token(token: str, client_id: str) -> list[str]:
    """
    Papeis concedidos a pessoa DENTRO do client do SGCAS.

    Tem de sair do access token: o `/userinfo` devolve apenas identidade e nunca
    carrega `resource_access`. Ler dali foi o que, no sistema anterior, deixou o
    SGCAS cego para papel e o obrigou a inventar um VISUALIZADOR para todos.

    A validacao de assinatura e responsabilidade de quem recebe o token na
    borda; esta funcao apenas extrai. Nao use isoladamente para autorizar.
    """
    acesso = _decodificar_payload(token).get('resource_access') or {}
    papeis = (acesso.get(client_id) or {}).get('roles')
    return list(papeis) if isinstance(papeis, list) else []


def papel_efetivo(papeis: list[str] | None) -> str | None:
    """
    Traduz os papeis do realm no unico que o SGCAS entende.

    Devolve `None` para quem nao tem papel algum no client — o cidadao comum,
    que tem conta no Tefe Cidadao mas nao e operador da assistencia social.
    Quem chama trata isso como porta fechada, nao como perfil vazio.
    """
    tem = set(papeis or ())
    return next((papel for papel in PRECEDENCIA if papel in tem), None)
