from rest_framework import serializers

from apps.atendimentos.models import (
    AcaoItinerante,
    AtendimentoDeRecepcao,
    Caso,
    Encaminhamento,
    SenhaDaFila,
)


class CasoSerializer(serializers.ModelSerializer):
    cidadao_nome = serializers.CharField(source='cidadao.nome', read_only=True)
    unidade_nome = serializers.CharField(source='unidade.nome', read_only=True)
    tecnico_nome = serializers.CharField(source='tecnico.nome', read_only=True, default=None)
    servico_nome = serializers.CharField(source='servico.nome', read_only=True, default=None)

    class Meta:
        model = Caso
        fields = [
            'id', 'protocolo', 'situacao', 'prioridade', 'descricao',
            'cidadao', 'cidadao_nome', 'unidade', 'unidade_nome',
            'tecnico', 'tecnico_nome', 'servico', 'servico_nome',
            'aberto_em', 'fechado_em',
        ]


class SenhaSerializer(serializers.ModelSerializer):
    cidadao_nome = serializers.CharField(source='cidadao.nome', read_only=True)

    class Meta:
        model = SenhaDaFila
        fields = [
            'id', 'senha', 'situacao', 'prioridade', 'servico',
            'cidadao', 'cidadao_nome', 'chamado_em', 'criado_em',
        ]


class AtendimentoDeRecepcaoSerializer(serializers.ModelSerializer):
    cidadao_nome = serializers.CharField(source='cidadao.nome', read_only=True)
    unidade_nome = serializers.CharField(source='unidade.nome', read_only=True)
    atendido_por_nome = serializers.CharField(source='atendido_por.nome', read_only=True)
    caso_protocolo = serializers.CharField(source='caso.protocolo', read_only=True, default=None)
    observacao = serializers.SerializerMethodField()
    local_do_atendimento = serializers.SerializerMethodField()

    class Meta:
        model = AtendimentoDeRecepcao
        fields = [
            'id', 'cidadao', 'cidadao_nome', 'unidade_nome', 'atendido_por_nome',
            'demanda', 'desfecho', 'motivo', 'observacao', 'local_do_atendimento',
            'caso', 'caso_protocolo', 'criado_em',
        ]

    def get_observacao(self, obj):
        if obj.caso_id and obj.caso and obj.caso.descricao:
            return obj.caso.descricao
        return obj.motivo

    def get_local_do_atendimento(self, obj):
        if obj.desfecho == AtendimentoDeRecepcao.Desfecho.FINALIZADO:
            return obj.unidade.nome if obj.unidade_id else 'Recepção'
        if obj.caso_id and obj.caso and obj.caso.unidade_id:
            return obj.caso.unidade.nome
        return obj.unidade.nome if obj.unidade_id else 'Fila'


class AcaoItineranteSerializer(serializers.ModelSerializer):
    unidade_nome = serializers.CharField(source='unidade.nome', read_only=True)
    responsavel_nome = serializers.CharField(source='responsavel.nome', read_only=True)

    class Meta:
        model = AcaoItinerante
        fields = [
            'id', 'titulo', 'descricao', 'local', 'data', 'observacoes',
            'unidade', 'unidade_nome', 'responsavel', 'responsavel_nome', 'ativa',
        ]


class RegistroDeRecepcaoSerializer(serializers.Serializer):
    """
    O que a recepção envia ao concluir o atendimento no balcão.

    `motivo` é exigido quando se finaliza sem encaminhar: é o que a próxima
    unidade vai ler quando a pessoa aparecer lá.

    A prioridade aqui é a prioridade de entrada na fila. A avaliação técnica
    pode mudar depois, mas a recepção precisa sinalizar preferencial/urgente
    para ordenar a chamada inicial.

    `unidade_destino_id` permite encaminhar já no balcão: a pessoa é cadastrada
    aqui e entra na fila de lá, com os dados prontos, em vez de fazer a viagem
    e recomeçar do zero. O serviço escolhido tem de pertencer à unidade de
    destino — marcar serviço alheio como sendo da própria unidade não é
    permitido.
    """

    cidadao_id = serializers.CharField()
    servico_id = serializers.CharField(help_text='De /institutional/services')
    unidade_destino_id = serializers.CharField(
        required=False, allow_null=True, allow_blank=True,
        help_text='Só quando o atendimento seguirá em outra unidade.',
    )
    observacao = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    desfecho = serializers.ChoiceField(choices=AtendimentoDeRecepcao.Desfecho.choices)
    prioridade = serializers.ChoiceField(choices=Caso.Prioridade.choices, default=Caso.Prioridade.NORMAL)
    motivo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    servico = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    acao_itinerante_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, dados):
        finalizou = dados['desfecho'] == AtendimentoDeRecepcao.Desfecho.FINALIZADO
        if finalizou and not (dados.get('motivo') or '').strip():
            raise serializers.ValidationError({
                'motivo': 'Informe o motivo — ele aparece para a próxima unidade que atender esta pessoa.'
            })
        return dados


class EncaminhamentoSerializer(serializers.ModelSerializer):
    unidade_destino_nome = serializers.CharField(
        source='unidade_destino.nome', read_only=True, default=None
    )
    encaminhado_por_nome = serializers.CharField(source='encaminhado_por.nome', read_only=True)

    class Meta:
        model = Encaminhamento
        fields = [
            'id', 'caso', 'situacao', 'motivo', 'observacoes',
            'unidade_destino', 'unidade_destino_nome', 'destino_externo',
            'encaminhado_por_nome', 'criado_em',
        ]


class NovoEncaminhamentoSerializer(serializers.Serializer):
    """
    Um destino, e apenas um: interno ou externo.

    Aceitar os dois deixaria ambíguo para onde a pessoa deve ir, e é o tipo de
    ambiguidade que vira encaminhamento perdido.
    """

    unidade_destino_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    destino_externo = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    motivo = serializers.CharField()
    observacoes = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    def validate(self, dados):
        interno = (dados.get('unidade_destino_id') or '').strip()
        externo = (dados.get('destino_externo') or '').strip()
        if bool(interno) == bool(externo):
            raise serializers.ValidationError(
                'Informe a unidade de destino OU o destino externo — um dos dois.'
            )
        return dados


class ConclusaoSerializer(serializers.Serializer):
    relato = serializers.CharField()
    situacao = serializers.ChoiceField(
        choices=[(Caso.Situacao.CONCLUIDO, 'Concluído'), (Caso.Situacao.ENCAMINHADO, 'Encaminhado')],
        default=Caso.Situacao.CONCLUIDO,
    )


class ObservacaoDoCasoSerializer(serializers.Serializer):
    observacao = serializers.CharField()


class NaoCompareceuSerializer(serializers.Serializer):
    motivo = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class NovaAcaoItineranteSerializer(serializers.Serializer):
    titulo = serializers.CharField()
    local = serializers.CharField()
    data = serializers.DateTimeField()
    descricao = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    observacoes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
