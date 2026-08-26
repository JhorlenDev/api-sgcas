"""O fluxo do balcão até o atendimento."""
from apps.atendimentos.models import AtendimentoDeRecepcao, Caso, SenhaDaFila
from testes.base import CenarioBase


class AtendimentoDeBalcao(CenarioBase):
    def registrar(self, **extra):
        corpo = {'cidadao_id': self.cidadao.id, 'servico_id': self.servico.id, **extra}
        return self.como(self.recepcionista).post(
            '/api/reception/atendimento', corpo, content_type='application/json'
        )

    def test_negativa_nao_abre_caso_nem_entra_na_fila(self):
        # A pessoa já recebeu este mês: o atendimento termina no balcão.
        resposta = self.registrar(desfecho='FINALIZADO', motivo='Já retirou no CRAS Centro')

        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(Caso.objects.filter(cidadao=self.cidadao).count(), 0)
        self.assertEqual(SenhaDaFila.objects.filter(cidadao=self.cidadao).count(), 0)
        self.assertEqual(AtendimentoDeRecepcao.objects.filter(cidadao=self.cidadao).count(), 1)

    def test_negativa_sem_motivo_e_recusada(self):
        # Sem o motivo, a próxima unidade não saberia por que foi negado, e a
        # pessoa refaria o mesmo pedido lá.
        resposta = self.registrar(desfecho='FINALIZADO')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('motivo', resposta.json())
        self.assertEqual(AtendimentoDeRecepcao.objects.count(), 0)

    def test_encaminhamento_cria_caso_e_senha(self):
        resposta = self.registrar(desfecho='ENCAMINHADO')
        dados = resposta.json()

        self.assertEqual(resposta.status_code, 201)
        self.assertIsNotNone(dados['caso'])
        self.assertIsNotNone(dados['senha'])
        self.assertEqual(Caso.objects.get(cidadao=self.cidadao).situacao, Caso.Situacao.EM_TRIAGEM)

    def test_recepcao_nao_define_prioridade(self):
        # Dizer que um caso é urgente é avaliação técnica. A recepção captura o
        # pedido; quem atende reprioriza ao ver a situação.
        dados = self.registrar(desfecho='ENCAMINHADO', prioridade='URGENTE').json()
        self.assertEqual(dados['caso']['prioridade'], Caso.Prioridade.NORMAL)
        self.assertEqual(dados['senha']['prioridade'], Caso.Prioridade.NORMAL)

    def test_servico_precisa_existir(self):
        resposta = self.registrar(servico_id='inventado', desfecho='ENCAMINHADO')
        self.assertEqual(resposta.status_code, 400)

    def test_nao_marca_servico_de_outra_unidade_como_seu(self):
        # A recepção pode ver os serviços de outra unidade — mas registrá-los
        # como atendimento da própria unidade falsearia de onde veio o serviço.
        resposta = self.registrar(servico_id=self.servico_do_centro.id, desfecho='ENCAMINHADO')
        self.assertEqual(resposta.status_code, 400)
        self.assertIn('servico_id', resposta.json())

    def test_encaminha_para_outra_unidade_declarando_o_destino(self):
        # A pessoa é cadastrada aqui e entra na fila de lá, com os dados
        # prontos, em vez de fazer a viagem e recomeçar do zero.
        resposta = self.registrar(
            servico_id=self.servico_do_centro.id,
            unidade_destino_id=self.centro.id,
            desfecho='ENCAMINHADO',
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(resposta.json()['caso']['unidade_nome'], 'CRAS Centro')

    def test_demanda_municipal_e_deduzida_do_servico(self):
        # Uma escolha na tela, duas informações no banco: o relatório da rede
        # continua fechando mesmo com serviços diferentes por unidade.
        self.registrar(desfecho='ENCAMINHADO')
        self.assertEqual(Caso.objects.get(cidadao=self.cidadao).demanda_id, self.demanda.id)

    def test_operador_sem_unidade_nao_registra(self):
        resposta = self.como(self.sem_unidade).post(
            '/api/reception/atendimento',
            {'cidadao_id': self.cidadao.id, 'servico_id': self.servico.id, 'desfecho': 'ENCAMINHADO'},
            content_type='application/json',
        )
        self.assertIn(resposta.status_code, (403, 409))


class ChamarDaFila(CenarioBase):
    def test_chamar_traz_o_atendimento_montado(self):
        # A mudança central do fluxo: antes, chamar só mudava o estado da senha
        # e o atendente procurava a pessoa de novo em outra tela.
        self.como(self.recepcionista).post(
            '/api/reception/atendimento',
            {'cidadao_id': self.cidadao.id, 'servico_id': self.servico.id, 'desfecho': 'ENCAMINHADO'},
            content_type='application/json',
        )
        atendente = self.coordenador  # lotado no CRAS Sul, como a recepção
        resposta = self.como(atendente).post(
            '/api/queues/chamar-proximo', {}, content_type='application/json'
        )
        dados = resposta.json()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(dados['cidadao']['nome'], self.cidadao.nome)
        self.assertIsNotNone(dados['caso'])
        self.assertIn('historico', dados)
        self.assertEqual(dados['senha']['situacao'], SenhaDaFila.Situacao.EM_ATENDIMENTO)

    def test_fila_vazia_responde_404(self):
        resposta = self.como(self.coordenador).post(
            '/api/queues/chamar-proximo', {}, content_type='application/json'
        )
        self.assertEqual(resposta.status_code, 404)
