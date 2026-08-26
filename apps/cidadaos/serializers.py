from rest_framework import serializers

from apps.cidadaos.models import Cidadao


class CidadaoNaListaSerializer(serializers.ModelSerializer):
    """
    O que aparece numa listagem.

    Deliberadamente enxuto: prontuário, socioeconômico e anexos não trafegam em
    lista. Quem precisa do detalhe abre o cadastro, e essa abertura fica na
    trilha de auditoria — o que uma listagem completa esconderia.
    """

    class Meta:
        model = Cidadao
        fields = ['id', 'nome', 'cpf', 'nascimento', 'bairro', 'cidade']


class CidadaoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cidadao
        fields = [
            'id', 'nome', 'cpf', 'nis', 'rg', 'email', 'telefone',
            'nascimento', 'sexo', 'naturalidade', 'escolaridade',
            'identidade_de_genero', 'raca', 'tem_deficiencia', 'estado_civil',
            'endereco', 'bairro', 'cidade', 'uf', 'cep',
            'documentos', 'endereco_detalhado', 'socioeconomico',
            'membros_da_familia', 'anexos', 'observacoes',
            'autoriza_imagem', 'imagem_revogada_em', 'consentiu_tefe_cidadao_em',
            'acao_itinerante', 'criado_em', 'atualizado_em',
        ]
        read_only_fields = ['id', 'criado_em', 'atualizado_em']


class EntradaDoHistoricoSerializer(serializers.Serializer):
    quando = serializers.DateTimeField()
    unidade = serializers.CharField()
    o_que = serializers.CharField()
    detalhe = serializers.CharField(allow_null=True)
    quem_atendeu = serializers.CharField(allow_null=True)
    no_mes_corrente = serializers.BooleanField()
    e_de_outra_unidade = serializers.BooleanField()


class NovoCidadaoSerializer(serializers.ModelSerializer):
    """
    Cadastro completo, feito na recepção.

    `criar_acesso_tefe_cidadao` vem marcado por padrão: a conta no Tefé Cidadão
    é o que permite à pessoa acompanhar depois o que foi pedido no CRAS.
    `consentimento` é a confirmação de que o termo foi lido para ela — criar
    conta de identidade para alguém sem que a pessoa saiba não é aceitável.
    """

    # Declarado à mão porque o modelo permite nulo — herança do tempo em que o
    # e-mail era opcional. Sem isto, omitir o campo passaria sem validação, e o
    # cadastro nasceria sem o login que a pessoa vai usar no Tefé Cidadão.
    email = serializers.CharField(required=True, allow_blank=False, allow_null=False)

    criar_acesso_tefe_cidadao = serializers.BooleanField(default=True)
    consentimento = serializers.BooleanField(default=False)
    acao_itinerante_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    class Meta:
        model = Cidadao
        fields = [
            'nome', 'cpf', 'nis', 'rg', 'email', 'telefone', 'nascimento', 'sexo',
            'naturalidade', 'escolaridade', 'identidade_de_genero', 'raca',
            'tem_deficiencia', 'estado_civil', 'endereco', 'bairro', 'cidade', 'uf', 'cep',
            'documentos', 'endereco_detalhado', 'socioeconomico', 'membros_da_familia',
            'observacoes', 'autoriza_imagem',
            'criar_acesso_tefe_cidadao', 'consentimento', 'acao_itinerante_id',
        ]

    def validate(self, dados):
        if dados.get('criar_acesso_tefe_cidadao') and not dados.get('consentimento'):
            raise serializers.ValidationError({
                'consentimento': 'Confirme que o termo foi lido para o cidadão, '
                                 'ou desmarque a criação do acesso.'
            })
        return dados
