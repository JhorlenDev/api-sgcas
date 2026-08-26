"""
Campo que se cifra sozinho ao gravar e se decifra ao ler.

O esquema guarda cada dado pessoal em ate tres colunas: a original em texto
puro (heranca do periodo anterior a cifragem), a cifrada e o indice cego. Quem
escreve regra de negocio nao deveria precisar saber disso — daí este campo, que
concentra o detalhe num lugar so.

A coluna em texto puro deixa de ser preenchida em cadastros novos: manter as
duas seria cifrar e, ao lado, guardar a resposta.
"""
from __future__ import annotations

from django.db import models

from apps.comum import cripto


class CampoCifrado(models.TextField):
    """
    Guarda cifrado, entrega decifrado.

    `indice` nomeia a coluna do HMAC, quando o campo precisa ser pesquisavel.
    Sem ela o valor fica ilegivel para busca — o que e o correto para dados que
    ninguem procura, como observacoes.
    """

    def __init__(self, *args, indice: str | None = None, **kwargs):
        self.indice = indice
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        nome, caminho, args, kwargs = super().deconstruct()
        if self.indice:
            kwargs['indice'] = self.indice
        return nome, caminho, args, kwargs

    def from_db_value(self, value, expression, connection):
        if value is None or not cripto.habilitada():
            return value
        return cripto.decifrar(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or not cripto.habilitada():
            return value
        return cripto.cifrar(value)
