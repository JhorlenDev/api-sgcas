"""
Coordenacoes e unidades da rede de assistencia social.

Os modelos sao escritos sobre as tabelas que ja existem: `managed = False` e
`db_table`/`db_column` apontando para o esquema atual. Nao ha migracao de dados,
e os dois backends podem ler o mesmo banco enquanto durar a transicao.

Os nomes em Python sao em portugues e legiveis; o mapeamento para as colunas em
camelCase fica isolado nos `db_column`, num lugar so.
"""
from django.db import models


class RegistroAtivoManager(models.Manager):
    """Esconde o que foi removido logicamente. Ver `Coordenacao.excluida_em`."""

    def get_queryset(self):
        return super().get_queryset().filter(excluida_em__isnull=True)


class Coordenacao(models.Model):
    id = models.TextField(primary_key=True)
    nome = models.TextField(db_column='name')
    sigla = models.TextField(db_column='code', unique=True)
    ativa = models.BooleanField(db_column='isActive', default=True)
    superior = models.ForeignKey(
        'self',
        models.DO_NOTHING,
        db_column='parent_id',
        blank=True,
        null=True,
        related_name='subordinadas',
    )
    criada_em = models.DateTimeField(db_column='createdAt')
    atualizada_em = models.DateTimeField(db_column='updatedAt')
    excluida_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    ativas = RegistroAtivoManager()

    class Meta:
        managed = True
        db_table = 'coordinations'
        verbose_name = 'coordenação'
        verbose_name_plural = 'coordenações'
        ordering = ['nome']

    def __str__(self) -> str:
        return f'{self.sigla} — {self.nome}'

    def raiz(self) -> 'Coordenacao':
        """
        Sobe a hierarquia ate a coordenacao de topo, que e a secretaria.

        Usar a coordenacao imediata daria o nivel errado: quem atende no CRAS
        Centro esta lotado em `CRAS-I`, e o rotulo sairia `CRAS-I/CRAS Centro`
        — ou o redundante `CREAS/CREAS`. Quem le a auditoria do Tefe Cidadao
        precisa saber a secretaria de origem, nao a subdivisao interna dela.

        O limite de saltos protege contra hierarquia ciclica gravada por engano:
        sem ele, um ciclo travaria o cadastro do cidadao com o atendente
        esperando na frente da pessoa.
        """
        atual = self
        for _ in range(10):
            if atual.superior_id is None:
                return atual
            atual = atual.superior
        return atual


class Unidade(models.Model):
    class Tipo(models.TextChoices):
        """Os valores aceitos pelo banco. Acolhimento institucional — Residência
        Inclusiva, ILPI — entra como ABRIGO, que é a modalidade existente."""

        CRAS = 'CRAS', 'CRAS'
        CREAS = 'CREAS', 'CREAS'
        CENTRO_POP = 'CENTRO_POP', 'Centro POP'
        ABRIGO = 'ABRIGO', 'Acolhimento institucional'
        SEDE = 'SEDE', 'Sede'
        OUTRO = 'OUTRO', 'Outro'

    id = models.TextField(primary_key=True)
    nome = models.TextField(db_column='name')
    sigla = models.TextField(db_column='code', unique=True)
    tipo = models.TextField(db_column='type')
    endereco = models.TextField(db_column='address', blank=True, null=True)
    telefone = models.TextField(db_column='phone', blank=True, null=True)
    coordenacao = models.ForeignKey(
        Coordenacao,
        models.DO_NOTHING,
        db_column='coordinationId',
        blank=True,
        null=True,
        related_name='unidades',
    )
    ativa = models.BooleanField(db_column='isActive', default=True)
    criada_em = models.DateTimeField(db_column='createdAt')
    atualizada_em = models.DateTimeField(db_column='updatedAt')
    excluida_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    ativas = RegistroAtivoManager()

    class Meta:
        managed = True
        db_table = 'units'
        verbose_name = 'unidade'
        verbose_name_plural = 'unidades'
        ordering = ['nome']

    def __str__(self) -> str:
        return self.nome

    def nome_qualificado(self) -> str:
        """
        `SIGLA/Unidade` — ex.: `SEMAS/CRAS Centro`.

        E o formato acordado para a auditoria do pre-cadastro no Tefe Cidadao.
        O prefixo existe porque o client de pre-cadastro e compartilhado por
        varias secretarias: sem ele, "Centro" da saude e "Centro" da assistencia
        social ficam indistinguiveis no registro.
        """
        if self.coordenacao is None:
            return self.nome
        return f'{self.coordenacao.raiz().sigla}/{self.nome}'


class Demanda(models.Model):
    """
    Catálogo do que se pode pedir na recepção.

    A classificação sai daqui, e não de texto livre: é o que a recepção escolhe
    ao encaminhar, e o que permite ao relatório dizer quantos casos de violação
    de direitos a rede atendeu. Texto digitado por cada atendente tornaria
    qualquer agregação impossível.
    """

    id = models.TextField(primary_key=True)
    nome = models.TextField(db_column='name')
    descricao = models.TextField(db_column='description', blank=True, null=True)
    categoria = models.TextField(db_column='category', blank=True, null=True)
    ativa = models.BooleanField(db_column='isActive', default=True)
    criada_em = models.DateTimeField(db_column='createdAt')
    atualizada_em = models.DateTimeField(db_column='updatedAt')

    class Meta:
        managed = True
        db_table = 'demands'
        verbose_name = 'demanda'
        verbose_name_plural = 'demandas'
        ordering = ['nome']

    def __str__(self) -> str:
        return self.nome


class Servico(models.Model):
    """
    O que uma unidade específica oferece.

    Diferente da `Demanda`, que é a categoria municipal: aqui é concreto e varia
    com a unidade. Cesta básica, na Residência Inclusiva, é "Alimentação e
    nutrição"; no CRAS é "Benefício Eventual". A recepcionista escolhe entre o
    que a *sua* unidade faz, em vez de encaixar tudo em cinco caixas amplas.

    A `demanda` amarra o serviço a uma categoria municipal. Sem ela o relatório
    da rede deixaria de fechar: "Alimentação e nutrição" e "Benefício Eventual"
    virariam coisas distintas, e ninguém conseguiria somar quantos benefícios a
    rede concedeu. Fica opcional para permitir cadastrar os serviços agora e
    categorizar depois — mas o que ficar sem categoria aparece separado no
    relatório, não some.
    """

    id = models.TextField(primary_key=True)
    unidade = models.ForeignKey(
        'institucional.Unidade', models.CASCADE, db_column='unitId', related_name='servicos'
    )
    nome = models.TextField(db_column='name')
    descricao = models.TextField(db_column='description', blank=True, null=True)
    demanda = models.ForeignKey(
        'institucional.Demanda', models.SET_NULL, db_column='demandId',
        blank=True, null=True, related_name='servicos',
    )
    ativo = models.BooleanField(db_column='isActive', default=True)
    criado_em = models.DateTimeField(db_column='createdAt', auto_now_add=True)
    atualizado_em = models.DateTimeField(db_column='updatedAt', auto_now=True)

    class Meta:
        managed = True
        db_table = 'unit_services'
        verbose_name = 'serviço'
        verbose_name_plural = 'serviços'
        ordering = ['unidade__nome', 'nome']
        constraints = [
            models.UniqueConstraint(fields=['unidade', 'nome'], name='servico_unico_por_unidade'),
        ]

    def __str__(self) -> str:
        return f'{self.unidade.nome} — {self.nome}'
