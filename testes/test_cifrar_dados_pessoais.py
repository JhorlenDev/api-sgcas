"""Backfill que cifra os dados pessoais gravados antes da cifragem ser ligada."""
import base64
import uuid
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.cidadaos.models import Cidadao
from apps.comum import cripto

CHAVE = base64.b64encode(b'0' * 32).decode()

CIFRAGEM_LIGADA = override_settings(
    PII_ENCRYPTION_ENABLED=True, PII_ENCRYPTION_KEY=CHAVE, PII_HMAC_KEY=CHAVE,
)


def grava_em_texto_puro(nome, cpf, excluido=False):
    """
    Insere direto no banco, como fazia a versão sem cifragem.

    Pelo modelo não dá: com a cifragem ligada o campo cifraria o valor, que é
    justamente o estado anterior que o teste precisa reproduzir.
    """
    agora = timezone.now()
    pk = str(uuid.uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            'INSERT INTO citizens ("id", "name", "cpfEncrypted", "createdAt",'
            ' "updatedAt", "deletedAt", "isActive", "synchronized")'
            ' VALUES (%s, %s, %s, %s, %s, %s, true, true)',
            [pk, nome, cpf, agora, agora, agora if excluido else None],
        )
    return pk


def coluna_bruta(pk, coluna='cpfEncrypted'):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT "{coluna}" FROM citizens WHERE "id" = %s', [pk])
        return cursor.fetchone()[0]


@CIFRAGEM_LIGADA
class Backfill(TestCase):
    def test_cifra_o_que_estava_em_texto_puro(self):
        pk = grava_em_texto_puro('Maria', '529.982.247-25')

        call_command('cifrar_dados_pessoais', stdout=StringIO())

        self.assertTrue(cripto.esta_cifrado(coluna_bruta(pk)))
        self.assertEqual(Cidadao.objects.get(pk=pk).cpf, '529.982.247-25')

    def test_preenche_o_indice_para_a_busca_encontrar(self):
        # O motivo do comando existir: sem índice o cadastro antigo some da
        # busca por documento assim que a cifragem é ligada.
        pk = grava_em_texto_puro('João', '529.982.247-25')
        self.assertFalse(Cidadao.vigentes.por_documento('529.982.247-25').exists())

        call_command('cifrar_dados_pessoais', stdout=StringIO())

        encontrados = Cidadao.vigentes.por_documento('529.982.247-25')
        self.assertEqual([c.pk for c in encontrados], [pk])

    def test_indexa_o_documento_na_forma_em_que_esta_gravado(self):
        # O indice cego e do valor como esta na coluna: gravado com pontuacao,
        # so a busca com pontuacao encontra. Vale igual para cadastro novo — o
        # backfill reproduz o comportamento do save(), nao um proprio.
        grava_em_texto_puro('Ana', '529.982.247-25')

        call_command('cifrar_dados_pessoais', stdout=StringIO())

        self.assertTrue(Cidadao.vigentes.por_documento('529.982.247-25').exists())
        self.assertFalse(Cidadao.vigentes.por_documento('52998224725').exists())

    def test_alcanca_cadastro_excluido_logicamente(self):
        # Excluído logicamente ainda guarda o dado pessoal da pessoa: deixá-lo
        # em texto puro manteria exatamente o que a cifragem quer evitar.
        pk = grava_em_texto_puro('Excluída', '111.444.777-35', excluido=True)

        call_command('cifrar_dados_pessoais', stdout=StringIO())

        self.assertTrue(cripto.esta_cifrado(coluna_bruta(pk)))

    def test_nao_mexe_na_data_de_atualizacao(self):
        pk = grava_em_texto_puro('Pedro', '529.982.247-25')
        antes = Cidadao.objects.get(pk=pk).atualizado_em

        call_command('cifrar_dados_pessoais', stdout=StringIO())

        self.assertEqual(Cidadao.objects.get(pk=pk).atualizado_em, antes)

    def test_rodar_de_novo_nao_regrava(self):
        pk = grava_em_texto_puro('Rita', '529.982.247-25')
        call_command('cifrar_dados_pessoais', stdout=StringIO())
        cifrado = coluna_bruta(pk)

        saida = StringIO()
        call_command('cifrar_dados_pessoais', stdout=saida)

        self.assertEqual(coluna_bruta(pk), cifrado)
        self.assertIn('nada a fazer', saida.getvalue())

    def test_simular_nao_grava(self):
        pk = grava_em_texto_puro('Carlos', '529.982.247-25')

        call_command('cifrar_dados_pessoais', '--simular', stdout=StringIO())

        self.assertFalse(cripto.esta_cifrado(coluna_bruta(pk)))

    def test_documento_duplicado_nao_impede_os_demais(self):
        # O índice cego é único; a base em texto puro tolerava a duplicidade.
        # A linha problemática é relatada, e o resto da base segue cifrado.
        grava_em_texto_puro('Duplicada A', '529.982.247-25')
        grava_em_texto_puro('Duplicada B', '529.982.247-25')
        ok = grava_em_texto_puro('Sem duplicata', '111.444.777-35')

        saida = StringIO()
        call_command('cifrar_dados_pessoais', stdout=saida)

        self.assertTrue(cripto.esta_cifrado(coluna_bruta(ok)))
        self.assertIn('falhas', saida.getvalue())


class SemCifragem(TestCase):
    @override_settings(PII_ENCRYPTION_ENABLED=False)
    def test_recusa_rodar_com_a_cifragem_desligada(self):
        # Rodaria gravando texto puro de volta e sem índice nenhum, dando a
        # falsa impressão de base migrada.
        with self.assertRaises(CommandError):
            call_command('cifrar_dados_pessoais', stdout=StringIO())
