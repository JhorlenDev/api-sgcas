"""
Paginacao e filtros das listagens — fonte unica.

Antes, cada listagem se protegia com um corte fixo no fim da consulta
(`[:100]`, `[:200]`, `[:50]`). O corte evita a resposta gigante, mas nao e
paginacao: quem chama nao sabe que existe mais coisa, nao tem como pedir a
proxima pagina, e o total que a tela mostra passa a ser o tamanho do corte. Numa
base municipal isso vira numero errado na tela — 100 casos exibidos como se
fossem os 220 mil que existem.

O envelope resolve as tres coisas de uma vez:

    {"itens": [...], "total": 220065, "pagina": 1, "por_pagina": 25, "paginas": 8803}

`total` e o numero de verdade, contado com os mesmos filtros da consulta. E o
que permite a tela dizer "1-25 de 220.065" em vez de inventar.

O limite maximo por pagina continua existindo: paginacao sem teto e o corte de
antes com outro nome, porque `?limit=999999` traz a tabela inteira.
"""
from __future__ import annotations

from datetime import date, datetime

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

LIMITE_PADRAO = 25
LIMITE_MAXIMO = 100


def _inteiro(request, nome: str, padrao: int, minimo: int, maximo: int) -> int:
    """
    Le um parametro numerico recusando lixo em vez de cair para o padrao.

    Silenciar `?page=abc` faria a tela mostrar a pagina 1 achando que mostra
    outra — o tipo de erro que so aparece quando alguem confere o numero.
    """
    bruto = request.query_params.get(nome)
    if bruto in (None, ''):
        return padrao
    try:
        valor = int(bruto)
    except (TypeError, ValueError):
        raise ValidationError({nome: f'Precisa ser um número inteiro. Recebido: "{bruto}".'})
    if valor < minimo:
        raise ValidationError({nome: f'Precisa ser no mínimo {minimo}.'})
    return min(valor, maximo)


def paginar(consulta: QuerySet, request, serializer, *, padrao: int = LIMITE_PADRAO,
            maximo: int = LIMITE_MAXIMO, contexto: dict | None = None) -> dict:
    """
    Envelope paginado de uma consulta.

    `total` sai de um `count()` com os mesmos filtros — nao do tamanho da
    fatia. E o unico jeito de a tela saber quantos registros existem de fato.
    """
    por_pagina = _inteiro(request, 'limit', padrao, 1, maximo)
    pagina = _inteiro(request, 'page', 1, 1, 10_000_000)

    total = consulta.count()
    paginas = max((total + por_pagina - 1) // por_pagina, 1)
    inicio = (pagina - 1) * por_pagina
    fatia = consulta[inicio:inicio + por_pagina]

    return {
        'itens': serializer(fatia, many=True, context=contexto or {}).data,
        'total': total,
        'pagina': pagina,
        'por_pagina': por_pagina,
        'paginas': paginas,
    }


def filtrar_iguais(consulta: QuerySet, request, mapa: dict[str, str]) -> QuerySet:
    """
    Aplica os filtros de igualdade presentes na query string.

    `mapa` liga o nome do parametro ao campo do modelo — `{'situacao':
    'situacao', 'unidade': 'unidade_id'}`. Parametro ausente ou vazio nao filtra;
    filtrar por vazio devolveria lista vazia e pareceria "nao ha registros".
    """
    for parametro, campo in mapa.items():
        valor = (request.query_params.get(parametro) or '').strip()
        if valor:
            consulta = consulta.filter(**{campo: valor})
    return consulta


def _data(valor: str, parametro: str) -> date:
    try:
        return datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        raise ValidationError({parametro: f'Use o formato AAAA-MM-DD. Recebido: "{valor}".'})


def filtrar_periodo(consulta: QuerySet, request, campo: str,
                    de: str = 'de', ate: str = 'ate') -> QuerySet:
    """
    Recorta por intervalo de datas, com as duas pontas inclusivas.

    A comparacao e feita no fuso do projeto (`__date`), e nao em UTC: quem filtra
    "hoje" numa unidade de Tefe espera o dia de Tefe. Em UTC, tudo que aconteceu
    depois das 20h local cairia no dia seguinte e sumiria do recorte.
    """
    inicio = (request.query_params.get(de) or '').strip()
    fim = (request.query_params.get(ate) or '').strip()

    if inicio:
        consulta = consulta.filter(**{f'{campo}__date__gte': _data(inicio, de)})
    if fim:
        consulta = consulta.filter(**{f'{campo}__date__lte': _data(fim, ate)})
    return consulta


def ordenar(consulta: QuerySet, request, permitidas: dict[str, tuple], padrao: str) -> QuerySet:
    """
    Ordena apenas pelo que a rota declara permitido.

    Repassar o parametro cru para o `order_by` deixaria qualquer autenticado
    ordenar por coluna interna — e, pior, provocar erro 500 com um nome de campo
    inexistente. A lista fechada tambem serve de documentacao do que a tela pode
    oferecer.
    """
    pedida = (request.query_params.get('ordenar') or '').strip() or padrao
    if pedida not in permitidas:
        raise ValidationError({
            'ordenar': f'Valor não suportado: "{pedida}". '
                       f'Use um de: {", ".join(sorted(permitidas))}.'
        })
    return consulta.order_by(*permitidas[pedida])


def hoje_local() -> date:
    return timezone.localtime(timezone.now()).date()
