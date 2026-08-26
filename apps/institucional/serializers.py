from rest_framework import serializers

from apps.institucional.models import Coordenacao, Demanda, Servico, Unidade


class CoordenacaoSerializer(serializers.ModelSerializer):
    superior = serializers.CharField(source='superior.sigla', read_only=True, default=None)

    class Meta:
        model = Coordenacao
        fields = ['id', 'nome', 'sigla', 'ativa', 'superior']


class UnidadeSerializer(serializers.ModelSerializer):
    coordenacao = serializers.CharField(source='coordenacao.sigla', read_only=True, default=None)
    nome_qualificado = serializers.CharField(read_only=True)

    class Meta:
        model = Unidade
        fields = [
            'id', 'nome', 'sigla', 'tipo', 'endereco', 'telefone',
            'coordenacao', 'nome_qualificado', 'ativa',
        ]


class DemandaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Demanda
        fields = ['id', 'nome', 'categoria', 'ativa']


class ServicoSerializer(serializers.ModelSerializer):
    unidade_nome = serializers.CharField(source='unidade.nome', read_only=True)
    demanda_nome = serializers.CharField(source='demanda.nome', read_only=True, default=None)

    class Meta:
        model = Servico
        fields = ['id', 'nome', 'descricao', 'unidade', 'unidade_nome', 'demanda_nome', 'ativo']


class NovaUnidadeSerializer(serializers.ModelSerializer):
    coordenacao_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Unidade
        fields = ['nome', 'sigla', 'tipo', 'endereco', 'telefone', 'coordenacao_id']


class NovoServicoSerializer(serializers.ModelSerializer):
    unidade_id = serializers.CharField(required=True, allow_blank=False)
    demanda_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Servico
        fields = ['nome', 'descricao', 'unidade_id', 'demanda_id']
