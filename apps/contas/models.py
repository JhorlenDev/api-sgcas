"""
Operadores do sistema — servidores da assistencia social.

A conta local existe para as consultas e para a auditoria ter a quem se referir.
Ela nao e a fonte da verdade sobre acesso: papel e concessao vivem no Tefe
Cidadao, e sao espelhados aqui a cada entrada.
"""
from django.db import models

from apps.contas.papeis import VE_QUEM_ATENDEU, VE_TODAS_AS_UNIDADES, Papel


class Operador(models.Model):
    id = models.TextField(primary_key=True)
    email = models.TextField(unique=True)
    nome = models.TextField(db_column='name')
    cpf = models.TextField(blank=True, null=True)
    papel = models.TextField(db_column='role')
    ativo = models.BooleanField(db_column='isActive', default=True)
    unidade = models.ForeignKey(
        'institucional.Unidade',
        models.DO_NOTHING,
        db_column='unitId',
        blank=True,
        null=True,
        related_name='operadores',
    )
    keycloak_id = models.TextField(db_column='keycloakId', blank=True, null=True)
    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')
    excluido_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'users'
        verbose_name = 'operador'
        verbose_name_plural = 'operadores'
        ordering = ['nome']

    def __str__(self) -> str:
        return f'{self.nome} ({self.papel})'

    # O DRF so exige `is_authenticated` para tratar a requisicao como
    # autenticada. Quem chega aqui ja teve o token validado na borda.
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    @property
    def ve_todas_as_unidades(self) -> bool:
        return self.papel in VE_TODAS_AS_UNIDADES

    @property
    def ve_quem_atendeu(self) -> bool:
        return self.papel in VE_QUEM_ATENDEU

    @property
    def e_admin(self) -> bool:
        return self.papel == Papel.ADMIN


class PedidoDeAcesso(models.Model):
    """
    Pedido de quem entrou pelo Tefe Cidadao sem papel no SGCAS.

    Fica fora da tabela de operadores de proposito. Na versao antiga toda
    tentativa virava usuario com papel de leitura — o que enchia o cadastro de
    cidadao curioso e, pior, deixava um papel pendurado numa conta inativa:
    bastava alguem ligar o `ativo` sem pensar para a pessoa sair lendo
    prontuario. Aqui o solicitante nao tem papel nenhum ate ser aprovado.
    """

    class Situacao(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        APROVADO = 'APROVADO', 'Aprovado'
        RECUSADO = 'RECUSADO', 'Recusado'

    id = models.TextField(primary_key=True)
    keycloak_id = models.TextField(db_column='keycloakId')
    email = models.TextField()
    nome = models.TextField(db_column='name')
    situacao = models.TextField(db_column='status', default=Situacao.PENDENTE)
    pedido_em = models.DateTimeField(db_column='requestedAt')
    decidido_em = models.DateTimeField(db_column='decidedAt', blank=True, null=True)
    decidido_por = models.ForeignKey(
        'contas.Operador',
        models.DO_NOTHING,
        db_column='decidedById',
        blank=True,
        null=True,
        related_name='decisoes_de_acesso',
    )
    papel_concedido = models.TextField(db_column='grantedRole', blank=True, null=True)
    unidade_concedida = models.TextField(db_column='grantedUnitId', blank=True, null=True)

    class Meta:
        managed = True
        db_table = 'access_requests'
        verbose_name = 'pedido de acesso'
        verbose_name_plural = 'pedidos de acesso'
        ordering = ['pedido_em']

    def __str__(self) -> str:
        return f'{self.nome} <{self.email}> — {self.situacao}'
