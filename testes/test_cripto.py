"""Cifragem de PII e índice cego."""
import base64

from django.test import SimpleTestCase, override_settings

from apps.comum import cripto

CHAVE = base64.b64encode(b'0' * 32).decode()


@override_settings(PII_ENCRYPTION_ENABLED=True, PII_ENCRYPTION_KEY=CHAVE, PII_HMAC_KEY=CHAVE)
class Cifragem(SimpleTestCase):
    def test_ida_e_volta(self):
        cifrado = cripto.cifrar('529.982.247-25')
        self.assertNotIn('529', cifrado)
        self.assertEqual(cripto.decifrar(cifrado), '529.982.247-25')

    def test_formato_compativel_com_o_backend_anterior(self):
        # `v1:iv:tag:texto`. Mudar isto tornaria ilegível todo o dado já
        # gravado em produção.
        partes = cripto.cifrar('teste').split(':')
        self.assertEqual(len(partes), 4)
        self.assertEqual(partes[0], 'v1')

    def test_cada_cifragem_gera_texto_diferente(self):
        # IV aleatório: dois CPFs iguais não podem produzir o mesmo texto
        # cifrado, senão dá para inferir igualdade sem decifrar.
        self.assertNotEqual(cripto.cifrar('mesmo'), cripto.cifrar('mesmo'))

    def test_texto_adulterado_e_recusado(self):
        cifrado = cripto.cifrar('529.982.247-25')
        partes = cifrado.split(':')
        partes[3] = 'A' + partes[3][1:]
        with self.assertRaises(cripto.ErroDeCripto):
            cripto.decifrar(':'.join(partes))

    def test_nao_recifra_o_que_ja_esta_cifrado(self):
        uma_vez = cripto.cifrar('teste')
        self.assertEqual(cripto.cifrar(uma_vez), uma_vez)

    def test_valor_em_texto_puro_e_devolvido_como_esta(self):
        # Dado gravado antes da cifragem ser ligada: a migração é gradual.
        self.assertEqual(cripto.decifrar('123.456.789-00'), '123.456.789-00')


@override_settings(PII_ENCRYPTION_ENABLED=True, PII_ENCRYPTION_KEY=CHAVE, PII_HMAC_KEY=CHAVE)
class IndiceCego(SimpleTestCase):
    def test_mesmo_valor_gera_mesmo_indice(self):
        self.assertEqual(cripto.indice_cego('529.982.247-25'), cripto.indice_cego('529.982.247-25'))

    def test_normaliza_caixa_e_espaco(self):
        # Sem isso a busca falharia por diferença de digitação.
        self.assertEqual(
            cripto.indice_cego('  Joana@Exemplo.COM '),
            cripto.indice_cego('joana@exemplo.com'),
        )

    def test_valores_diferentes_geram_indices_diferentes(self):
        self.assertNotEqual(cripto.indice_cego('111'), cripto.indice_cego('222'))

    def test_vazio_nao_gera_indice(self):
        self.assertIsNone(cripto.indice_cego(''))
        self.assertIsNone(cripto.indice_cego(None))
