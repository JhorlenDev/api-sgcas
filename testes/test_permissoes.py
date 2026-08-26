"""Quem pode chamar o quê."""
from testes.base import CenarioBase


class MatrizDePermissoes(CenarioBase):
    def rotas(self, operador):
        cliente = self.como(operador)
        return {
            'me': cliente.get('/api/auth/me').status_code,
            'buscar': cliente.get('/api/citizens/?busca=Antonia').status_code,
            'prontuario': cliente.get(f'/api/citizens/{self.cidadao.id}').status_code,
            'fila_acesso': cliente.get('/api/access-requests/').status_code,
            'auditoria': cliente.get('/api/auditoria/').status_code,
        }

    def test_sem_sessao_tudo_fechado(self):
        from django.test import Client
        anonimo = Client(headers={'host': 'localhost'})
        for rota in ['/api/auth/me', '/api/citizens/?busca=x', '/api/access-requests/']:
            self.assertEqual(anonimo.get(rota).status_code, 403, rota)

    def test_recepcao_busca_mas_nao_abre_prontuario(self):
        # Ela precisa encontrar a pessoa e ver o histórico para decidir; não
        # precisa ler relato de atendimento nem dado socioeconômico.
        r = self.rotas(self.recepcionista)
        self.assertEqual(r['buscar'], 200)
        self.assertEqual(r['prontuario'], 403)

    def test_equipe_de_atendimento_abre_prontuario(self):
        self.assertEqual(self.rotas(self.tecnico)['prontuario'], 200)

    def test_fila_de_acesso_e_auditoria_sao_so_do_admin(self):
        for operador in (self.recepcionista, self.tecnico, self.coordenador):
            r = self.rotas(operador)
            self.assertEqual(r['fila_acesso'], 403, operador.papel)
            self.assertEqual(r['auditoria'], 403, operador.papel)
        admin = self.rotas(self.admin)
        self.assertEqual(admin['fila_acesso'], 200)
        self.assertEqual(admin['auditoria'], 200)

    def test_visualizador_le_mas_nao_abre_prontuario(self):
        r = self.rotas(self.visualizador)
        self.assertEqual(r['buscar'], 200)
        self.assertEqual(r['prontuario'], 403)

    def test_operador_desativado_e_recusado_em_tudo(self):
        # Desativar fecha a porta na hora, sem esperar a sessão expirar.
        r = self.rotas(self.inativo)
        self.assertEqual(r['me'], 403)
        self.assertEqual(r['buscar'], 403)
