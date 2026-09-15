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

    def test_recepcao_nao_marca_urgente(self):
        # Dizer que um caso é urgente é avaliação técnica. A recepção captura o
        # pedido; quem atende reprioriza ao ver a situação. O pedido não é
        # recusado — a pessoa já está no balcão e não pode voltar pra fila.
        resposta = self.registrar(desfecho='ENCAMINHADO', prioridade='URGENTE')

        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        self.assertEqual(dados['caso']['prioridade'], Caso.Prioridade.NORMAL)
        self.assertEqual(dados['senha']['prioridade'], Caso.Prioridade.NORMAL)

    def test_recepcao_marca_preferencial(self):
        # A preferência legal (idoso, PCD, gestante) é observada no balcão, e é
        # o atendente quem a registra — daí a senha PR sair da recepção.
        dados = self.registrar(desfecho='ENCAMINHADO', prioridade='ALTA').json()

        self.assertEqual(dados['caso']['prioridade'], Caso.Prioridade.ALTA)
        self.assertEqual(dados['senha']['prioridade'], Caso.Prioridade.ALTA)
        self.assertTrue(dados['senha']['senha'].startswith('PR'))

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


class RecuperarAtendimento(CenarioBase):
    def abrir(self):
        self.como(self.recepcionista).post(
            '/api/reception/atendimento',
            {'cidadao_id': self.cidadao.id, 'servico_id': self.servico.id, 'desfecho': 'ENCAMINHADO'},
            content_type='application/json',
        )
        resposta = self.como(self.coordenador).post(
            '/api/queues/chamar-proximo', {}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 200)
        return resposta.json()

    def test_recupera_em_outra_sessao_sem_chamar_novamente(self):
        chamado = self.abrir()
        resposta = self.como(self.coordenador).get('/api/queues/atendimento-atual')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), chamado)

    def test_nao_retorna_atendimento_de_outro_operador(self):
        self.abrir()
        self.tecnico.unidade = self.sul
        self.tecnico.save(update_fields=['unidade'])
        resposta = self.como(self.tecnico).get('/api/queues/atendimento-atual')
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.data)

    def test_chamar_novamente_preserva_senha_e_horario(self):
        chamado = self.abrir()
        # Mesmo com mais uma pessoa aguardando, deve devolver a senha já aberta.
        import uuid
        pendente = SenhaDaFila.objects.get(pk=chamado['senha']['id'])
        pendente.pk = str(uuid.uuid4())
        pendente.senha = 'N999'
        pendente.situacao = SenhaDaFila.Situacao.AGUARDANDO
        pendente.atendido_por = None
        pendente.chamado_em = None
        pendente.save(force_insert=True)
        resposta = self.como(self.coordenador).post(
            '/api/queues/chamar-proximo', {}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), chamado)
        self.assertEqual(SenhaDaFila.objects.filter(situacao='EM_ATENDIMENTO').count(), 1)
        pendente.refresh_from_db()
        self.assertEqual(pendente.situacao, SenhaDaFila.Situacao.AGUARDANDO)

    def test_finalizado_nao_e_recuperado(self):
        chamado = self.abrir()
        resposta = self.como(self.coordenador).post(
            f"/api/queues/{chamado['senha']['id']}/nao-compareceu",
            {}, content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(self.como(self.coordenador).get('/api/queues/atendimento-atual').data)

    def test_sem_atendimento_retorna_vazio(self):
        resposta = self.como(self.coordenador).get('/api/queues/atendimento-atual')
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.data)

    def test_recepcionista_nao_acessa_atendimento(self):
        resposta = self.como(self.recepcionista).get('/api/queues/atendimento-atual')
        self.assertEqual(resposta.status_code, 403)


    def test_lista_e_retoma_senha_escolhida(self):
        chamado = self.abrir()
        lista = self.como(self.coordenador).get('/api/queues/em-atendimento')
        self.assertEqual(lista.status_code, 200)
        self.assertEqual(lista.json()[0]['id'], chamado['senha']['id'])
        self.assertTrue(lista.json()[0]['pode_retomar'])
        resposta = self.como(self.coordenador).get(f"/api/queues/{chamado['senha']['id']}/retomar")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json(), chamado)

    def test_outro_operador_ve_responsavel_mas_nao_retoma(self):
        chamado = self.abrir()
        self.tecnico.unidade = self.sul
        self.tecnico.save(update_fields=['unidade'])
        lista = self.como(self.tecnico).get('/api/queues/em-atendimento').json()
        self.assertFalse(lista[0]['pode_retomar'])
        self.assertEqual(lista[0]['operador_nome'], self.coordenador.nome)
        self.assertEqual(self.como(self.tecnico).get(f"/api/queues/{chamado['senha']['id']}/retomar").status_code, 404)

    def test_outra_unidade_nao_lista_senha(self):
        self.abrir()
        self.assertEqual(self.como(self.tecnico).get('/api/queues/em-atendimento').json(), [])

    def test_retomar_senha_finalizada_e_recusado(self):
        chamado = self.abrir()
        SenhaDaFila.objects.filter(pk=chamado['senha']['id']).update(situacao='ATENDIDO')
        self.assertEqual(self.como(self.coordenador).get(f"/api/queues/{chamado['senha']['id']}/retomar").status_code, 404)


    def test_detalhes_correspondem_aos_totais_e_ao_escopo(self):
        chamado = self.abrir()
        cliente = self.como(self.coordenador)
        painel = cliente.get('/api/queues/painel').json()
        for grupo in ('atendidos_hoje', 'aguardando_na_fila', 'em_atendimento', 'finalizados_hoje', 'casos_em_acompanhamento'):
            resposta = cliente.get(f'/api/queues/painel/{grupo}')
            self.assertEqual(resposta.status_code, 200)
            # `total` do envelope, não o tamanho da página: é ele que tem de
            # bater com o número do painel.
            self.assertEqual(resposta.json()['total'], painel[grupo])
            self.assertEqual(self.como(self.tecnico).get(f'/api/queues/painel/{grupo}').json()['itens'], [])
        resposta = cliente.get('/api/queues/painel/casos_em_acompanhamento').json()
        self.assertEqual(resposta['tipo'], 'casos')
        self.assertEqual(resposta['itens'][0]['id'], chamado['caso']['id'])
        self.assertEqual(cliente.get('/api/queues/painel/invalido').status_code, 404)

    def test_detalhes_sao_paginados(self):
        chamado = self.abrir()
        # Mais duas senhas aguardando, copiadas da chamada, para haver o que
        # dividir em páginas.
        import uuid
        for numero in ('N901', 'N902'):
            copia = SenhaDaFila.objects.get(pk=chamado['senha']['id'])
            copia.pk = str(uuid.uuid4())
            copia.senha = numero
            copia.situacao = SenhaDaFila.Situacao.AGUARDANDO
            copia.atendido_por = None
            copia.chamado_em = None
            copia.save(force_insert=True)
        resposta = self.como(self.coordenador).get('/api/queues/painel/aguardando_na_fila?limit=1&page=2').json()
        self.assertEqual(resposta['tipo'], 'senhas')
        self.assertEqual(resposta['total'], 2)
        self.assertEqual(resposta['paginas'], 2)
        self.assertEqual(resposta['pagina'], 2)
        self.assertEqual(len(resposta['itens']), 1)

    def test_detalhes_finalizados_hoje(self):
        chamado = self.abrir()
        cliente = self.como(self.coordenador)
        resposta = cliente.post(f"/api/cases/{chamado['caso']['id']}/concluir", {'situacao': 'CONCLUIDO', 'relato': 'Teste concluído'}, content_type='application/json')
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(cliente.get('/api/queues/painel/atendidos_hoje').json()['itens'][0]['id'], chamado['senha']['id'])
        self.assertEqual(cliente.get('/api/queues/painel/finalizados_hoje').json()['itens'][0]['id'], chamado['caso']['id'])
        self.assertEqual(cliente.get('/api/queues/painel/casos_em_acompanhamento').json()['itens'], [])
