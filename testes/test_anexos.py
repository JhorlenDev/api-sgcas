"""Anexos do prontuário."""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image

from apps.cidadaos.models import Cidadao
from testes.base import CenarioBase


def imagem_falsa(largura=3000, altura=2400) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new('RGB', (largura, altura), 'white').save(buffer, format='PNG')
    return SimpleUploadedFile('RG da Maria.png', buffer.getvalue(), content_type='image/png')


class AnexosDoProntuario(CenarioBase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.pasta, ignore_errors=True)

    def enviar(self, arquivo, operador=None):
        with override_settings(ARMAZENAMENTO_LOCAL=self.pasta):
            return self.como(operador or self.tecnico).post(
                f'/api/citizens/{self.cidadao.id}/anexos',
                {'file': arquivo, 'tipo_documento': 'rg_frente'},
            )

    def test_envia_e_lista(self):
        resposta = self.enviar(imagem_falsa())
        self.assertEqual(resposta.status_code, 201)

        cidadao = Cidadao.objects.get(id=self.cidadao.id)
        self.assertEqual(len(cidadao.anexos), 1)
        self.assertEqual(cidadao.anexos[0]['tipo_documento'], 'rg_frente')

    def test_o_nome_no_disco_nao_e_o_original(self):
        # Nome de arquivo carrega dado pessoal com frequência.
        self.enviar(imagem_falsa())
        anexo = Cidadao.objects.get(id=self.cidadao.id).anexos[0]
        self.assertNotIn('Maria', anexo['arquivo'])
        self.assertTrue(anexo['arquivo'].endswith('.jpg'))

    def test_imagem_e_recomprimida_e_ganha_miniatura(self):
        self.enviar(imagem_falsa())
        anexo = Cidadao.objects.get(id=self.cidadao.id).anexos[0]
        self.assertIsNotNone(anexo['miniatura'])
        self.assertEqual(anexo['mime'], 'image/jpeg')

    def test_o_caminho_nao_vaza_na_listagem(self):
        self.enviar(imagem_falsa())
        with override_settings(ARMAZENAMENTO_LOCAL=self.pasta):
            listagem = self.como(self.tecnico).get(
                f'/api/citizens/{self.cidadao.id}/anexos'
            ).json()
        self.assertNotIn('arquivo', listagem[0])
        self.assertNotIn('miniatura', listagem[0])

    def test_formato_nao_aceito_e_recusado(self):
        executavel = SimpleUploadedFile('x.exe', b'MZ', content_type='application/x-msdownload')
        resposta = self.enviar(executavel)
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Cidadao.objects.get(id=self.cidadao.id).anexos or [], [])

    def test_recepcao_nao_anexa(self):
        self.assertEqual(self.enviar(imagem_falsa(), self.recepcionista).status_code, 403)

    def test_baixar_devolve_o_arquivo(self):
        self.enviar(imagem_falsa())
        anexo = Cidadao.objects.get(id=self.cidadao.id).anexos[0]
        with override_settings(ARMAZENAMENTO_LOCAL=self.pasta):
            resposta = self.como(self.tecnico).get(
                f'/api/citizens/{self.cidadao.id}/anexos/{anexo["id"]}'
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'image/jpeg')

    def test_remover_e_ato_de_supervisao(self):
        self.enviar(imagem_falsa())
        anexo = Cidadao.objects.get(id=self.cidadao.id).anexos[0]
        rota = f'/api/citizens/{self.cidadao.id}/anexos/{anexo["id"]}/remover'
        with override_settings(ARMAZENAMENTO_LOCAL=self.pasta):
            self.assertEqual(self.como(self.tecnico).delete(rota).status_code, 403)
            self.assertEqual(self.como(self.admin).delete(rota).status_code, 204)
        self.assertEqual(Cidadao.objects.get(id=self.cidadao.id).anexos, [])
