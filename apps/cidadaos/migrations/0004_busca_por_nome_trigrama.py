"""
Índice de trigrama para a busca por nome.

A recepção procura o cidadão por parte do nome, e a consulta é
`name ILIKE '%termo%'`. Índice B-tree não serve para isso: ele ordena por
prefixo, e o curinga à esquerda o torna inútil. Numa base municipal a busca
passa a varrer o cadastro inteiro a cada tecla — medimos 147 ms descartando
98.536 linhas em 100 mil cadastros.

`pg_trgm` resolve quebrando o texto em trigramas e indexando-os num GIN, que é
o que permite casar pedaço no meio da palavra.

**Requisito de infraestrutura:** `CREATE EXTENSION` exige privilégio elevado no
Postgres. Em serviço gerenciado, `pg_trgm` costuma estar na lista de extensões
liberadas, mas pode precisar ser habilitado pelo painel antes de migrar. Se esta
migration falhar por permissão, é isso — e não um erro do esquema.

`CONCURRENTLY` mantém a tabela gravável enquanto o índice é construído, ao custo
de a migration não poder rodar dentro de transação (`atomic = False`).
"""
from django.db import migrations


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('cidadaos', '0003_cidadao_cidadao_atualizado_em_idx'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS pg_trgm;',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                'CREATE INDEX CONCURRENTLY IF NOT EXISTS cidadao_nome_trgm_idx '
                'ON citizens USING gin (name gin_trgm_ops);'
            ),
            reverse_sql='DROP INDEX CONCURRENTLY IF EXISTS cidadao_nome_trgm_idx;',
        ),
    ]
