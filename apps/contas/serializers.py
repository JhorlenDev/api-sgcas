from rest_framework import serializers

from apps.contas.models import Operador, PedidoDeAcesso


class UnidadeResumidaSerializer(serializers.Serializer):
    id = serializers.CharField()
    nome = serializers.CharField()


class OperadorSerializer(serializers.ModelSerializer):
    unidade = UnidadeResumidaSerializer(read_only=True)

    class Meta:
        model = Operador
        fields = ['id', 'nome', 'email', 'papel', 'ativo', 'unidade']


class PedidoDeAcessoSerializer(serializers.ModelSerializer):
    decidido_por = serializers.CharField(source='decidido_por.nome', read_only=True, default=None)

    class Meta:
        model = PedidoDeAcesso
        fields = [
            'id', 'nome', 'email', 'situacao', 'pedido_em',
            'decidido_em', 'decidido_por', 'papel_concedido',
        ]


class DecisaoDeAcessoSerializer(serializers.Serializer):
    """Corpo da aprovação: o papel a conceder e a unidade de lotação."""

    papel = serializers.CharField()
    unidade_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class OperadorNaListaSerializer(serializers.ModelSerializer):
    unidade_nome = serializers.CharField(source='unidade.nome', read_only=True, default=None)

    class Meta:
        model = Operador
        fields = ['id', 'nome', 'email', 'papel', 'ativo', 'unidade', 'unidade_nome']


class AtualizarOperadorSerializer(serializers.Serializer):
    """
    O que o SGCAS ainda administra sobre um operador.

    Papel não entra: quem concede é o Tefé Cidadão, e o valor local é apenas o
    espelho do que veio no token. Aceitar `papel` aqui criaria uma segunda fonte
    de verdade, sobrescrita no próximo acesso da pessoa — uma alteração que
    parece ter funcionado e se desfaz sozinha.

    E-mail idem: é a chave que casa a conta local com a do realm.
    """

    nome = serializers.CharField(required=False)
    cpf = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    unidade_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    ativo = serializers.BooleanField(required=False)


class AlterarPerfilOperadorSerializer(serializers.Serializer):
    """Troca o papel do operador no Keycloak e espelha no SGCAS."""

    papel = serializers.CharField()
