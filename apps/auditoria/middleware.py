"""
Middleware que grava a trilha de auditoria.

Fica fora das views de propósito: espalhar chamadas de auditoria por cada
endpoint garante que alguém esqueça em algum. Aqui, um endpoint novo já nasce
auditado — e esquecer passa a exigir uma exclusão explícita, que aparece na
revisão de código.
"""
from __future__ import annotations

import json
import logging
import uuid

from django.utils import timezone

from apps.auditoria.models import RegistroDeAuditoria
from apps.auditoria.redacao import redigir

logger = logging.getLogger(__name__)

# Leituras auditadas: apenas onde o alvo é dado pessoal.
#
# Auditar todo GET encheria a trilha de consulta a lista de unidades e catálogo
# de demandas, e a informação que importa — quem abriu o prontuário de fulano —
# ficaria enterrada no ruído.
LEITURAS_AUDITADAS = ('/api/citizens', '/api/reception', '/api/queues/chamar-proximo')

# Fora da trilha: o próprio módulo de auditoria (evita recursão) e o fluxo de
# autenticação, cujos corpos carregam token.
IGNORADAS = ('/api/auditoria', '/api/auth/keycloak', '/api/auth/logout')

ACOES = {'GET': 'READ', 'POST': 'CREATE', 'PUT': 'UPDATE', 'PATCH': 'UPDATE', 'DELETE': 'DELETE'}


class TrilhaDeAuditoria:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        corpo = self._corpo(request)
        resposta = self.get_response(request)

        try:
            if self._deve_registrar(request, resposta):
                self._registrar(request, resposta, corpo)
        except Exception:
            logger.exception(
                'Falha ao registrar auditoria: %s %s',
                request.method,
                request.path,
            )

        return resposta

    def _corpo(self, request) -> dict | None:
        """Lê o corpo antes da view consumi-lo."""
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return None
        try:
            return json.loads(request.body or b'{}')
        except (ValueError, UnicodeDecodeError):
            return None

    def _deve_registrar(self, request, resposta) -> bool:
        caminho = request.path
        if not caminho.startswith('/api/') or caminho.startswith(IGNORADAS):
            return False
        if resposta.status_code >= 400:
            return False
        if request.method == 'GET':
            return caminho.startswith(LEITURAS_AUDITADAS)
        return request.method in ACOES

    def _registrar(self, request, resposta, corpo) -> None:
        operador = getattr(request, 'user', None)
        if operador is None or not getattr(operador, 'is_authenticated', False):
            operador = None

        partes = [p for p in request.path.split('/') if p]
        entidade = partes[1] if len(partes) > 1 else 'desconhecida'
        entidade_id = next((p for p in partes[2:] if len(p) >= 20), None)

        RegistroDeAuditoria(
            id=str(uuid.uuid4()),
            operador=operador,
            acao=ACOES.get(request.method, request.method),
            entidade=entidade,
            entidade_id=entidade_id,
            dados_depois=redigir(corpo) if corpo else None,
            endereco_ip=self._ip(request),
            navegador=(request.META.get('HTTP_USER_AGENT') or '')[:400] or None,
            criado_em=timezone.now(),
        ).save(force_insert=True)

    def _ip(self, request) -> str | None:
        encaminhado = request.META.get('HTTP_X_FORWARDED_FOR')
        if encaminhado:
            return encaminhado.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
