"""
Casos, fila e benefícios — o que acontece quando alguém é atendido.

O caso e a senha da fila pertencem à unidade que atendeu. O histórico deles,
não: a pessoa circula entre os CRAS, e quem a recebe precisa saber o que já foi
concedido em outro lugar. Ver `apps.atendimentos.historico`.
"""
from django.db import models


class RegistroVigenteManager(models.Manager):
    """
    Esconde o que foi removido logicamente.

    O nome do campo varia com o gênero do que ele descreve — `excluido_em` para
    caso e benefício, `excluida_em` para ação. Manter a concordância deixa o
    modelo legível em português, e o gerenciador se ajusta.
    """

    campo_de_exclusao = 'excluido_em'

    def get_queryset(self):
        return super().get_queryset().filter(**{f'{self.campo_de_exclusao}__isnull': True})


class AcoesVigentesManager(RegistroVigenteManager):
    campo_de_exclusao = 'excluida_em' 


class Caso(models.Model):
    class Situacao(models.TextChoices):
        EM_TRIAGEM = 'EM_TRIAGEM', 'Em triagem'
        EM_ATENDIMENTO = 'EM_ATENDIMENTO', 'Em atendimento'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'
        ENCAMINHADO = 'ENCAMINHADO', 'Encaminhado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    class Prioridade(models.TextChoices):
        BAIXA = 'BAIXA', 'Baixa'
        NORMAL = 'NORMAL', 'Normal'
        ALTA = 'ALTA', 'Alta'
        URGENTE = 'URGENTE', 'Urgente'

    id = models.TextField(primary_key=True)
    protocolo = models.TextField(db_column='protocol')
    situacao = models.TextField(db_column='status', default=Situacao.EM_TRIAGEM)
    prioridade = models.TextField(db_column='priority', default=Prioridade.NORMAL)
    descricao = models.TextField(db_column='description', blank=True, null=True)

    cidadao = models.ForeignKey(
        'cidadaos.Cidadao', models.DO_NOTHING, db_column='citizenId', related_name='casos'
    )
    unidade = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='unitId', related_name='casos'
    )
    tecnico = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='technicianId',
        blank=True, null=True, related_name='casos_atribuidos',
    )
    # Preenchido quando o registro nasceu numa ação itinerante, e não na sede.
    # Nulo é o caso comum: atendimento na própria unidade.
    acao_itinerante = models.ForeignKey(
        'atendimentos.AcaoItinerante', models.DO_NOTHING, db_column='itinerantActionId',
        blank=True, null=True, related_name='casos',
    )

    familia_id = models.TextField(db_column='familyId', blank=True, null=True)
    # A demanda e a categoria municipal, deduzida do servico escolhido. Fica
    # opcional porque um servico pode ainda nao ter categoria atribuida — e
    # perder o atendimento por causa disso seria pior do que somar depois.
    demanda_id = models.TextField(db_column='demandId', blank=True, null=True)
    servico = models.ForeignKey(
        'institucional.Servico', models.SET_NULL, db_column='serviceId',
        blank=True, null=True, related_name='casos',
    )

    aberto_em = models.DateTimeField(db_column='openedAt')
    fechado_em = models.DateTimeField(db_column='closedAt', blank=True, null=True)
    ativo = models.BooleanField(db_column='isActive', default=True)
    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')
    excluido_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    vigentes = RegistroVigenteManager()

    class Meta:
        managed = True
        db_table = 'cases'
        verbose_name = 'caso'
        verbose_name_plural = 'casos'
        ordering = ['-aberto_em']

    def __str__(self) -> str:
        return f'{self.protocolo} — {self.situacao}'


class SenhaDaFila(models.Model):
    class Situacao(models.TextChoices):
        AGUARDANDO = 'AGUARDANDO', 'Aguardando'
        CHAMADO = 'CHAMADO', 'Chamado'
        EM_ATENDIMENTO = 'EM_ATENDIMENTO', 'Em atendimento'
        ATENDIDO = 'ATENDIDO', 'Atendido'
        DESISTIU = 'DESISTIU', 'Desistiu'

    id = models.TextField(primary_key=True)
    senha = models.TextField(db_column='ticket')
    cidadao = models.ForeignKey(
        'cidadaos.Cidadao', models.DO_NOTHING, db_column='citizenId', related_name='senhas'
    )
    unidade = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='unitId', related_name='senhas'
    )
    prioridade = models.TextField(db_column='priority', default=Caso.Prioridade.NORMAL)
    situacao = models.TextField(db_column='status', default=Situacao.AGUARDANDO)
    servico = models.TextField(db_column='serviceName', blank=True, null=True)
    atendido_por = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='attendedById',
        blank=True, null=True, related_name='senhas_atendidas',
    )
    chamado_em = models.DateTimeField(db_column='calledAt', blank=True, null=True)
    finalizado_em = models.DateTimeField(db_column='finishedAt', blank=True, null=True)
    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')

    class Meta:
        managed = True
        db_table = 'queue_tickets'
        verbose_name = 'senha da fila'
        verbose_name_plural = 'senhas da fila'
        ordering = ['criado_em']

    def __str__(self) -> str:
        return f'{self.senha} — {self.situacao}'


