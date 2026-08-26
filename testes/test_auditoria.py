"""A trilha de auditoria."""
from apps.auditoria.models import RegistroDeAuditoria
from testes.base import CenarioBase


class TrilhaDeAuditoria(CenarioBase):
    def test_registra_leitura_de_prontuario(self):
        # Um sistema que só audita escrita não responde "quem consultou os
        # dados desta pessoa" — que é o que a LGPD pede.
        self.como(self.tecnico).get(f'/api/citizens/{self.cidadao.id}')
        registro = RegistroDeAuditoria.objects.filter(acao='READ', entidade='citizens').first()
        self.assertIsNotNone(registro)
        self.assertEqual(registro.operador_id, self.tecnico.id)

    def test_registra_escrita_com_dados_redigidos(self):
        self.como(self.recepcionista).post(
            '/api/reception/atendimento',
            {'cidadao_id': self.cidadao.id, 'servico_id': self.servico.id,
             'desfecho': 'FINALIZADO', 'motivo': 'Relato de violência doméstica'},
            content_type='application/json',
        )
        registro = RegistroDeAuditoria.objects.filter(acao='CREATE').first()
        self.assertIsNotNone(registro)
        self.assertTrue(registro.dados_depois['motivo'].startswith('[REDIGIDO:'))
        self.assertNotIn('violência', str(registro.dados_depois))

    def test_nao_polui_a_trilha_com_consulta_a_catalogo(self):
        # Auditar todo GET enterraria a informação que importa no ruído.
        antes = RegistroDeAuditoria.objects.count()
        cliente = self.como(self.tecnico)
        cliente.get('/api/institutional/units')
        cliente.get('/api/institutional/demands')
        cliente.get('/api/auth/me')
        self.assertEqual(RegistroDeAuditoria.objects.count(), antes)

    def test_requisicao_recusada_nao_vira_registro(self):
        antes = RegistroDeAuditoria.objects.count()
        self.como(self.recepcionista).get(f'/api/citizens/{self.cidadao.id}')  # 403
        self.assertEqual(RegistroDeAuditoria.objects.count(), antes)
