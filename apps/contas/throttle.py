"""
Rate limiting para endpoints de autenticacao.

Os endpoints de login/callback sao Django views, nao DRF, entao nao se beneficiam
do throttling configurado no REST_FRAMEWORK. Este middleware aplica limite
especifico: 10 requisicoes por minuto por IP para rotas de auth.
"""
from __future__ import annotations

import time

from django.core.cache import cache
from django.http import JsonResponse

LIMITES = {
    '/api/auth/keycloak/login': 10,
    '/api/auth/keycloak/callback': 10,
    '/api/auth/access-request/resend': 5,
}

JANELA = 60  # segundos


def _chave(ip: str, rota: str) -> str:
    return f'throttle:{rota}:{ip}'


class ThrottleAuth:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'GET' and request.method != 'POST':
            return self.get_response(request)

        rota = None
        for padrao, _ in LIMITES.items():
            if request.path == padrao:
                rota = padrao
                break

        if rota is None:
            return self.get_response(request)

        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        if not ip:
            ip = request.META.get('REMOTE_ADDR', '0.0.0.0')

        chave = _chave(ip, rota)
        limite = LIMITES[rota]

        count = cache.get(chave, 0)
        if count >= limite:
            return JsonResponse(
                {'erro': 'Muitas requisicoes. Aguarde e tente novamente.'},
                status=429,
            )

        cache.set(chave, count + 1, JANELA)
        return self.get_response(request)
