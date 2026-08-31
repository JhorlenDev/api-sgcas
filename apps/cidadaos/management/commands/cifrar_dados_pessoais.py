"""
Cifra os dados pessoais que ficaram em texto puro antes da cifragem ser ligada.

Necessário porque ligar `PII_ENCRYPTION_ENABLED` sozinho não basta: a busca por
documento passa a comparar índice cego com índice cego, e as linhas gravadas
antes não têm índice nenhum. Sem este backfill elas somem da busca em silêncio
— o atendente conclui que a pessoa não tem cadastro e cadastra de novo.

Como funciona: com a cifragem ligada, ler um valor em texto puro devolve o
próprio texto (`decifrar` só age no formato `v1:`), e gravá-lo de volta o cifra
e preenche o índice. Reler e regravar cada cidadão é, portanto, todo o trabalho.

Idempotente: percorre só quem ainda tem coluna em texto puro, então rodar de
novo numa base já migrada não grava nada. Atualiza apenas as colunas de dado
pessoal, para não mexer em `atualizado_em` — essa data é do atendimento, não
da manutenção.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, connection, transaction

from apps.cidadaos.models import Cidadao
from apps.comum import cripto

# As colunas cifradas. O save() do modelo acrescenta sozinho os índices cegos
# correspondentes a cpf, nis e email.
CAMPOS = ['cpf', 'nis', 'email', 'rg', 'telefone', 'endereco']

LOTE = 500


class Command(BaseCommand):
    help = 'Cifra os dados pessoais gravados antes da cifragem ser ligada.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--simular', action='store_true',
            help='Relata quantos cadastros seriam cifrados, sem gravar.',
        )

    def handle(self, *args, **opcoes):
        if not cripto.habilitada():
            # Sem a cifragem ligada o save() não preenche índice, e o comando
            # gravaria texto puro de volta: trabalho nenhum, com a falsa
            # impressão de base migrada.
            raise CommandError(
                'PII_ENCRYPTION_ENABLED está desligada. Ligue-a (e configure '
                'PII_ENCRYPTION_KEY e PII_HMAC_KEY) antes de rodar este comando.'
            )

        # Confere as chaves antes de tocar na base: falhar no meio deixaria
        # parte das linhas cifrada e parte não.
        cripto.cifrar('teste-de-chave')
        cripto.indice_cego('teste-de-chave')

        pendentes = self._pks_em_texto_puro()
        total = Cidadao.objects.count()

        self.stdout.write(f'cadastros na base      : {total}')
        self.stdout.write(f'com dado em texto puro : {len(pendentes)}')

        if opcoes['simular']:
            self.stdout.write(self.style.WARNING('simulação — nada foi gravado'))
            return

        if not pendentes:
            self.stdout.write(self.style.SUCCESS('nada a fazer'))
            return

        cifrados = falhas = 0

        for cidadao in Cidadao.objects.filter(pk__in=pendentes).iterator(chunk_size=LOTE):
            try:
                # Por linha, e não em bloco único: um CPF duplicado na base não
                # pode desfazer o que já foi cifrado antes dele.
                with transaction.atomic():
                    cidadao.save(update_fields=CAMPOS)
                cifrados += 1
            except IntegrityError as erro:
                # Índice cego é determinístico: dois cadastros com o mesmo CPF
                # colidem na coluna única, duplicidade que a base em texto puro
                # tolerava por não ter índice.
                falhas += 1
                self.stdout.write(self.style.WARNING(f'  {cidadao.pk} ({cidadao.nome}): {erro}'))

        self.stdout.write('')
        self.stdout.write(f'cifrados : {cifrados}')
        if falhas:
            self.stdout.write(self.style.ERROR(
                f'falhas   : {falhas} — provável documento duplicado; '
                'resolva a duplicidade e rode de novo'
            ))
        else:
            self.stdout.write(self.style.SUCCESS('nenhuma falha'))

    def _pks_em_texto_puro(self) -> list[str]:
        """
        Ids cujos dados pessoais ainda não estão no formato `v1:`.

        Vai direto ao banco porque ler pelo modelo passaria por `from_db_value`,
        que decifra — e aí todo valor pareceria texto puro.
        """
        colunas = [Cidadao._meta.get_field(nome).column for nome in CAMPOS]
        condicao = ' OR '.join(
            f'("{c}" IS NOT NULL AND "{c}" <> \'\' AND "{c}" NOT LIKE %s)' for c in colunas
        )
        with connection.cursor() as cursor:
            cursor.execute(
                f'SELECT "id" FROM "{Cidadao._meta.db_table}" WHERE {condicao}',
                [f'{cripto.VERSAO}:%'] * len(colunas),
            )
            return [linha[0] for linha in cursor.fetchall()]
