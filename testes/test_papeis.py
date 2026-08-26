"""Precedência de papéis e leitura do token."""
import base64
import json

from django.test import SimpleTestCase

from apps.contas.papeis import Papel, papeis_do_token, papel_efetivo


def token_falso(papeis, client='sgcas-web'):
    corpo = base64.urlsafe_b64encode(
        json.dumps({'resource_access': {client: {'roles': papeis}}}).encode()
    ).decode().rstrip('=')
    return f'cabecalho.{corpo}.assinatura'


class PrecedenciaDePapeis(SimpleTestCase):
    def test_papel_unico(self):
        self.assertEqual(papel_efetivo(['TECNICO']), Papel.TECNICO)

    def test_vale_o_mais_forte_quando_ha_dois(self):
        # Coordenador que também aprova acessos recebe os dois papéis; a
        # precedência precisa ser determinística, não a ordem do array.
        self.assertEqual(papel_efetivo(['COORDENADOR', 'ADMIN']), Papel.ADMIN)
        self.assertEqual(papel_efetivo(['ADMIN', 'COORDENADOR']), Papel.ADMIN)

    def test_sem_papel_do_sgcas_e_porta_fechada(self):
        # Cidadão comum: tem conta no Tefé Cidadão, não é operador.
        self.assertIsNone(papel_efetivo(['CIDADAO']))
        self.assertIsNone(papel_efetivo([]))
        self.assertIsNone(papel_efetivo(None))

    def test_le_papeis_do_client_certo(self):
        token = token_falso(['ADMIN'])
        self.assertEqual(papeis_do_token(token, 'sgcas-web'), ['ADMIN'])

    def test_ignora_papeis_de_outro_client(self):
        # Ser admin de outro sistema do realm não dá acesso ao SGCAS.
        token = token_falso(['ADMIN'], client='outro-sistema')
        self.assertEqual(papeis_do_token(token, 'sgcas-web'), [])

    def test_token_malformado_nao_derruba(self):
        self.assertEqual(papeis_do_token('lixo', 'sgcas-web'), [])
