"""Escopo por unidade: falha fechado e recusa unidade alheia."""
from django.core.exceptions import PermissionDenied

from apps.contas.escopo import SEM_UNIDADE, escopo_de, pode_acessar_unidade, resolver_filtro
from testes.base import CenarioBase


class EscopoPorUnidade(CenarioBase):
    def test_admin_ve_tudo(self):
        self.assertEqual(escopo_de(self.admin), {})

    def test_operador_restrito_a_propria_unidade(self):
        self.assertEqual(escopo_de(self.tecnico), {'unidade_id': self.centro.id})

    def test_coordenador_tambem_e_restrito(self):
        # Foi restringido depois de o sistema anterior deixá-lo ver tudo.
        self.assertEqual(escopo_de(self.coordenador), {'unidade_id': self.sul.id})

    def test_sem_unidade_falha_fechado(self):
        # Conta criada por SSO nasce sem unidade. Filtro vazio daria acesso a
        # todas as unidades justamente a quem não tem nenhuma.
        self.assertEqual(escopo_de(self.sem_unidade), {'unidade_id': SEM_UNIDADE})

    def test_pedir_unidade_alheia_e_recusado(self):
        with self.assertRaises(PermissionDenied):
            resolver_filtro(self.tecnico, self.sul.id)

    def test_admin_pode_filtrar_por_unidade(self):
        self.assertEqual(resolver_filtro(self.admin, self.sul.id), {'unidade_id': self.sul.id})

    def test_acesso_a_unidade(self):
        self.assertTrue(pode_acessar_unidade(self.tecnico, self.centro.id))
        self.assertFalse(pode_acessar_unidade(self.tecnico, self.sul.id))
        self.assertTrue(pode_acessar_unidade(self.admin, self.sul.id))
        self.assertFalse(pode_acessar_unidade(self.sem_unidade, self.sul.id))
