"""Cenário mínimo compartilhado pelos testes de integração."""
import uuid

from django.test import Client, TestCase
from django.utils import timezone

from apps.cidadaos.models import Cidadao
from apps.contas.autenticacao import CHAVE_OPERADOR
from apps.contas.models import Operador
from apps.contas.papeis import Papel
from apps.institucional.models import Coordenacao, Demanda, Servico, Unidade


class CenarioBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        agora = timezone.now()

        cls.secretaria = Coordenacao.objects.create(
            id=str(uuid.uuid4()), nome='Secretaria de Assistência Social',
            sigla='SEMAS', criada_em=agora, atualizada_em=agora,
        )
        cls.psb = Coordenacao.objects.create(
            id=str(uuid.uuid4()), nome='Proteção Social Básica', sigla='PSB',
            superior=cls.secretaria, criada_em=agora, atualizada_em=agora,
        )
        cls.centro = Unidade.objects.create(
            id=str(uuid.uuid4()), nome='CRAS Centro', sigla='CRAS-C', tipo='CRAS',
            coordenacao=cls.psb, criada_em=agora, atualizada_em=agora,
        )
        cls.sul = Unidade.objects.create(
            id=str(uuid.uuid4()), nome='CRAS Sul', sigla='CRAS-S', tipo='CRAS',
            coordenacao=cls.psb, criada_em=agora, atualizada_em=agora,
        )
        cls.demanda = Demanda.objects.create(
            id=str(uuid.uuid4()), nome='Benefício Eventual', categoria='BENEFICIO',
            criada_em=agora, atualizada_em=agora,
        )

        # A recepção escolhe entre os serviços da própria unidade, e a demanda
        # municipal é deduzida deles.
        cls.servico = Servico.objects.create(
            id=str(uuid.uuid4()), unidade=cls.sul, nome='Alimentação e nutrição',
            descricao='Cesta básica e apoio alimentar', demanda=cls.demanda,
        )
        cls.servico_do_centro = Servico.objects.create(
            id=str(uuid.uuid4()), unidade=cls.centro, nome='Acolhimento',
            demanda=cls.demanda,
        )

        def operador(apelido, papel, unidade=None, ativo=True, nome=None):
            return Operador.objects.create(
                id=str(uuid.uuid4()), email=f'{apelido}@teste.local',
                nome=nome or apelido.title(), papel=papel, ativo=ativo,
                unidade=unidade, criado_em=agora, atualizado_em=agora,
            )

        cls.admin = operador('admin', Papel.ADMIN)
        cls.coordenador = operador('coordenador', Papel.COORDENADOR, cls.sul)
        cls.tecnico = operador('tecnico', Papel.TECNICO, cls.centro, nome='José Técnico')
        cls.recepcionista = operador('recepcao', Papel.RECEPCIONISTA, cls.sul)
        cls.visualizador = operador('visualizador', Papel.VISUALIZADOR, cls.sul)
        cls.inativo = operador('inativo', Papel.TECNICO, cls.sul, ativo=False)
        cls.sem_unidade = operador('sem_unidade', Papel.TECNICO)

        cls.cidadao = Cidadao.objects.create(
            id=str(uuid.uuid4()), nome='Antonia Ribeiro', cpf='529.982.247-25',
            email='antonia@teste.local', telefone='(97) 98111-0000',
            criado_em=agora, atualizado_em=agora,
        )

    def como(self, operador) -> Client:
        cliente = Client(headers={'host': 'localhost'})
        sessao = cliente.session
        sessao[CHAVE_OPERADOR] = operador.id
        sessao.save()
        cliente.cookies['sessionid'] = sessao.session_key
        return cliente
