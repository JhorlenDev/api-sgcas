from rest_framework import serializers

from apps.auditoria.models import RegistroDeAuditoria


class RegistroDeAuditoriaSerializer(serializers.ModelSerializer):
    """
    A trilha como a tela a le.

    Os nomes de saida sao os que a consulta ja usava antes de haver serializer
    (`quando`, `quem`, `registro`, `dados`) — mudar agora quebraria quem
    consome sem ganhar nada.

    `dados_antes` nao sai daqui: o valor anterior de um campo e util na
    apuracao, mas expo-lo na listagem geral e distribuir o dado pessoal que a
    edicao justamente removeu.
    """

    quando = serializers.DateTimeField(source='criado_em', read_only=True)
    quem = serializers.CharField(source='operador.nome', read_only=True, default=None)
    quem_id = serializers.CharField(source='operador_id', read_only=True, default=None)
    registro = serializers.CharField(source='entidade_id', read_only=True, default=None)
    dados = serializers.JSONField(source='dados_depois', read_only=True)
    ip = serializers.CharField(source='endereco_ip', read_only=True, default=None)

    class Meta:
        model = RegistroDeAuditoria
        fields = ['id', 'quando', 'quem', 'quem_id', 'acao', 'entidade', 'registro', 'dados', 'ip']
