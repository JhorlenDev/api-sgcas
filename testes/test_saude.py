"""Health check do container."""
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings


class Saude(TestCase):
    def test_responde_sem_login(self):
        resposta = self.client.get('/api/health')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), {'status': 'ok'})

    def test_sem_banco_e_503(self):
        # `healthy` com o banco fora esconderia justamente a falha que importa.
        with mock.patch.object(connection, 'cursor', side_effect=Exception('fora')):
            resposta = self.client.get('/api/health')
        self.assertEqual(resposta.status_code, 503)

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r'^api/health$'])
    def test_nao_redireciona_para_https(self):
        # O check roda por HTTP de dentro do container; redirecionado, nunca daria 200.
        self.assertEqual(self.client.get('/api/health').status_code, 200)