class BeneficioEventual(models.Model):
    """
    Benefício concedido — cesta básica, auxílio funeral, passagem.

    É o registro que a recepção consulta antes de conceder de novo: alguém pode
    retirar no CRAS Centro e pedir o mesmo no CRAS Sul na semana seguinte.
    """

    class Tipo(models.TextChoices):
        """
        As categorias do SUAS: o benefício eventual é classificado pela
        *situação* que o justifica, não pelo item entregue. Uma cesta básica e
        uma passagem podem ambas ser vulnerabilidade temporária.
        """

        MORTE = 'SITUACAO_MORTE', 'Situação de morte'
        NASCIMENTO = 'SITUACAO_NASCIMENTO', 'Situação de nascimento'
        CALAMIDADE = 'SITUACAO_CALAMIDADE', 'Situação de calamidade'
        VULNERABILIDADE = 'SITUACAO_VULNERABILIDADE_TEMPORARIA', 'Vulnerabilidade temporária'
        OUTROS = 'OUTROS', 'Outros'

    id = models.TextField(primary_key=True)
    cidadao = models.ForeignKey(
        'cidadaos.Cidadao', models.DO_NOTHING, db_column='citizenId', related_name='beneficios'
    )
    nome_da_pessoa = models.TextField(db_column='personName')
    tipo = models.TextField(db_column='type')
    tipo_outro = models.TextField(db_column='typeOther', blank=True, null=True)
    descricao = models.TextField(db_column='description', blank=True, null=True)
    registrado_por = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='registeredById',
        related_name='beneficios_registrados',
    )
    unidade = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='unitId',
        blank=True, null=True, related_name='beneficios',
    )
    # Preenchido quando o registro nasceu numa ação itinerante, e não na sede.
    # Nulo é o caso comum: atendimento na própria unidade.
    acao_itinerante = models.ForeignKey(
        'atendimentos.AcaoItinerante', models.DO_NOTHING, db_column='itinerantActionId',
        blank=True, null=True, related_name='beneficios',
    )

    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')
    excluido_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    vigentes = RegistroVigenteManager()

    class Meta:
        managed = True
        db_table = 'eventual_benefits'
        verbose_name = 'benefício eventual'
        verbose_name_plural = 'benefícios eventuais'
        ordering = ['-criado_em']

    def __str__(self) -> str:
        return f'{self.get_tipo_display() if self.tipo in dict(self.Tipo.choices) else self.tipo}'


class AcaoItinerante(models.Model):
    """
    Atendimento fora da sede — em comunidade, distrito ou zona rural.

    Funciona como um local de atendimento temporário: a equipe vai até o
    Caiambe, monta a ação, e ali cadastra pessoas, abre casos e concede
    benefícios. Tudo isso pertence à unidade de origem, mas *aconteceu* na ação.

    A distinção existe para o relatório: sem ela não há como responder "quantas
    pessoas atendemos no Caiambe". Antes, a única medida era um número digitado
    à mão no campo `participantes` — que não se sustenta em prestação de contas,
    porque ninguém consegue reconstruir de onde ele veio.
    """

    id = models.TextField(primary_key=True)
    titulo = models.TextField(db_column='title')
    descricao = models.TextField(db_column='description', blank=True, null=True)
    local = models.TextField(db_column='location')
    data = models.DateTimeField(db_column='date')
    observacoes = models.TextField(db_column='observations', blank=True, null=True)

    # Contagem manual herdada. Mantida para o histórico já registrado; os
    # números novos saem da contagem real dos vínculos.
    participantes = models.IntegerField(db_column='attendees', default=0)

    responsavel = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='userId',
        related_name='acoes_itinerantes',
    )
    unidade = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='unitId',
        related_name='acoes_itinerantes',
    )

    ativa = models.BooleanField(db_column='isActive', default=True)
    criada_em = models.DateTimeField(db_column='createdAt')
    atualizada_em = models.DateTimeField(db_column='updatedAt')
    excluida_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    vigentes = AcoesVigentesManager()

    class Meta:
        managed = True
        db_table = 'itinerant_actions'
        verbose_name = 'ação itinerante'
        verbose_name_plural = 'ações itinerantes'
        ordering = ['-data']

    def __str__(self) -> str:
        return f'{self.titulo} — {self.local}'

    def balanco(self) -> dict:
        """
        O que efetivamente aconteceu na ação, contado dos vínculos.

        É o que a prestação de contas precisa: números que se pode auditar até
        o registro individual, em vez de um total que alguém digitou.
        """
        from apps.cidadaos.models import Cidadao

        return {
            'cidadaos_cadastrados': Cidadao.vigentes.filter(acao_itinerante=self).count(),
            'casos_abertos': Caso.vigentes.filter(acao_itinerante=self).count(),
            'beneficios_concedidos': BeneficioEventual.vigentes.filter(acao_itinerante=self).count(),
        }


