"""Gestão de operadores."""
from apps.contas.models import Operador
from testes.base import CenarioBase


class GestaoDeOperadores(CenarioBase):
    def test_lista_e_restrita_a_supervisao(self):
        self.assertEqual(self.como(self.recepcionista).get('/api/users/').status_code, 403)
        self.assertEqual(self.como(self.admin).get('/api/users/').status_code, 200)

    def test_quem_nao_ve_todas_as_unidades_ve_so_a_sua(self):
        # Mais quem está sem lotação — é a partir daí que a unidade é atribuída.
        emails = {o['email'] for o in self.como(self.coordenador).get('/api/users/').json()}
        self.assertIn(self.recepcionista.email, emails)      # mesma unidade
        self.assertIn(self.sem_unidade.email, emails)        # sem lotação
        self.assertNotIn(self.tecnico.email, emails)         # outra unidade

    def test_admin_define_a_lotacao_de_quem_entrou_pelo_sso(self):
        # Sem isto, quem entra pelo SSO fica sem enxergar nada e não há como
        # corrigir pela interface.
        resposta = self.como(self.admin).put(
            f'/api/users/{self.sem_unidade.id}/atualizar',
            {'unidade_id': self.sul.id}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 200)
        self.sem_unidade.refresh_from_db()
        self.assertEqual(self.sem_unidade.unidade_id, self.sul.id)

    def test_papel_nao_e_alteravel_por_aqui(self):
        # Quem concede papel é o Tefé Cidadão; aceitar aqui criaria uma segunda
        # fonte de verdade, sobrescrita no próximo acesso da pessoa.
        self.como(self.admin).put(
            f'/api/users/{self.tecnico.id}/atualizar',
            {'papel': 'ADMIN'}, content_type='application/json',
        )
        self.tecnico.refresh_from_db()
        self.assertEqual(self.tecnico.papel, 'TECNICO')

    def test_so_admin_atualiza(self):
        resposta = self.como(self.coordenador).put(
            f'/api/users/{self.tecnico.id}/atualizar',
            {'nome': 'Outro'}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 403)

    def test_unidade_inexistente_e_recusada(self):
        resposta = self.como(self.admin).put(
            f'/api/users/{self.tecnico.id}/atualizar',
            {'unidade_id': 'inventada'}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 400)

    def test_nao_pode_desligar_a_propria_conta(self):
        resposta = self.como(self.admin).delete(f'/api/users/{self.admin.id}/desligar')
        self.assertEqual(resposta.status_code, 400)

    def test_desligar_marca_como_excluido(self):
        resposta = self.como(self.admin).delete(f'/api/users/{self.tecnico.id}/desligar')
        self.assertEqual(resposta.status_code, 204)
        desligado = Operador.objects.get(id=self.tecnico.id)
        self.assertFalse(desligado.ativo)
        self.assertIsNotNone(desligado.excluido_em)

    def test_cada_um_ve_a_propria_conta(self):
        cliente = self.como(self.recepcionista)
        self.assertEqual(cliente.get(f'/api/users/{self.recepcionista.id}').status_code, 200)
        self.assertEqual(cliente.get(f'/api/users/{self.tecnico.id}').status_code, 403)
