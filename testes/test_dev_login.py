"""
Travas da entrada local sem SSO (`apps/contas/dev_login.py`).

A view é chamada direto, e não pela URL: o test runner roda com DEBUG=False, e
com DEBUG falso a rota nem é registrada. Aqui o que se prova é a view — ela
precisa recusar sozinha, mesmo que alguém registre a rota por engano.
"""
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, override_settings

from apps.contas.autenticacao import CHAVE_OPERADOR
from apps.contas.dev_login import entrar_local
from testes.base import CenarioBase

FRONT = 'https://front.exemplo'
TUNEL = 'algo-aleatorio.trycloudflare.com'
CHAVE = 'chave-de-teste-bem-comprida-1234567890'


@override_settings(DEBUG=True, DEV_LOGIN_ENABLED=True, DEV_LOGIN_CHAVE=CHAVE, FRONTEND_URL=FRONT)
class TravasDaEntradaLocal(CenarioBase):
    def pedir(self, query='', host='localhost:8000', encaminhado=None):
        extras = {'HTTP_HOST': host}
        if encaminhado:
            extras['HTTP_X_FORWARDED_HOST'] = encaminhado
        request = RequestFactory().get(f'/api/auth/dev-login{query}', **extras)
        SessionMiddleware(lambda r: None).process_request(request)
        return request, entrar_local(request)

    def test_localhost_entra_sem_chave(self):
        request, resposta = self.pedir(encaminhado='localhost:3001')
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(resposta['Location'], f'{FRONT}/dashboard')
        self.assertIn(CHAVE_OPERADOR, request.session)

    def test_chamada_direta_na_api_local_entra(self):
        _, resposta = self.pedir(host='127.0.0.1:8000')
        self.assertEqual(resposta.status_code, 302)

    def test_tunel_sem_chave_recebe_404(self):
        request, resposta = self.pedir(encaminhado=TUNEL)
        self.assertEqual(resposta.status_code, 404)
        self.assertNotIn(CHAVE_OPERADOR, request.session)

    def test_tunel_com_chave_errada_recebe_404(self):
        _, resposta = self.pedir('?chave=errada', encaminhado=TUNEL)
        self.assertEqual(resposta.status_code, 404)

    def test_tunel_com_chave_certa_entra(self):
        request, resposta = self.pedir(f'?chave={CHAVE}', encaminhado=TUNEL)
        self.assertEqual(resposta.status_code, 302)
        self.assertIn(CHAVE_OPERADOR, request.session)

    def test_outra_maquina_da_rede_sem_chave_recebe_404(self):
        _, resposta = self.pedir(host='192.168.0.20:8000')
        self.assertEqual(resposta.status_code, 404)

    @override_settings(DEV_LOGIN_CHAVE='')
    def test_chave_vazia_nunca_libera_quem_vem_de_fora(self):
        _, resposta = self.pedir('?chave=', encaminhado=TUNEL)
        self.assertEqual(resposta.status_code, 404)

    @override_settings(DEV_LOGIN_ENABLED=False)
    def test_sem_a_flag_nem_localhost_entra(self):
        _, resposta = self.pedir(encaminhado='localhost:3001')
        self.assertEqual(resposta.status_code, 404)

    @override_settings(DEBUG=False)
    def test_sem_debug_nem_com_flag_e_chave_entra(self):
        _, resposta = self.pedir(f'?chave={CHAVE}', encaminhado='localhost:3001')
        self.assertEqual(resposta.status_code, 404)

    def test_destino_fora_do_front_volta_para_o_painel(self):
        for destino in ('@exemplo.com/x', '//exemplo.com/x', '/\\exemplo.com', 'https://exemplo.com'):
            _, resposta = self.pedir(f'?destino={destino}', encaminhado='localhost:3001')
            self.assertEqual(resposta['Location'], f'{FRONT}/dashboard', destino)

    def test_destino_do_proprio_front_e_respeitado(self):
        _, resposta = self.pedir('?destino=/fila', encaminhado='localhost:3001')
        self.assertEqual(resposta['Location'], f'{FRONT}/fila')
