from django.db import models


class RegistroDeAuditoria(models.Model):
    """
    Quem fez o quê, quando, e de onde.

    Leitura também é registrada quando o alvo é dado pessoal: abrir o prontuário
    de alguém é um ato que precisa ser demonstrável. Um sistema que só audita
    escrita não consegue responder "quem consultou os dados desta pessoa".
    """

    id = models.TextField(primary_key=True)
    operador = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='userId',
        blank=True, null=True, related_name='registros_de_auditoria',
    )
    acao = models.TextField(db_column='action')
    entidade = models.TextField(db_column='entity')
    entidade_id = models.TextField(db_column='entityId', blank=True, null=True)
    dados_antes = models.JSONField(db_column='oldData', blank=True, null=True)
    dados_depois = models.JSONField(db_column='newData', blank=True, null=True)
    endereco_ip = models.TextField(db_column='ipAddress', blank=True, null=True)
    navegador = models.TextField(db_column='userAgent', blank=True, null=True)
    criado_em = models.DateTimeField(db_column='createdAt')

    class Meta:
        managed = True
        db_table = 'audit_logs'
        verbose_name = 'registro de auditoria'
        verbose_name_plural = 'registros de auditoria'
        ordering = ['-criado_em']

    def __str__(self) -> str:
        return f'{self.acao} {self.entidade} por {self.operador_id}'
