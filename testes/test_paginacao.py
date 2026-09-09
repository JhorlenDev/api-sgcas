"""
Paginação e filtros das listagens.

O defeito que motivou este arquivo não tinha teste que o pegasse: as listagens
devolviam uma lista cortada em 100, e a suíte só conferia código de status. Numa
base pequena o corte nunca era alcançado, então nada acusava que o número
exibido na tela era o tamanho do corte, e não o total.
"""
import uuid

from django.utils import timezone

from apps.atendimentos.models import Caso
from testes.base import CenarioBase


class Paginacao(CenarioBase):
    """A listagem de casos, que é a maior do sistema."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        agora = timezone.now()
        for n in range(30):
            Caso.objects.create(
                id=str(uuid.uuid4()),
                protocolo=f'2026-{n:04d}',
                situacao=Caso.Situacao.EM_TRIAGEM if n % 3 else Caso.Situacao.CONCLUIDO,
                prioridade=Caso.Prioridade.ALTA if n % 5 else Caso.Prioridade.NORMAL,
                cidadao=cls.cidadao,
                unidade=cls.sul,
                servico=cls.servico,
                aberto_em=agora,
                criado_em=agora,
                atualizado_em=agora,
            )

    def listar(self, query=''):
        return self.como(self.admin).get(f'/api/cases/{query}').json()

    def test_envelope_traz_o_total_real_e_nao_o_tamanho_da_pagina(self):
        # O ponto do exercicio: 30 casos, pagina de 10. O `total` precisa dizer
        # 30 — se disser 10, a tela volta a exibir o tamanho da fatia como se
        # fosse o tamanho da rede.
        corpo = self.listar('?limit=10')
        self.assertEqual(len(corpo['itens']), 10)
        self.assertEqual(corpo['total'], 30)
        self.assertEqual(corpo['paginas'], 3)
        self.assertEqual(corpo['pagina'], 1)

    def test_paginas_seguintes_trazem_registros_diferentes(self):
        primeira = {c['id'] for c in self.listar('?limit=10&page=1')['itens']}
        segunda = {c['id'] for c in self.listar('?limit=10&page=2')['itens']}
        self.assertEqual(len(primeira), 10)
        self.assertEqual(len(segunda), 10)
        self.assertFalse(primeira & segunda)

    def test_pagina_alem_do_fim_devolve_vazio_sem_erro(self):
        corpo = self.listar('?limit=10&page=99')
        self.assertEqual(corpo['itens'], [])
        self.assertEqual(corpo['total'], 30)

    def test_limite_por_pagina_tem_teto(self):
        # Paginacao sem teto e o corte antigo com outro nome.
        corpo = self.listar('?limit=100000')
        self.assertLessEqual(corpo['por_pagina'], 100)

    def test_parametro_invalido_e_recusado_em_vez_de_ignorado(self):
        # Cair para o padrao faria a tela mostrar a pagina 1 achando que mostra
        # outra.
        self.assertEqual(self.como(self.admin).get('/api/cases/?page=abc').status_code, 400)
        self.assertEqual(self.como(self.admin).get('/api/cases/?limit=0').status_code, 400)

    def test_ordenacao_so_aceita_o_que_a_rota_declara(self):
        self.assertEqual(self.como(self.admin).get('/api/cases/?ordenar=aberto_em').status_code, 200)
        self.assertEqual(self.como(self.admin).get('/api/cases/?ordenar=senha').status_code, 400)


class FiltrosDeCaso(Paginacao):
    def test_filtra_por_situacao(self):
        corpo = self.listar('?situacao=CONCLUIDO')
        self.assertEqual(corpo['total'], 10)
        self.assertTrue(all(c['situacao'] == 'CONCLUIDO' for c in corpo['itens']))

    def test_filtra_por_prioridade(self):
        corpo = self.listar('?prioridade=ALTA')
        self.assertEqual(corpo['total'], 24)

    def test_busca_casa_protocolo(self):
        corpo = self.listar('?busca=2026-0007')
        self.assertEqual(corpo['total'], 1)

    def test_busca_casa_nome_do_cidadao(self):
        corpo = self.listar('?busca=Antonia')
        self.assertEqual(corpo['total'], 30)

    def test_periodo_recusa_data_malformada(self):
        self.assertEqual(self.como(self.admin).get('/api/cases/?de=ontem').status_code, 400)


class ResumoDeCasos(Paginacao):
    def test_resumo_conta_a_rede_inteira_e_nao_a_pagina(self):
        # É a correção do defeito: os contadores da tela vinham de um `filter()`
        # sobre a página recebida.
        corpo = self.como(self.admin).get('/api/cases/resumo?limit=5').json()
        self.assertEqual(corpo['total'], 30)
        self.assertEqual(corpo['por_situacao']['EM_TRIAGEM'], 20)
        self.assertEqual(corpo['por_situacao']['CONCLUIDO'], 10)
        self.assertEqual(corpo['em_acompanhamento'], 20)

    def test_resumo_respeita_os_mesmos_filtros_da_listagem(self):
        # Se divergirem, o contador do topo deixa de descrever a lista de baixo.
        corpo = self.como(self.admin).get('/api/cases/resumo?situacao=CONCLUIDO').json()
        self.assertEqual(corpo['total'], 10)
        self.assertEqual(corpo['por_situacao']['EM_TRIAGEM'], 0)

    def test_resumo_respeita_o_escopo_por_unidade(self):
        # O técnico é do CRAS Centro; os casos foram abertos no CRAS Sul.
        corpo = self.como(self.tecnico).get('/api/cases/resumo').json()
        self.assertEqual(corpo['total'], 0)


class ContratoDoOperador(CenarioBase):
    def test_unidade_tem_o_mesmo_formato_na_lista_e_no_me(self):
        """
        O mesmo nome não pode significar duas coisas.

        Quando `/api/users/` devolvia `unidade` como string e `/api/auth/me`
        como objeto, quem lia `unidade.id` recebia `undefined` sem erro — e o
        formulário de usuários acabava enviando lotação vazia, apagando a
        unidade de quem fosse salvo.
        """
        na_lista = next(
            o for o in self.como(self.admin).get('/api/users/').json()['itens']
            if o['id'] == self.coordenador.id
        )
        no_me = self.como(self.coordenador).get('/api/auth/me').json()

        self.assertIsInstance(na_lista['unidade'], dict)
        self.assertIsInstance(no_me['unidade'], dict)
        self.assertEqual(na_lista['unidade']['id'], no_me['unidade']['id'])
        self.assertEqual(na_lista['unidade_id'], self.sul.id)

    def test_operador_sem_lotacao_devolve_unidade_nula(self):
        na_lista = next(
            o for o in self.como(self.admin).get('/api/users/').json()['itens']
            if o['id'] == self.sem_unidade.id
        )
        self.assertIsNone(na_lista['unidade'])