class AtendimentoDeRecepcao(models.Model):
    """
    Toda passagem pelo balcão vira um registro — inclusive a que termina em não.

    Existe porque a negativa também é atendimento. Sem registrá-la, o mesmo
    pedido volta na semana seguinte, em outra unidade, sem rastro — que é a
    situação que motivou o histórico municipal. Aqui fica quem atendeu, o que
    foi pedido, o que se decidiu e por quê.

    Separado de `Caso` de propósito: um caso é acompanhamento que segue no
    tempo; isto é o registro do contato. Confundir os dois inflaria a contagem
    de casos com atendimentos que se resolveram em cinco minutos no balcão.
    """

    class Desfecho(models.TextChoices):
        ENCAMINHADO = 'ENCAMINHADO', 'Encaminhado para a fila'
        FINALIZADO = 'FINALIZADO', 'Finalizado na recepção'

    id = models.TextField(primary_key=True)
    cidadao = models.ForeignKey(
        'cidadaos.Cidadao', models.DO_NOTHING, db_column='citizenId',
        related_name='atendimentos_de_recepcao',
    )
    unidade = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='unitId',
        related_name='atendimentos_de_recepcao',
    )
    atendido_por = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='attendedById',
        related_name='atendimentos_de_recepcao',
    )
    acao_itinerante = models.ForeignKey(
        'atendimentos.AcaoItinerante', models.DO_NOTHING, db_column='itinerantActionId',
        blank=True, null=True, related_name='atendimentos_de_recepcao',
    )

    demanda = models.TextField(db_column='demand')
    desfecho = models.TextField(db_column='outcome')

    # Obrigatório quando o desfecho é FINALIZADO: é a explicação que aparece
    # para a próxima unidade que atender esta pessoa.
    motivo = models.TextField(db_column='reason', blank=True, null=True)

    caso = models.ForeignKey(
        'atendimentos.Caso', models.DO_NOTHING, db_column='caseId',
        blank=True, null=True, related_name='atendimentos_de_recepcao',
    )

    criado_em = models.DateTimeField(db_column='createdAt', auto_now_add=True)

    class Meta:
        managed = True
        db_table = 'reception_visits'
        verbose_name = 'atendimento de recepção'
        verbose_name_plural = 'atendimentos de recepção'
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['cidadao', 'criado_em'], name='recepcao_cidadao_data_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.cidadao_id} — {self.desfecho}'


class Encaminhamento(models.Model):
    """
    Quando o caso precisa de outro serviço — outra unidade ou fora da rede.

    O destino pode ser interno (outro CRAS, o CREAS) ou externo (Conselho
    Tutelar, saúde, Defensoria). São coisas diferentes: o interno precisa
    *chegar* na unidade de destino e aparecer para a equipe de lá; o externo é
    registro de que a pessoa foi orientada a procurar outro órgão.

    Por isso os dois campos: `unidade_destino` quando é da rede, e
    `destino_externo` quando não é. Sem o primeiro, encaminhar para outro CRAS
    viraria um texto que ninguém do outro lado jamais leria.
    """

    class Situacao(models.TextChoices):
        PENDENTE = 'PENDENTE', 'Pendente'
        ACEITO = 'ACEITO', 'Aceito'
        RECUSADO = 'RECUSADO', 'Recusado'
        CONCLUIDO = 'CONCLUIDO', 'Concluído'

    id = models.TextField(primary_key=True)
    caso = models.ForeignKey(
        'atendimentos.Caso', models.DO_NOTHING, db_column='caseId',
        related_name='encaminhamentos',
    )
    encaminhado_por = models.ForeignKey(
        'contas.Operador', models.DO_NOTHING, db_column='referredById',
        related_name='encaminhamentos_feitos',
    )
    unidade_destino = models.ForeignKey(
        'institucional.Unidade', models.DO_NOTHING, db_column='targetUnitId',
        blank=True, null=True, related_name='encaminhamentos_recebidos',
    )
    destino_externo = models.TextField(db_column='targetEntity')
    motivo = models.TextField(db_column='reason')
    situacao = models.TextField(db_column='status', default=Situacao.PENDENTE)
    observacoes = models.TextField(db_column='notes', blank=True, null=True)
    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')

    class Meta:
        managed = True
        db_table = 'referrals'
        verbose_name = 'encaminhamento'
        verbose_name_plural = 'encaminhamentos'
        ordering = ['-criado_em']

    def __str__(self) -> str:
        destino = self.unidade_destino.nome if self.unidade_destino_id else self.destino_externo
        return f'{self.caso_id} → {destino}'

    @property
    def e_interno(self) -> bool:
        return self.unidade_destino_id is not None
