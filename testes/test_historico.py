"""Histórico municipal e a checagem de duplicidade."""
import uuid

from django.utils import timezone

from apps.atendimentos import historico
from apps.atendimentos.models import BeneficioEventual
from testes.base import CenarioBase


class HistoricoEntreUnidades(CenarioBase):
    def setUp(self):
        agora = timezone.now()
        # A pessoa recebeu no CRAS Centro; quem consulta está no CRAS Sul.
        self.beneficio = BeneficioEventual.objects.create(
            id=str(uuid.uuid4()), cidadao=self.cidadao, nome_da_pessoa=self.cidadao.nome,
            tipo=BeneficioEventual.Tipo.VULNERABILIDADE, descricao='Cesta básica',
            registrado_por=self.tecnico, unidade=self.centro,
            criado_em=agora, atualizado_em=agora,
        )

    def test_atravessa_unidades(self):
        # É o ponto do histórico: sem isso a duplicidade nunca aparece.
        entradas = historico.do_cidadao(self.cidadao, self.recepcionista)
        self.assertEqual(len(entradas), 1)
        self.assertEqual(entradas[0].unidade, 'CRAS Centro')
        self.assertTrue(entradas[0].e_de_outra_unidade)

    def test_recepcao_nao_ve_quem_atendeu(self):
        entradas = historico.do_cidadao(self.cidadao, self.recepcionista)
        self.assertIsNone(entradas[0].quem_atendeu)

    def test_coordenador_ve_quem_atendeu(self):
        # O nome é sempre gravado; o que se restringe é a exposição rotineira.
        entradas = historico.do_cidadao(self.cidadao, self.coordenador)
        self.assertEqual(entradas[0].quem_atendeu, 'José Técnico')

    def test_admin_ve_quem_atendeu(self):
        self.assertEqual(historico.do_cidadao(self.cidadao, self.admin)[0].quem_atendeu, 'José Técnico')

    def test_marca_o_mes_corrente(self):
        self.assertTrue(historico.do_cidadao(self.cidadao, self.admin)[0].no_mes_corrente)


class AlertaDeDuplicidade(CenarioBase):
    def setUp(self):
        agora = timezone.now()
        BeneficioEventual.objects.create(
            id=str(uuid.uuid4()), cidadao=self.cidadao, nome_da_pessoa=self.cidadao.nome,
            tipo=BeneficioEventual.Tipo.VULNERABILIDADE, registrado_por=self.tecnico,
            unidade=self.centro, criado_em=agora, atualizado_em=agora,
        )

    def test_avisa_no_mesmo_tipo(self):
        alerta = historico.alerta_de_duplicidade(self.cidadao, BeneficioEventual.Tipo.VULNERABILIDADE)
        self.assertIsNotNone(alerta)
        self.assertEqual(alerta.unidade.nome, 'CRAS Centro')

    def test_nao_avisa_em_tipo_diferente(self):
        # Pedido novo segue o fluxo normal.
        self.assertIsNone(historico.alerta_de_duplicidade(self.cidadao, BeneficioEventual.Tipo.MORTE))
