"""
O cidadão atendido pela rede de assistência social.

Os dados pessoais moram em colunas cifradas, com um índice cego ao lado para
que a busca por CPF, NIS ou e-mail não exija decifrar a tabela inteira. As
colunas em texto puro seguem no esquema por herança do período anterior à
cifragem — são lidas, mas não recebem valor novo.
"""
from django.db import models
import re

from apps.cidadaos.campos import CampoCifrado
from apps.comum import cripto


class GerenciadorDeCidadaos(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(excluido_em__isnull=True)

    def por_documento(self, termo: str):
        """
        Busca por CPF, NIS ou e-mail.

        Com a cifragem ligada, compara índice cego com índice cego: um HMAC do
        valor normalizado, que encontra a pessoa em consulta indexada sem
        decifrar linha alguma.

        Com a cifragem desligada — ambiente de desenvolvimento, ou base ainda
        não migrada — não há índice gravado, e a comparação é direta na coluna.
        Sem esse caminho a busca devolveria vazio em silêncio, que é pior do que
        falhar: o atendente concluiria que a pessoa não tem cadastro.
        """
        termo = (termo or '').strip()
        if not termo:
            return self.none()

        apenas_digitos = re.sub(r'\D+', '', termo)
        termos = {termo}
        if apenas_digitos:
            termos.add(apenas_digitos)

        if not cripto.habilitada():
            return self.filter(
                models.Q(cpf__in=termos)
                | models.Q(nis__in=termos)
                | models.Q(email__iexact=termo)
            )

        indices = [cripto.indice_cego(item) for item in termos]
        return self.filter(
            models.Q(cpf_indice__in=indices)
            | models.Q(nis_indice__in=indices)
            | models.Q(email_indice=cripto.indice_cego(termo))
        )


class Cidadao(models.Model):
    class Sexo(models.TextChoices):
        MASCULINO = 'MASCULINO', 'Masculino'
        FEMININO = 'FEMININO', 'Feminino'
        NAO_BINARIO = 'NAO_BINARIO', 'Não binário'
        OUTRO = 'OUTRO', 'Outro'
        NAO_INFORMADO = 'NAO_INFORMADO', 'Não informado'

    id = models.TextField(primary_key=True)
    nome = models.TextField(db_column='name')

    # Identificado no atendimento offline antes de existir id do servidor.
    id_local = models.TextField(db_column='localId', unique=True, blank=True, null=True)

    # ─── Dados pessoais cifrados ───
    cpf = CampoCifrado(db_column='cpfEncrypted', indice='cpfHash', blank=True, null=True)
    cpf_indice = models.TextField(db_column='cpfHash', unique=True, blank=True, null=True)
    nis = CampoCifrado(db_column='nisEncrypted', indice='nisHash', blank=True, null=True)
    nis_indice = models.TextField(db_column='nisHash', blank=True, null=True)
    email = CampoCifrado(db_column='emailEncrypted', indice='emailHash', blank=True, null=True)
    email_indice = models.TextField(db_column='emailHash', unique=True, blank=True, null=True)
    rg = CampoCifrado(db_column='rgEncrypted', blank=True, null=True)
    telefone = CampoCifrado(db_column='phoneEncrypted', blank=True, null=True)
    endereco = CampoCifrado(db_column='addressEncrypted', blank=True, null=True)

    # ─── Demais dados do cadastro ───
    nascimento = models.DateTimeField(db_column='birthDate', blank=True, null=True)
    sexo = models.TextField(db_column='gender', blank=True, null=True)
    naturalidade = models.TextField(db_column='naturality', blank=True, null=True)
    escolaridade = models.TextField(db_column='education', blank=True, null=True)
    identidade_de_genero = models.TextField(db_column='genderIdentity', blank=True, null=True)
    raca = models.TextField(db_column='race', blank=True, null=True)
    tem_deficiencia = models.BooleanField(db_column='hasDisability', blank=True, null=True)
    estado_civil = models.TextField(db_column='maritalStatus', blank=True, null=True)

    bairro = models.TextField(db_column='neighborhood', blank=True, null=True)
    cidade = models.TextField(db_column='city', blank=True, null=True)
    uf = models.TextField(db_column='state', blank=True, null=True)
    cep = models.TextField(db_column='zipCode', blank=True, null=True)
    observacoes = models.TextField(db_column='notes', blank=True, null=True)

    documentos = models.JSONField(db_column='documentData', blank=True, null=True)
    endereco_detalhado = models.JSONField(db_column='addressData', blank=True, null=True)
    socioeconomico = models.JSONField(db_column='socioeconomicData', blank=True, null=True)
    ingresso = models.JSONField(db_column='entryData', blank=True, null=True)
    membros_da_familia = models.JSONField(db_column='familyMembers', blank=True, null=True)
    termo_de_responsabilidade = models.JSONField(db_column='responsibilityTerm', blank=True, null=True)
    anexos = models.JSONField(db_column='attachedDocuments', blank=True, null=True)

    # ─── Consentimentos ───
    #
    # Guardados como data, e nao apenas como sim/nao: o Art. 8, parágrafo 6 da
    # LGPD exige poder demonstrar que o consentimento era válido — e para isso é
    # preciso saber quando foi dado. A revogação fica em campo separado de
    # `autoriza_imagem = False` justamente para distinguir "nunca autorizou" de
    # "autorizou e revogou depois".
    autoriza_imagem = models.BooleanField(db_column='imageAuthorization', blank=True, null=True)
    imagem_aceita_em = models.DateTimeField(db_column='imageAuthorizationAcceptedAt', blank=True, null=True)
    imagem_responsavel = models.TextField(db_column='imageAuthorizationResponsible', blank=True, null=True)
    imagem_revogada_em = models.DateTimeField(db_column='imageAuthorizationRevokedAt', blank=True, null=True)
    consentiu_tefe_cidadao_em = models.DateTimeField(db_column='tefeCidadaoConsentAt', blank=True, null=True)

    situacao_beneficiario = models.TextField(db_column='beneficiarySituation', blank=True, null=True)
    atualizado_por = models.TextField(db_column='updatedByName', blank=True, null=True)
    sincronizado = models.BooleanField(db_column='synchronized', default=True)
    situacao_sincronizacao = models.TextField(db_column='syncStatus', blank=True, null=True)

    # Preenchido quando o registro nasceu numa ação itinerante, e não na sede.
    # Nulo é o caso comum: atendimento na própria unidade.
    acao_itinerante = models.ForeignKey(
        'atendimentos.AcaoItinerante', models.DO_NOTHING, db_column='itinerantActionId',
        blank=True, null=True, related_name='cidadaos',
    )

    familia_id = models.TextField(db_column='familyId', blank=True, null=True)
    ativo = models.BooleanField(db_column='isActive', default=True)
    criado_em = models.DateTimeField(db_column='createdAt')
    atualizado_em = models.DateTimeField(db_column='updatedAt')
    excluido_em = models.DateTimeField(db_column='deletedAt', blank=True, null=True)

    objects = models.Manager()
    vigentes = GerenciadorDeCidadaos()

    class Meta:
        managed = True
        db_table = 'citizens'
        verbose_name = 'cidadão'
        verbose_name_plural = 'cidadãos'
        ordering = ['nome']

    def __str__(self) -> str:
        return self.nome

    def save(self, *args, **kwargs):
        """Mantém os índices cegos coerentes com os valores cifrados."""
        if cripto.habilitada():
            self.cpf_indice = cripto.indice_cego(self.cpf)
            self.nis_indice = cripto.indice_cego(self.nis)
            self.email_indice = cripto.indice_cego(self.email)

            campos = kwargs.get('update_fields')
            if campos is not None:
                indices = {'cpf': 'cpf_indice', 'nis': 'nis_indice', 'email': 'email_indice'}
                kwargs['update_fields'] = list(campos) + [
                    indices[c] for c in campos if c in indices
                ]

        super().save(*args, **kwargs)
