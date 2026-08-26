"""
Cifragem dos dados pessoais do cidadao.

Duas operacoes distintas, com finalidades distintas:

- **cifrar/decifrar** protege o dado em repouso. Reversivel, com AES-256-GCM,
  que alem de cifrar detecta adulteracao.
- **indice_cego** permite *procurar* sem decifrar. E um HMAC: sempre igual para
  a mesma entrada, e irreversivel. Sem ele, buscar um CPF exigiria decifrar a
  tabela inteira a cada consulta.

O formato `v1:iv:tag:texto` e o mesmo gravado pelo backend anterior — trocar
implicaria reescrever todo o dado ja existente em producao. O prefixo de versao
existe justamente para permitir uma troca futura sem ambiguidade.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

VERSAO = 'v1'
TAMANHO_CHAVE = 32
TAMANHO_IV = 12
TAMANHO_TAG = 16


class ErroDeCripto(RuntimeError):
    pass


def _chave(nome: str) -> bytes:
    valor = getattr(settings, nome, '') or ''
    if not valor:
        raise ErroDeCripto(f'{nome} não está configurada')

    chave = base64.b64decode(valor)
    if len(chave) != TAMANHO_CHAVE:
        raise ErroDeCripto(f'{nome} precisa ser uma chave de 32 bytes em base64')
    return chave


def habilitada() -> bool:
    return getattr(settings, 'PII_ENCRYPTION_ENABLED', False)


def esta_cifrado(valor: str | None) -> bool:
    if not valor:
        return False
    partes = valor.split(':')
    return len(partes) == 4 and partes[0] == VERSAO


def cifrar(texto: str | None) -> str | None:
    if not texto:
        return texto
    if esta_cifrado(texto):
        return texto

    iv = os.urandom(TAMANHO_IV)
    # O AESGCM do `cryptography` devolve texto cifrado + tag concatenados; o
    # formato guarda os dois separados, como o backend anterior gravou.
    selado = AESGCM(_chave('PII_ENCRYPTION_KEY')).encrypt(iv, texto.encode(), None)
    cifrado, tag = selado[:-TAMANHO_TAG], selado[-TAMANHO_TAG:]

    return ':'.join([
        VERSAO,
        base64.b64encode(iv).decode(),
        base64.b64encode(tag).decode(),
        base64.b64encode(cifrado).decode(),
    ])


def decifrar(valor: str | None) -> str | None:
    if not valor:
        return valor
    if not esta_cifrado(valor):
        # Dado gravado antes da cifragem ser ligada. Devolver como esta permite
        # que a migracao seja gradual, em vez de exigir parada total.
        return valor

    _, iv_b64, tag_b64, texto_b64 = valor.split(':')
    try:
        iv = base64.b64decode(iv_b64)
        selado = base64.b64decode(texto_b64) + base64.b64decode(tag_b64)
        return AESGCM(_chave('PII_ENCRYPTION_KEY')).decrypt(iv, selado, None).decode()
    except Exception as erro:
        # Nao repassa o erro original: ele pode conter fragmento do dado.
        raise ErroDeCripto('Não foi possível decifrar o campo') from erro


def indice_cego(texto: str | None) -> str | None:
    """
    HMAC do valor normalizado — o que permite buscar sem decifrar.

    A normalizacao (sem espaco nas bordas, minusculas) e o que faz
    "  Joao@Exemplo.COM " e "joao@exemplo.com" caírem no mesmo indice. Sem ela,
    a busca falharia por diferenca de digitacao.
    """
    if not texto:
        return None
    normalizado = texto.strip().lower().encode()
    return hmac.new(_chave('PII_HMAC_KEY'), normalizado, hashlib.sha256).hexdigest()
