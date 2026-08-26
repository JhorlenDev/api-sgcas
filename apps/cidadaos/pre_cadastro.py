"""
Criação da conta do cidadão no Tefé Cidadão.

A conta nasce **sem senha**: quem a define é a própria pessoa, no primeiro
acesso, com um código enviado pelo SSO. O CRAS nunca vê nem cria senha de
ninguém — o que também evita a prática de anotar senha em papel.

Nada aqui pode derrubar o cadastro do cidadão. Atendimento presencial não pode
depender de o SSO estar no ar: se falhar, a pessoa já foi atendida e o registro
dela existe. O resultado volta para o atendente saber o que dizer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests
from django.conf import settings

TEMPO_LIMITE = 15
OBRIGATORIOS = ('cpf', 'email', 'telefone')


@dataclass(frozen=True)
class Resultado:
    situacao: str            # criado · ja_existe · incompleto · falhou · desligado
    mensagem: str | None = None
    faltando: tuple[str, ...] = ()


_token = {'valor': None, 'expira_em': 0.0}


def habilitado() -> bool:
    return bool(
        settings.PRECADASTRO_ENABLED
        and settings.PRECADASTRO_CLIENT_ID
        and settings.PRECADASTRO_CLIENT_SECRET
    )


def _base() -> str:
    return f'{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}'


def _obter_token() -> str:
    """
    Token da conta de serviço, reaproveitado enquanto vale.

    A documentação do SSO pede reaproveitamento explícito: num mutirão de
    cadastramento, pedir um token por pessoa faria do SSO o gargalo do
    atendimento. A margem de 30s evita usar um token que expira no caminho.
    """
    agora = time.monotonic()
    if _token['valor'] and agora < _token['expira_em']:
        return _token['valor']

    resposta = requests.post(
        f'{_base()}/protocol/openid-connect/token',
        data={
            'grant_type': 'client_credentials',
            'client_id': settings.PRECADASTRO_CLIENT_ID,
            'client_secret': settings.PRECADASTRO_CLIENT_SECRET,
        },
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    _token['valor'] = dados['access_token']
    _token['expira_em'] = agora + max(dados.get('expires_in', 300) - 30, 30)
    return _token['valor']


def criar(cidadao, unidade: str | None, operador: str | None) -> Resultado:
    if not habilitado():
        return Resultado('desligado')

    faltando = tuple(campo for campo in OBRIGATORIOS if not getattr(cidadao, campo, None))
    if faltando:
        return Resultado('incompleto', faltando=faltando)

    nome, *resto = (cidadao.nome or '').strip().split()
    endereco = cidadao.endereco_detalhado or {}

    corpo = {
        'cpf': cidadao.cpf,
        'nome': nome,
        'sobrenome': ' '.join(resto) or None,
        'email': cidadao.email,
        'telefone': cidadao.telefone,
        'data_nascimento': cidadao.nascimento.strftime('%d/%m/%Y') if cidadao.nascimento else None,
        'sexo': cidadao.sexo,
        'endereco_cep': cidadao.cep or endereco.get('cep'),
        'endereco_logradouro': cidadao.endereco or endereco.get('logradouro'),
        'endereco_numero': endereco.get('numero'),
        'endereco_bairro': cidadao.bairro or endereco.get('bairro'),
        'endereco_cidade': cidadao.cidade or endereco.get('cidade'),
        'endereco_estado': cidadao.uf or endereco.get('estado'),
        # Com um client de pré-cadastro compartilhado por várias secretarias, o
        # campo `origem` passa a ser o mesmo para todas: são estes dois campos
        # que permitem saber depois quem criou cada conta e de onde.
        'unidade': unidade,
        'operador': operador,
    }

    try:
        resposta = requests.post(
            f'{_base()}/pre-cadastro',
            json={k: v for k, v in corpo.items() if v is not None},
            headers={'Authorization': f'Bearer {_obter_token()}'},
            timeout=TEMPO_LIMITE,
        )
    except requests.RequestException as erro:
        return Resultado('falhou', mensagem=str(erro)[:200])

    if resposta.status_code in (200, 201):
        return Resultado(resposta.json().get('status', 'criado'))

    return Resultado('falhou', mensagem=f'HTTP {resposta.status_code}: {resposta.text[:160]}')
