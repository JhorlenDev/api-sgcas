"""
Redação da trilha de auditoria.

A trilha existe para provar **quem** alterou **o quê** e **quando** — não para
guardar uma segunda cópia do prontuário. Um log sem redação vira um banco
paralelo de dado sensível, tipicamente com menos controle de acesso que o
original.

Três níveis, por natureza do dado:

1. **Segredo** — apagado por completo. Senha ou token no log não tem uso legítimo.
2. **Relato** — substituído pelo tamanho. Texto livre onde o técnico descreve
   violência, saúde mental ou situação de rua é dado sensível (LGPD Art. 11).
   Guardar o tamanho preserva o que a auditoria precisa — saber que o campo
   mudou — sem replicar o conteúdo.
3. **Identificador** — mascarado em parte. Ver `***.***.***-45` basta para
   conferir de quem se trata; o CPF inteiro, não é necessário.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

SEGREDOS = frozenset({
    'password', 'senha', 'refresh_token', 'refreshtoken', 'access_token',
    'accesstoken', 'reset_token', 'resettoken', 'authorization', 'token',
    'client_secret', 'clientsecret', 'secret', 'jwt', 'id_token',
})

RELATOS = frozenset({
    'descricao', 'description', 'relato', 'observacao', 'observacoes',
    'notes', 'motivo', 'reason', 'justificativa', 'observations',
    'tipo_outro', 'typeother',
})

IDENTIFICADORES = frozenset({
    'cpf', 'nis', 'rg', 'email', 'telefone', 'phone', 'cep', 'zipcode',
    'endereco', 'address', 'logradouro', 'numero', 'complemento',
    'nome_original', 'nome_arquivo', 'caminho_local',
})


def _mascarar(chave: str, valor: str) -> str:
    digitos = re.sub(r'\D', '', valor)
    chave = chave.lower()

    if chave == 'email':
        nome, _, dominio = valor.partition('@')
        return f'{nome[:2]}***@{dominio}' if dominio else '[REDIGIDO]'
    if chave == 'cpf' and len(digitos) >= 2:
        return f'***.***.***-{digitos[-2:]}'
    if chave in {'telefone', 'phone'} and len(digitos) >= 4:
        return f'(**) *****-{digitos[-4:]}'
    if chave in {'cep', 'zipcode'} and len(digitos) >= 2:
        return f'{digitos[:2]}***-***'
    if chave == 'nis' and len(digitos) >= 3:
        return f'{digitos[:3]}********'
    return '[REDIGIDO]'


def redigir(valor):
    """Percorre a estrutura aplicando os três níveis."""
    if valor is None or isinstance(valor, (bool, int, float, Decimal)):
        return valor
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, (list, tuple)):
        return [redigir(item) for item in valor]
    if not isinstance(valor, dict):
        return valor

    saida = {}
    for chave, conteudo in valor.items():
        simples = str(chave).lower()

        if simples in SEGREDOS:
            saida[chave] = '[REDIGIDO]'
        elif simples in RELATOS:
            # Só o tamanho: a tela de logs continua apontando que o campo mudou,
            # sem expor o que o técnico escreveu sobre a pessoa.
            saida[chave] = (
                f'[REDIGIDO:{len(conteudo)}c]' if isinstance(conteudo, str)
                else redigir(conteudo)
            )
        elif simples in IDENTIFICADORES:
            saida[chave] = (
                _mascarar(simples, conteudo) if isinstance(conteudo, str) and conteudo
                else redigir(conteudo)
            )
        else:
            saida[chave] = redigir(conteudo)

    return saida
