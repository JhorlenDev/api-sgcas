"""
Base de demonstracao do SGCAS — o sistema cheio, de ponta a ponta.

Semeia a rede inteira: coordenacoes, catalogo de demandas, operadores de todos
os papeis, cidadaos com prontuario completo, acoes itinerantes, casos nas cinco
situacoes, fila do dia com todas as senhas, atendimentos de balcao, beneficios
eventuais, encaminhamentos internos e externos e trilha de auditoria.

**Idempotente por construcao.** Todo id sai de `uuid5` sobre uma chave estavel,
entao rodar de novo atualiza as mesmas linhas em vez de duplicar. Nada e
apagado — nao ha `delete()` neste arquivo, de proposito: um seed que limpa a
base e uma bomba a um comando de distancia de uma base que nao era de teste.

As datas sao relativas ao momento da execucao. A fila semeada e sempre a de
HOJE, senao o painel da recepcao e o do atendente nasceriam zerados — os dois
contam por `criado_em__date=hoje`.

    docker compose run --rm api python manage.py semear_demo
"""
from __future__ import annotations

import random
import re
import unicodedata
import uuid
from datetime import timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.atendimentos.models import (
    AcaoItinerante,
    AtendimentoDeRecepcao,
    BeneficioEventual,
    Caso,
    Encaminhamento,
    SenhaDaFila,
)
from apps.auditoria.models import RegistroDeAuditoria
from apps.cidadaos.models import Cidadao
from apps.contas.models import Operador, PedidoDeAcesso
from apps.contas.papeis import Papel
from apps.institucional.management.commands.cadastrar_servicos import CATALOGO
from apps.institucional.models import Coordenacao, Demanda, Servico, Unidade

# Namespace fixo: e o que torna o id de cada registro reproduzivel entre
# execucoes. Trocar este valor faz o seed criar uma base paralela em vez de
# atualizar a existente.
NS = uuid.UUID('6f1c3d9e-0b7a-4f2c-9d51-5a9d0c2b7e41')

EMAIL_DEV = 'contato@marreiradigital.com.br'

BAIRROS = [
    'Abial', 'Aeroporto', 'Alvorada', 'Bom Jesus', 'Bruno Fernandes', 'Caeté',
    'Colônia Ventura', 'Fátima', 'Jerusalém', 'Juruá', 'Monte Cristo',
    'Nossa Senhora de Nazaré', 'Olaria', 'Santa Luzia', 'Santo Antônio',
    'São Francisco', 'São João', 'Trapiche', 'Vila Nova',
]

RACAS = ['PARDA', 'PRETA', 'BRANCA', 'INDIGENA', 'AMARELA', 'NAO_DECLARADA']
ESCOLARIDADES = [
    'SEM_INSTRUCAO', 'FUNDAMENTAL_INCOMPLETO', 'FUNDAMENTAL_COMPLETO',
    'MEDIO_INCOMPLETO', 'MEDIO_COMPLETO', 'SUPERIOR_INCOMPLETO', 'SUPERIOR_COMPLETO',
]
ESTADOS_CIVIS = ['SOLTEIRO', 'CASADO', 'UNIAO_ESTAVEL', 'SEPARADO', 'DIVORCIADO', 'VIUVO']

# (nome, sexo). Mistura proposital de faixas etarias e arranjos familiares:
# a rede de assistencia atende idoso sozinho, mae solo com filhos e familia
# inteira, e a tela precisa mostrar os tres.
PESSOAS = [
    ('Maria do Socorro Nascimento', 'FEMININO'),
    ('José Raimundo da Silva', 'MASCULINO'),
    ('Ana Lúcia Bentes', 'FEMININO'),
    ('Francisco das Chagas Pinto', 'MASCULINO'),
    ('Raimunda Alves de Souza', 'FEMININO'),
    ('Antônio Marcos Ferreira', 'MASCULINO'),
    ('Josefa Maria de Oliveira', 'FEMININO'),
    ('João Batista Cordeiro', 'MASCULINO'),
    ('Cleuza Maria Tavares', 'FEMININO'),
    ('Sebastião Nogueira Lima', 'MASCULINO'),
    ('Rosilene da Costa Braga', 'FEMININO'),
    ('Manoel Vieira dos Santos', 'MASCULINO'),
    ('Adriana Pinheiro Maciel', 'FEMININO'),
    ('Edilson Ramos de Castro', 'MASCULINO'),
    ('Luciana Barbosa Freire', 'FEMININO'),
    ('Carlos Alberto Mendonça', 'MASCULINO'),
    ('Vanderlúcia Gomes Rocha', 'FEMININO'),
    ('Paulo Sérgio Andrade', 'MASCULINO'),
    ('Márcia Regina Cavalcante', 'FEMININO'),
    ('Genésio Trindade Farias', 'MASCULINO'),
    ('Elizângela Moreira Dias', 'FEMININO'),
    ('Roberto Carlos Siqueira', 'MASCULINO'),
    ('Nazaré do Carmo Batalha', 'FEMININO'),
    ('Domingos Sávio Queiroz', 'MASCULINO'),
    ('Simone Cristina Peixoto', 'FEMININO'),
    ('Valdemir Aguiar Monteiro', 'MASCULINO'),
    ('Iracema Duarte Sampaio', 'FEMININO'),
    ('Benedito Almeida Correia', 'MASCULINO'),
    ('Silvana Ribeiro Amorim', 'FEMININO'),
    ('Jorge Luiz Bastos', 'MASCULINO'),
    ('Terezinha de Jesus Lopes', 'FEMININO'),
    ('Ivan Barros Guimarães', 'MASCULINO'),
    ('Fernanda Cristina Melo', 'FEMININO'),
    ('Wilson Prado Marinho', 'MASCULINO'),
    ('Débora Regina Passos', 'FEMININO'),
    ('Osvaldo Teixeira Rocha', 'MASCULINO'),
    ('Patrícia Helena Cunha', 'FEMININO'),
    ('Getúlio Aires do Vale', 'MASCULINO'),
    ('Aparecida Nunes Serrão', 'FEMININO'),
    ('Ricardo Vasconcelos Pena', 'MASCULINO'),
    ('Joelma Santana Bezerra', 'FEMININO'),
    ('Adalberto Furtado Neves', 'MASCULINO'),
    ('Cristiane Macedo Lira', 'FEMININO'),
    ('Nilton César Rebelo', 'MASCULINO'),
    ('Regina Célia Mourão', 'FEMININO'),
]

# Equipe alem das contas de teste: e o que faz o "quem atendeu" variar entre
# unidades e a coluna de tecnico deixar de repetir o mesmo nome.
EQUIPE = [
    ('Ana Cláudia Ferreira', Papel.ASSISTENTE_SOCIAL, 'CRAS-C', True),
    ('Lúcia Helena Maciel', Papel.RECEPCIONISTA, 'CRAS-C', True),
    ('Marcos Vinícius Tavares', Papel.TECNICO, 'CRAS-N', True),
    ('Raimunda Nonata Souza', Papel.RECEPCIONISTA, 'CRAS-N', True),
    ('Antônio Carlos Braga', Papel.GESTOR_ACOES_ITINERANTES, 'CRAS-N', True),
    ('Joana D\'Arc Batista', Papel.COORDENADOR, 'CRAS-S', True),
    ('Elias Bentes de Lima', Papel.TECNICO, 'CRAS-S', True),
    ('Marlene Souza Tapajós', Papel.RECEPCIONISTA, 'CRAS-S', True),
    ('Cleide Marques Pinheiro', Papel.ASSISTENTE_SOCIAL, 'CREAS-001', True),
    ('Iracy Nunes de Oliveira', Papel.RECEPCIONISTA, 'CREAS-001', True),
    ('Fábio Nogueira Cruz', Papel.TECNICO, 'CREAS-001', True),
    ('Sandra Regina Alves', Papel.COORDENADOR, 'CREAS-001', True),
    ('Miriam Castelo Branco', Papel.TECNICO, 'ILPI-001', True),
    # Desligada: existe para a tela de usuarios mostrar o estado inativo, que e
    # diferente de "nao existe" — o nome dela segue nos atendimentos antigos.
    ('Vera Lúcia Sarmento', Papel.TECNICO, 'CRAS-S', False),
]

SITUACOES_DE_RECEPCAO = [
    'Solicitação de cesta básica',
    'Atualização do Cadastro Único',
    'Orientação sobre BPC',
    'Pedido de auxílio funeral',
    'Encaminhamento para 2ª via de documentos',
    'Denúncia de violação de direitos',
    'Solicitação de passagem para tratamento de saúde',
    'Acompanhamento de medida socioeducativa',
    'Inclusão em serviço de convivência',
    'Situação de rua — abordagem social',
]

MOTIVOS_DE_BALCAO = [
    'Orientada no balcão: documentação incompleta, retornar com RG e comprovante de residência.',
    'Resolvido na recepção: agendamento do Cadastro Único feito para a próxima terça-feira.',
    'Pessoa já possui atendimento em aberto na unidade — orientada a aguardar contato da técnica.',
    'Benefício concedido há menos de 30 dias na rede. Orientada sobre o intervalo mínimo.',
    'Demanda é da saúde. Orientada a procurar a UBS do bairro; contato anotado para acompanhamento.',
]


def ident(chave: str) -> str:
    """Id estavel a partir de uma chave de negocio. Ver o cabecalho do modulo."""
    return str(uuid.uuid5(NS, chave))


def slug_de(nome: str) -> str:
    """
    `nome.sobrenome` sem acento, para o e-mail institucional.

    Sem a normalizacao sairia `ana.claudia.ferreira` com cedilha e til dentro do
    endereco — que existe no papel, mas nenhuma prefeitura emite, e na tela
    denuncia o dado como inventado.
    """
    sem_acento = (
        unicodedata.normalize('NFKD', nome)
        .encode('ascii', 'ignore')
        .decode('ascii')
    )
    return re.sub(r'[^a-z0-9.]+', '', sem_acento.lower().replace(' ', '.'))


def cpf_de(semente: int) -> str:
    """CPF com digitos verificadores corretos — a busca por documento e testada."""
    # Os 9 primeiros digitos sao o proprio numero da semente, e nao uma formula
    # sobre ela. A versao anterior calculava cada digito como
    # `(semente * 7 + constante_da_posicao) % 10`: como todos os digitos giravam
    # juntos com `semente * 7 % 10`, o prefixo inteiro tinha 10 valores
    # possiveis — 100 mil cidadaos sairam com 11 CPFs distintos, e a busca por
    # documento devolvia meio municipio.
    # `semente * 811` modulo 1e9 e uma bijecao (811 nao divide 2 nem 5), entao
    # sementes distintas continuam dando CPFs distintos — mas com os digitos
    # espalhados, em vez de oito zeros a esquerda denunciando o dado como
    # sintetico na primeira coluna da tela.
    base = [int(d) for d in f'{(semente * 811 + 123_456_789) % 1_000_000_000:09d}']
    for _ in range(2):
        peso = len(base) + 1
        soma = sum(d * (peso - i) for i, d in enumerate(base))
        resto = (soma * 10) % 11
        base.append(0 if resto == 10 else resto)
    return ''.join(str(d) for d in base)


class Command(BaseCommand):
    help = 'Semeia uma base de demonstração completa do SGCAS (idempotente).'

    def handle(self, *args, **opcoes):
        self.rnd = random.Random(20260908)
        self.agora = timezone.localtime(timezone.now())
        self.hoje = self.agora.date()

        with transaction.atomic():
            self.coordenacoes = self._coordenacoes()
            self.unidades = self._unidades()
            self.demandas = self._demandas()

        # So na base vazia. O `cadastrar_servicos` se diz idempotente, mas poe
        # um uuid novo no `defaults` do `update_or_create`: no segundo caminho a
        # PK muda, o UPDATE nao acha linha, o ORM cai para INSERT e a constraint
        # `servico_unico_por_unidade` estoura. Rodar de novo nao e opcao.
        if not Servico.objects.exists():
            call_command('cadastrar_servicos', verbosity=0)

        with transaction.atomic():
            self.servicos = self._categorizar_servicos()
            self.operadores = self._operadores()
            self._pedidos_de_acesso()
            self.acoes = self._acoes_itinerantes()
            self.cidadaos = self._cidadaos()
            totais = self._movimento()
            self._auditoria()

        self._relatorio(totais)

    # ─────────────────────────── rede institucional ───────────────────────────

    def _quando(self, dias_atras: int, hora: int, minuto: int = 0):
        base = self.agora - timedelta(days=dias_atras)
        return base.replace(hour=hora, minute=minuto, second=0, microsecond=0)

    def _coordenacoes(self) -> dict[str, Coordenacao]:
        criadas: dict[str, Coordenacao] = {}
        hierarquia = [
            ('SEMAS', 'Secretaria Municipal de Assistência Social', None),
            ('PSB', 'Proteção Social Básica', 'SEMAS'),
            ('PSE', 'Proteção Social Especial', 'SEMAS'),
        ]
        for sigla, nome, superior in hierarquia:
            registro, _ = Coordenacao.objects.update_or_create(
                id=ident(f'coordenacao:{sigla}'),
                defaults={
                    'nome': nome,
                    'sigla': sigla,
                    'ativa': True,
                    'superior': criadas.get(superior) if superior else None,
                    'criada_em': self._quando(400, 8),
                    'atualizada_em': self.agora,
                    'excluida_em': None,
                },
            )
            criadas[sigla] = registro
        return criadas

    def _unidades(self) -> dict[str, Unidade]:
        # As unidades ja vieram do `cadastrar_servicos`. Aqui elas ganham
        # coordenacao, endereco e telefone: sem coordenacao, `nome_qualificado`
        # devolve so o nome e a auditoria do pre-cadastro perde a secretaria.
        detalhes = {
            'CRAS-C': ('PSB', 'Rua Marechal Deodoro, 344 — Centro', '(97) 3343-1201'),
            'CRAS-N': ('PSB', 'Av. Brasil, 1210 — Juruá', '(97) 3343-1202'),
            'CRAS-S': ('PSB', 'Rua Santa Teresa, 88 — Santo Antônio', '(97) 3343-1203'),
            'CREAS-001': ('PSE', 'Rua Duque de Caxias, 500 — Centro', '(97) 3343-1250'),
            'ILPI-001': ('PSE', 'Estrada do Aeroporto, km 3 — Aeroporto', '(97) 3343-1270'),
            'RESINC-001': ('PSE', 'Rua Floriano Peixoto, 76 — Vila Nova', '(97) 3343-1280'),
        }
        por_sigla: dict[str, Unidade] = {}
        for unidade in Unidade.objects.all():
            dados = detalhes.get(unidade.sigla)
            if dados:
                coordenacao, endereco, telefone = dados
                unidade.coordenacao = self.coordenacoes[coordenacao]
                unidade.endereco = endereco
                unidade.telefone = telefone
                unidade.atualizada_em = self.agora
                unidade.save(update_fields=['coordenacao', 'endereco', 'telefone', 'atualizada_em'])
            por_sigla[unidade.sigla] = unidade
        return por_sigla

    def _demandas(self) -> dict[str, Demanda]:
        catalogo = [
            ('Acompanhamento Familiar', 'PAIF, PAEFI e acompanhamento continuado de famílias.'),
            ('Benefício Eventual', 'Cesta básica, auxílio natalidade, funeral e passagem.'),
            ('Violação de Direitos', 'Violência, negligência, abuso e medidas protetivas.'),
            ('Situação de Rua', 'Abordagem social, acolhimento e reinserção.'),
            ('Documentação Civil', 'Acesso a registro civil, RG, CPF e 2ª via de documentos.'),
            ('Cadastro Único', 'Inclusão e atualização cadastral para programas de transferência.'),
        ]
        criadas: dict[str, Demanda] = {}
        for nome, descricao in catalogo:
            registro, _ = Demanda.objects.update_or_create(
                id=ident(f'demanda:{nome}'),
                defaults={
                    'nome': nome,
                    'descricao': descricao,
                    'categoria': nome,
                    'ativa': True,
                    'criada_em': self._quando(400, 8),
                    'atualizada_em': self.agora,
                },
            )
            criadas[nome] = registro
        return criadas

    def _categorizar_servicos(self) -> dict[str, list[Servico]]:
        """
        Fecha a lacuna que o `cadastrar_servicos` deixa.

        Ele so liga o servico a categoria quando o catalogo de demandas ja
        existe — e o catalogo nao vem no repositorio. O que sobra sem categoria
        nao some da tela, mas fica fora do relatorio da rede, que e onde o
        numero da assistencia social e cobrado.
        """
        # A ordem importa: vale a primeira regra que casar. E o casamento e pelo
        # NOME do servico, nao pela descricao — "estudo psicossocial e documentos
        # tecnicos" tem a palavra "documentos" na descricao e nao e documentacao
        # civil. Descricao e prosa; nome e o que classifica.
        palavras = [
            (('cadastro único', 'cadastro unico', 'cadúnico'), 'Cadastro Único'),
            (('documentação civil', 'documentacao civil', 'certidão', 'registro civil',
              '2ª via', 'segunda via'), 'Documentação Civil'),
            (('situação de rua', 'abordagem social', 'população de rua', 'centro pop'),
             'Situação de Rua'),
            (('paefi', 'violência', 'violação', 'medida socioeducativa', 'abuso',
              'protetiva', 'liberdade assistida', 'enfrentamento'), 'Violação de Direitos'),
            (('cesta', 'alimentação', 'alimentacao', 'nutrição', 'benefício eventual',
              'natalidade', 'funeral', 'passagem'), 'Benefício Eventual'),
        ]
        # A categoria declarada no proprio `cadastrar_servicos` tem precedencia:
        # e a decisao de quem escreveu o catalogo. O casamento por palavra so
        # entra onde o catalogo deixou `None`.
        do_catalogo = {
            (sigla, nome_servico): categoria
            for sigla, _, _, servicos in CATALOGO
            for nome_servico, _, categoria in servicos
        }

        por_unidade: dict[str, list[Servico]] = {}
        for servico in Servico.objects.select_related('unidade').all():
            sigla = servico.unidade.sigla
            escolhida = do_catalogo.get((sigla, servico.nome))
            if not escolhida:
                alvo = servico.nome.lower()
                escolhida = next(
                    (nome for chaves, nome in palavras if any(c in alvo for c in chaves)),
                    'Acompanhamento Familiar',
                )
            demanda = self.demandas[escolhida]
            if servico.demanda_id != demanda.id:
                servico.demanda = demanda
                servico.save(update_fields=['demanda'])
            por_unidade.setdefault(sigla, []).append(servico)
        return por_unidade

    # ──────────────────────────────── pessoas ────────────────────────────────

    def _operadores(self) -> dict[str, Operador]:
        """
        As contas de teste usam o mesmo e-mail que o `dev-login` procura.

        Sem isso o seed criaria um segundo Paulo Marreira ao lado do que a
        entrada de desenvolvimento cria, e o painel — que conta por operador
        logado — nasceria zerado justamente para quem vai olhar a tela.
        """
        criados: dict[str, Operador] = {}

        papeis_de_teste = [
            (Papel.ADMIN, 'CRAS-C'),
            (Papel.COORDENADOR, 'CRAS-C'),
            (Papel.ASSISTENTE_SOCIAL, 'CRAS-C'),
            (Papel.TECNICO, 'CRAS-C'),
            (Papel.RECEPCIONISTA, 'CRAS-C'),
            (Papel.GESTOR_ACOES_ITINERANTES, 'CRAS-C'),
            (Papel.VISUALIZADOR, 'CRAS-C'),
        ]
        for papel, sigla in papeis_de_teste:
            email = EMAIL_DEV if papel == Papel.ADMIN else f'{papel.lower()}.{EMAIL_DEV}'
            nome = 'Paulo Marreira' if papel == Papel.ADMIN else f'Paulo Marreira ({papel})'
            operador = Operador.objects.filter(email=email).first()
            if operador is None:
                operador = Operador(id=ident(f'operador:{email}'), email=email)
            operador.nome = nome
            operador.papel = papel
            operador.ativo = True
            operador.excluido_em = None
            operador.unidade = self.unidades[sigla]
            operador.cpf = cpf_de(900 + len(criados))
            operador.keycloak_id = f'dev-{papel.lower()}'
            operador.criado_em = getattr(operador, 'criado_em', None) or self._quando(300, 9)
            operador.atualizado_em = self.agora
            operador.save()
            criados[papel] = operador

        for indice, (nome, papel, sigla, ativo) in enumerate(EQUIPE):
            # A conta e procurada pelo E-MAIL, nao pelo id derivado do nome.
            # O e-mail e a chave natural do operador — e a mesma que o
            # `dev-login` e o proprio login pelo Tefe Cidadao usam para casar a
            # conta local com a do realm. Procurar pelo id derivado quebra assim
            # que a regra de formatacao muda: o id novo nao acha a linha antiga,
            # o INSERT esbarra no e-mail unico, e o seed para de rodar.
            slug = slug_de(nome)
            email = f'{slug}@tefe.am.gov.br'
            operador = Operador.objects.filter(email=email).first()
            if operador is None:
                operador = Operador(id=ident(f'operador:{nome}'), email=email)
            operador.nome = nome
            operador.papel = papel
            operador.ativo = ativo
            operador.unidade = self.unidades[sigla]
            operador.cpf = cpf_de(100 + indice)
            operador.keycloak_id = f'kc-{slug}'
            operador.criado_em = self._quando(300 - indice * 7, 9)
            operador.atualizado_em = self.agora
            operador.excluido_em = None
            operador.save()
            criados[nome] = operador

        return criados

    def _pedidos_de_acesso(self) -> None:
        admin = self.operadores[Papel.ADMIN]
        pedidos = [
            ('Gilberto Farias de Menezes', 'gilberto.menezes@tefe.am.gov.br',
             PedidoDeAcesso.Situacao.PENDENTE, None, None, 2),
            ('Sônia Maria do Vale', 'sonia.vale@tefe.am.gov.br',
             PedidoDeAcesso.Situacao.PENDENTE, None, None, 1),
            ('Hélio Ramos Beleza', 'helio.beleza@tefe.am.gov.br',
             PedidoDeAcesso.Situacao.PENDENTE, None, None, 0),
            ('Cleide Marques Pinheiro', 'cleide.marques.pinheiro@tefe.am.gov.br',
             PedidoDeAcesso.Situacao.APROVADO, Papel.ASSISTENTE_SOCIAL, 'CREAS-001', 45),
            ('Wanderley Pontes Aragão', 'wanderley.aragao@tefe.am.gov.br',
             PedidoDeAcesso.Situacao.RECUSADO, None, None, 30),
        ]
        for nome, email, situacao, papel, sigla, dias in pedidos:
            decidido = situacao != PedidoDeAcesso.Situacao.PENDENTE
            PedidoDeAcesso.objects.update_or_create(
                id=ident(f'pedido:{email}'),
                defaults={
                    'keycloak_id': ident(f'keycloak:{email}'),
                    'email': email,
                    'nome': nome,
                    'situacao': situacao,
                    'pedido_em': self._quando(dias, 10, 15),
                    'decidido_em': self._quando(max(dias - 1, 0), 14) if decidido else None,
                    'decidido_por': admin if decidido else None,
                    'papel_concedido': papel,
                    'unidade_concedida': self.unidades[sigla].id if sigla else None,
                },
            )

    def _acoes_itinerantes(self) -> list[AcaoItinerante]:
        gestor = self.operadores[Papel.GESTOR_ACOES_ITINERANTES]
        braga = self.operadores['Antônio Carlos Braga']
        planejadas = [
            ('Mutirão de Cadastro Único — Caiambé', 'Comunidade Caiambé', 96, True, gestor, 'CRAS-N',
             'Atualização cadastral e orientação sobre BPC na comunidade ribeirinha.'),
            ('Assistência Itinerante — Nogueira', 'Comunidade Nogueira', 62, True, braga, 'CRAS-N',
             'Atendimento social, entrega de benefícios eventuais e busca ativa.'),
            ('Ação Rural — São Francisco do Bauana', 'São Francisco do Bauana', 38, True, gestor, 'CRAS-S',
             'Cadastro de famílias em situação de vulnerabilidade na zona rural.'),
            ('Ação Integrada — Missões', 'Comunidade Missões', 0, False, braga, 'CRAS-C',
             'Ação em andamento: cadastro, orientação previdenciária e documentação civil.'),
            ('Mutirão do Igapó Grande', 'Bom Jesus do Igapó Grande', -21, False, gestor, 'CRAS-N',
             'Programada com a Secretaria de Saúde. Transporte fluvial confirmado.'),
        ]
        acoes = []
        for titulo, local, dias, concluida, responsavel, sigla, descricao in planejadas:
            acao, _ = AcaoItinerante.objects.update_or_create(
                id=ident(f'acao:{titulo}'),
                defaults={
                    'titulo': titulo,
                    'descricao': descricao,
                    'local': local,
                    'data': self._quando(dias, 7, 30),
                    'observacoes': (
                        'Equipe deslocada por via fluvial. Prestação de contas entregue à coordenação.'
                        if concluida else
                        'Equipe montada. Levar formulários impressos e maleta de documentação.'
                    ),
                    'participantes': 0,
                    'cidadaos_atendidos': 0,
                    'beneficios_concedidos': 0,
                    'casos_abertos': 0,
                    'concluida': concluida,
                    'responsavel': responsavel,
                    'unidade': self.unidades[sigla],
                    'ativa': True,
                    'criada_em': self._quando(max(dias, 0) + 10, 9),
                    'atualizada_em': self.agora,
                    'excluida_em': None,
                },
            )
            acoes.append(acao)
        return acoes

    def _cidadaos(self) -> list[Cidadao]:
        cidadaos = []
        for indice, (nome, sexo) in enumerate(PESSOAS):
            chave = f'cidadao:{indice:03d}'
            idade = 6 + (indice * 7) % 74
            nascimento = self.agora.replace(
                year=self.agora.year - idade,
                month=1 + indice % 12,
                day=1 + (indice * 3) % 27,
                hour=0, minute=0, second=0, microsecond=0,
            )
            bairro = BAIRROS[indice % len(BAIRROS)]
            primeiro = nome.split()[0].lower()
            sobrenome = nome.split()[-1].lower()

            # Familias: cada bloco de 3 a partir do 12o compartilha o mesmo
            # `familia_id`, para o prontuario mostrar composicao familiar real.
            familia = ident(f'familia:{(indice - 12) // 3}') if indice >= 12 else None

            # Alguns registros nasceram numa acao itinerante, e nao no balcao —
            # e o que faz o balanco da acao ter numero para contar.
            acao = self.acoes[indice % 3] if indice % 7 == 0 else None

            renda = self.rnd.choice([0, 218, 350, 706, 900, 1412, 1518])
            pessoas_na_casa = 1 + (indice % 6)

            cidadao = Cidadao.objects.filter(id=ident(chave)).first() or Cidadao(id=ident(chave))
            cidadao.nome = nome
            cidadao.id_local = f'TFE-{indice:04d}' if indice % 4 == 0 else None
            cidadao.cpf = cpf_de(indice + 1)
            cidadao.nis = f'{(16000000000 + indice * 7919):011d}'
            cidadao.email = f'{primeiro}.{sobrenome}{indice}@exemplo.tefe.am'
            cidadao.rg = f'{(1000000 + indice * 137):07d} SSP/AM'
            cidadao.telefone = f'(97) 9{(81000000 + indice * 1237):08d}'
            cidadao.endereco = f'Rua {self.rnd.choice(["das Flores", "Amazonas", "Tefé", "Solimões", "da Paz", "Ipiranga"])}, {10 + indice * 3}'
            cidadao.nascimento = nascimento
            cidadao.sexo = sexo
            cidadao.naturalidade = self.rnd.choice(['Tefé/AM', 'Alvarães/AM', 'Uarini/AM', 'Coari/AM', 'Manaus/AM'])
            cidadao.escolaridade = ESCOLARIDADES[indice % len(ESCOLARIDADES)]
            cidadao.identidade_de_genero = 'CISGENERO'
            cidadao.raca = RACAS[indice % len(RACAS)]
            cidadao.tem_deficiencia = indice % 11 == 0
            cidadao.estado_civil = ESTADOS_CIVIS[indice % len(ESTADOS_CIVIS)]
            cidadao.bairro = bairro
            cidadao.cidade = 'Tefé'
            cidadao.uf = 'AM'
            cidadao.cep = f'69{(470000 + indice * 11):06d}'[:8]
            cidadao.observacoes = self.rnd.choice([
                'Família acompanhada pelo PAIF desde o ano passado.',
                'Idosa reside sozinha; vizinha é a referência de contato.',
                'Beneficiária do Bolsa Família. Cadastro atualizado na última visita.',
                'Encaminhada pela Unidade Básica de Saúde do bairro.',
                'Responsável por dois netos menores de idade.',
                None,
            ])
            cidadao.documentos = {
                'cpf': cidadao.cpf,
                'nis': cidadao.nis,
                'rg': cidadao.rg,
                'orgaoExpedidor': 'SSP/AM',
                'tituloEleitor': f'{(1000000000 + indice * 7717):012d}',
                'certidao': 'NASCIMENTO' if idade < 18 else 'CASAMENTO',
            }
            cidadao.endereco_detalhado = {
                'logradouro': cidadao.endereco,
                'numero': str(10 + indice * 3),
                'bairro': bairro,
                'municipio': 'Tefé',
                'uf': 'AM',
                'cep': cidadao.cep,
                'zona': 'RURAL' if acao is not None else 'URBANA',
                'referencia': self.rnd.choice([
                    'Próximo à igreja', 'Ao lado da escola municipal',
                    'Em frente ao campo de futebol', 'Última casa da rua',
                ]),
            }
            cidadao.socioeconomico = {
                'rendaFamiliar': renda,
                'rendaPerCapita': round(renda / pessoas_na_casa, 2),
                'pessoasNoDomicilio': pessoas_na_casa,
                'situacaoMoradia': self.rnd.choice(['PROPRIA', 'ALUGADA', 'CEDIDA', 'OCUPACAO']),
                'tipoConstrucao': self.rnd.choice(['ALVENARIA', 'MADEIRA', 'MISTA', 'PALAFITA']),
                'aguaEncanada': self.rnd.choice([True, False]),
                'energiaEletrica': True,
                'coletaDeLixo': self.rnd.choice([True, False]),
                'beneficios': self.rnd.sample(
                    ['BOLSA_FAMILIA', 'BPC', 'AUXILIO_BRASIL', 'SEGURO_DEFESO', 'NENHUM'],
                    k=self.rnd.randint(1, 2),
                ),
            }
            cidadao.ingresso = {
                'origem': 'ACAO_ITINERANTE' if acao is not None else 'DEMANDA_ESPONTANEA',
                'unidadeDeEntrada': (acao.unidade.nome if acao else self.unidades['CRAS-C'].nome),
                'dataDeEntrada': self._quando(200 - indice * 3, 9).isoformat(),
            }
            cidadao.membros_da_familia = [
                {
                    'nome': f'{parente} {nome.split()[-1]}',
                    'parentesco': parentesco,
                    'nascimento': f'{self.agora.year - anos}-0{1 + indice % 8}-1{indice % 9}',
                    'rendaPropria': 0,
                }
                for parente, parentesco, anos in self.rnd.sample(
                    [
                        ('Kauã', 'FILHO', 9), ('Yasmin', 'FILHA', 14), ('Davi', 'FILHO', 4),
                        ('Antônia', 'MAE', 68), ('Raimundo', 'PAI', 71), ('Lorena', 'NETA', 6),
                    ],
                    k=min(pessoas_na_casa - 1, 3) if pessoas_na_casa > 1 else 0,
                )
            ]
            cidadao.termo_de_responsabilidade = {
                'aceito': True,
                'aceitoEm': self._quando(200 - indice * 3, 9, 20).isoformat(),
                'responsavel': 'O próprio',
                'via': 'PRESENCIAL',
            }
            cidadao.anexos = []
            cidadao.autoriza_imagem = indice % 5 != 0
            cidadao.imagem_aceita_em = self._quando(200 - indice * 3, 9, 25) if indice % 5 != 0 else None
            cidadao.imagem_responsavel = 'O próprio' if indice % 5 != 0 else None
            # Revogacao gravada em campo proprio: e o que distingue "nunca
            # autorizou" de "autorizou e voltou atras" (LGPD, art. 8, §5).
            cidadao.imagem_revogada_em = self._quando(20, 11) if indice % 17 == 0 else None
            cidadao.consentiu_tefe_cidadao_em = self._quando(200 - indice * 3, 9, 30)
            cidadao.situacao_beneficiario = self.rnd.choice(
                ['ATIVO', 'ATIVO', 'ATIVO', 'EM_ANALISE', 'INATIVO']
            )
            cidadao.atualizado_por = 'Paulo Marreira'
            cidadao.sincronizado = True
            cidadao.situacao_sincronizacao = 'SINCRONIZADO'
            cidadao.acao_itinerante = acao
            cidadao.familia_id = familia
            cidadao.ativo = True
            cidadao.criado_em = self._quando(max(200 - indice * 3, 1), 9)
            cidadao.atualizado_em = self.agora
            cidadao.excluido_em = None
            cidadao.save()
            cidadaos.append(cidadao)
        return cidadaos

    # ─────────────────────────────── movimento ───────────────────────────────

    def _tecnicos_de(self, sigla: str) -> list[Operador]:
        equipe = [
            o for o in self.operadores.values()
            if o.unidade_id == self.unidades[sigla].id
            and o.papel in (Papel.TECNICO, Papel.ASSISTENTE_SOCIAL, Papel.COORDENADOR)
            and o.ativo
        ]
        return equipe or [self.operadores[Papel.TECNICO]]

    def _recepcionista_de(self, sigla: str) -> Operador:
        for operador in self.operadores.values():
            if operador.unidade_id == self.unidades[sigla].id and operador.papel == Papel.RECEPCIONISTA:
                return operador
        return self.operadores[Papel.RECEPCIONISTA]

    def _evolucao(self, autor: Operador, inicio, fim, linhas: list[str]) -> str:
        """
        Reproduz o formato que `anotar_caso` grava, para a timeline bater.

        As anotacoes se distribuem entre a abertura e o fechamento do caso, e o
        fim e limitado ao agora: evolucao datada no futuro nao existe no sistema
        real, e denuncia o registro como fabricado a quem le a tela.
        """
        fim = min(fim or self.agora, self.agora)
        if fim < inicio:
            fim = inicio
        passos = max(len(linhas) - 1, 1)
        partes = []
        for passo, texto in enumerate(linhas):
            momento = inicio + (fim - inicio) * (passo / passos)
            partes.append(f'[{momento:%d/%m/%Y %H:%M}] {autor.nome}: {texto}')
        return '\n\n'.join(partes)

    def _movimento(self) -> dict:
        """Casos, fila, balcão, benefícios e encaminhamentos — tudo coerente entre si."""
        contador_de_senhas: dict[tuple, int] = {}
        prefixos = {'URGENTE': 'UR', 'ALTA': 'PR', 'NORMAL': 'NR', 'BAIXA': 'BX'}

        def proxima_senha(unidade_sigla: str, dia, prioridade: str) -> str:
            prefixo = prefixos[prioridade]
            chave = (unidade_sigla, dia, prefixo)
            contador_de_senhas[chave] = contador_de_senhas.get(chave, 0) + 1
            return f'{prefixo}{contador_de_senhas[chave]:03d}'

        # Distribuicao dos casos. O peso do CRAS Centro e proposital: e a
        # unidade das contas de teste, e um painel vazio nao mostra nada.
        roteiro = [
            # (situacao, quantidade, dias_atras_min, dias_atras_max)
            (Caso.Situacao.EM_TRIAGEM, 13, 0, 0),
            (Caso.Situacao.EM_ATENDIMENTO, 7, 0, 0),
            (Caso.Situacao.CONCLUIDO, 22, 3, 170),
            (Caso.Situacao.ENCAMINHADO, 11, 5, 120),
            (Caso.Situacao.CANCELADO, 7, 2, 90),
        ]
        pesos_de_unidade = ['CRAS-C'] * 5 + ['CRAS-N'] * 2 + ['CRAS-S'] * 2 + ['CREAS-001'] * 2 + ['ILPI-001', 'RESINC-001']

        casos_criados = 0
        senhas_criadas = 0
        recepcoes_criadas = 0
        encaminhamentos_criados = 0
        sequencia = 0

        for situacao, quantidade, dias_min, dias_max in roteiro:
            for n in range(quantidade):
                sequencia += 1
                chave = f'caso:{situacao}:{n:02d}'
                cidadao = self.cidadaos[(sequencia * 5) % len(self.cidadaos)]
                sigla = pesos_de_unidade[sequencia % len(pesos_de_unidade)]
                unidade = self.unidades[sigla]
                servico = self.rnd.choice(self.servicos[sigla])
                equipe = self._tecnicos_de(sigla)
                tecnico = equipe[sequencia % len(equipe)]
                prioridade = self.rnd.choices(
                    ['URGENTE', 'ALTA', 'NORMAL', 'BAIXA'], weights=[1, 3, 6, 2]
                )[0]
                dias = self.rnd.randint(dias_min, dias_max) if dias_max > dias_min else dias_min
                abertura = self._quando(dias, 8 + (sequencia % 8), (sequencia * 7) % 60)

                # O caso das contas de teste: para o painel de quem loga como
                # TECNICO/ASSISTENTE_SOCIAL nao ficar vazio, parte do que e de
                # hoje no CRAS Centro fica com a conta de teste.
                if sigla == 'CRAS-C' and dias == 0 and sequencia % 3 == 0:
                    tecnico = self.operadores[Papel.TECNICO]

                em_aberto = situacao in (Caso.Situacao.EM_TRIAGEM,)

                # Calculado antes do relato: e o limite superior das anotacoes.
                if situacao in (Caso.Situacao.CONCLUIDO, Caso.Situacao.ENCAMINHADO):
                    fechamento = abertura + timedelta(days=self.rnd.randint(1, 20))
                elif situacao == Caso.Situacao.CANCELADO:
                    fechamento = abertura + timedelta(hours=3)
                else:
                    fechamento = None

                # O painel da recepcao conta por operador LOGADO. Parte do que e
                # de hoje fica com a conta de teste da recepcao e parte com a do
                # admin, para nenhum dos dois perfis abrir a tela zerada.
                recepcionista = self._recepcionista_de(sigla)
                if sigla == 'CRAS-C' and dias == 0:
                    if sequencia % 4 == 0:
                        recepcionista = self.operadores[Papel.ADMIN]
                    elif sequencia % 2 == 0:
                        recepcionista = self.operadores[Papel.RECEPCIONISTA]

                relato = {
                    Caso.Situacao.EM_TRIAGEM: [
                        f'Recepção encaminhou para {servico.nome}. Aguardando chamada da equipe técnica.',
                    ],
                    Caso.Situacao.EM_ATENDIMENTO: [
                        'Atendimento iniciado. Escuta qualificada realizada; família em vulnerabilidade temporária.',
                        'Providência: inclusão no acompanhamento do PAIF e agendamento de visita domiciliar.',
                    ],
                    Caso.Situacao.CONCLUIDO: [
                        'Situação identificada: insegurança alimentar após perda de renda no domicílio.',
                        'Providência tomada: concessão de benefício eventual e inclusão no CadÚnico.',
                        'Retorno necessário: reavaliação em 60 dias. Caso concluído nesta data.',
                    ],
                    Caso.Situacao.ENCAMINHADO: [
                        'Situação identificada: demanda excede a competência da unidade.',
                        'Providência: articulação com o serviço de destino e envio do relatório técnico.',
                    ],
                    Caso.Situacao.CANCELADO: [
                        'Cidadão chamado três vezes e não compareceu ao guichê. Senha liberada.',
                    ],
                }[situacao]

                caso, _ = Caso.objects.update_or_create(
                    id=ident(chave),
                    defaults={
                        'protocolo': f'{abertura:%Y%m%d}-{ident(chave)[:6].upper()}',
                        'situacao': situacao,
                        'prioridade': prioridade,
                        # Em triagem ninguem assumiu o caso ainda: a unica nota
                        # existente e a da recepcao que encaminhou.
                        'descricao': self._evolucao(
                            recepcionista if em_aberto else tecnico,
                            abertura, fechamento, relato,
                        ),
                        'cidadao': cidadao,
                        'unidade': unidade,
                        'tecnico': None if em_aberto else tecnico,
                        'acao_itinerante': cidadao.acao_itinerante,
                        'familia_id': cidadao.familia_id,
                        'demanda_id': servico.demanda_id,
                        'servico': servico,
                        'aberto_em': abertura,
                        'fechado_em': fechamento,
                        'ativo': True,
                        'criado_em': abertura,
                        'atualizado_em': self.agora,
                        'excluido_em': None,
                    },
                )
                casos_criados += 1

                # ── senha da fila, no estado que corresponde ao do caso ──
                estado_da_senha = {
                    Caso.Situacao.EM_TRIAGEM: SenhaDaFila.Situacao.AGUARDANDO,
                    Caso.Situacao.EM_ATENDIMENTO: SenhaDaFila.Situacao.EM_ATENDIMENTO,
                    Caso.Situacao.CONCLUIDO: SenhaDaFila.Situacao.ATENDIDO,
                    Caso.Situacao.ENCAMINHADO: SenhaDaFila.Situacao.ATENDIDO,
                    Caso.Situacao.CANCELADO: SenhaDaFila.Situacao.DESISTIU,
                }[situacao]
                chamado = None if estado_da_senha == SenhaDaFila.Situacao.AGUARDANDO else abertura + timedelta(minutes=25)
                finalizado = caso.fechado_em if estado_da_senha in (
                    SenhaDaFila.Situacao.ATENDIDO, SenhaDaFila.Situacao.DESISTIU
                ) else None

                SenhaDaFila.objects.update_or_create(
                    id=ident(f'senha:{chave}'),
                    defaults={
                        'senha': proxima_senha(sigla, abertura.date(), prioridade),
                        'cidadao': cidadao,
                        'unidade': unidade,
                        'prioridade': prioridade,
                        'situacao': estado_da_senha,
                        'servico': servico.nome,
                        'atendido_por': None if em_aberto else caso.tecnico,
                        'chamado_em': chamado,
                        'finalizado_em': finalizado,
                        'criado_em': abertura,
                        'atualizado_em': self.agora,
                    },
                )
                senhas_criadas += 1

                # ── registro do balcão que originou o caso ──
                visita, _ = AtendimentoDeRecepcao.objects.update_or_create(
                    id=ident(f'recepcao:{chave}'),
                    defaults={
                        'cidadao': cidadao,
                        # `registrar_recepcao` grava sempre a unidade de quem
                        # atendeu no balcao — que pode diferir da unidade do
                        # caso quando a recepcao ja encaminha para outra.
                        'unidade': recepcionista.unidade,
                        'atendido_por': recepcionista,
                        'acao_itinerante': cidadao.acao_itinerante,
                        'demanda': servico.nome,
                        'desfecho': AtendimentoDeRecepcao.Desfecho.ENCAMINHADO,
                        'motivo': None,
                        'caso': caso,
                    },
                )
                # `criado_em` e auto_now_add: so a UPDATE alcanca a coluna.
                AtendimentoDeRecepcao.objects.filter(id=visita.id).update(
                    criado_em=abertura - timedelta(minutes=12)
                )
                recepcoes_criadas += 1

                # ── encaminhamento, quando é o caso ──
                if situacao == Caso.Situacao.ENCAMINHADO:
                    interno = n % 2 == 0
                    destino = self.unidades['CREAS-001'] if interno and sigla != 'CREAS-001' else None
                    externo = '' if destino else self.rnd.choice([
                        'Conselho Tutelar de Tefé',
                        'Defensoria Pública do Estado do Amazonas',
                        'Ministério Público — Promotoria da Infância',
                        'UBS Nossa Senhora de Fátima',
                        'Hospital Regional de Tefé',
                    ])
                    Encaminhamento.objects.update_or_create(
                        id=ident(f'encaminhamento:{chave}'),
                        defaults={
                            'caso': caso,
                            'encaminhado_por': tecnico,
                            'unidade_destino': destino,
                            'destino_externo': destino.nome if destino else externo,
                            'motivo': self.rnd.choice([
                                'Situação de violação de direitos exige acompanhamento da proteção social especial.',
                                'Necessidade de atendimento jurídico para regularização de guarda.',
                                'Demanda de saúde mental identificada durante a escuta.',
                                'Suspeita de negligência contra pessoa idosa.',
                            ]),
                            'situacao': self.rnd.choice([
                                Encaminhamento.Situacao.PENDENTE,
                                Encaminhamento.Situacao.ACEITO,
                                Encaminhamento.Situacao.CONCLUIDO,
                                Encaminhamento.Situacao.RECUSADO,
                            ]),
                            'observacoes': 'Relatório técnico anexado ao prontuário e enviado ao destino.',
                            'criado_em': caso.fechado_em or abertura,
                            'atualizado_em': self.agora,
                        },
                    )
                    encaminhamentos_criados += 1

        # ── casos fechados HOJE pelas contas de teste ──
        #
        # O painel do atendente conta "atendidos hoje" e "finalizados hoje" por
        # `atendido_por`/`tecnico` = quem esta logado, com data de hoje. Sem
        # este bloco os dois cartoes nascem zerados justamente para quem vai
        # abrir a tela — o resto dos casos concluidos e historico.
        fechados_hoje = [
            (self.operadores[Papel.ADMIN], 'CONCLUIDO'),
            (self.operadores[Papel.TECNICO], 'CONCLUIDO'),
            (self.operadores[Papel.TECNICO], 'CONCLUIDO'),
            (self.operadores[Papel.ASSISTENTE_SOCIAL], 'CONCLUIDO'),
            (self.operadores[Papel.ADMIN], 'ENCAMINHADO'),
        ]
        for n, (autor, desfecho) in enumerate(fechados_hoje):
            chave = f'caso-hoje:{n}'
            cidadao = self.cidadaos[(n * 9 + 4) % len(self.cidadaos)]
            servico = self.rnd.choice(self.servicos['CRAS-C'])
            prioridade = ['ALTA', 'NORMAL', 'NORMAL', 'BAIXA', 'URGENTE'][n]
            abertura = self._quando(0, 8, 5 + n * 7)
            fechamento = self._quando(0, max(self.agora.hour - 1, 9), 30)
            relato = [
                'Atendimento realizado. Situação identificada e providências registradas.',
                'Desfecho registrado nesta data com orientação de retorno em 30 dias.',
            ]
            caso, _ = Caso.objects.update_or_create(
                id=ident(chave),
                defaults={
                    'protocolo': f'{abertura:%Y%m%d}-{ident(chave)[:6].upper()}',
                    'situacao': desfecho,
                    'prioridade': prioridade,
                    'descricao': self._evolucao(autor, abertura, fechamento, relato),
                    'cidadao': cidadao,
                    'unidade': self.unidades['CRAS-C'],
                    'tecnico': autor,
                    'acao_itinerante': None,
                    'familia_id': cidadao.familia_id,
                    'demanda_id': servico.demanda_id,
                    'servico': servico,
                    'aberto_em': abertura,
                    'fechado_em': fechamento,
                    'ativo': True,
                    'criado_em': abertura,
                    'atualizado_em': self.agora,
                    'excluido_em': None,
                },
            )
            casos_criados += 1

            SenhaDaFila.objects.update_or_create(
                id=ident(f'senha:{chave}'),
                defaults={
                    'senha': proxima_senha('CRAS-C', abertura.date(), prioridade),
                    'cidadao': cidadao,
                    'unidade': self.unidades['CRAS-C'],
                    'prioridade': prioridade,
                    'situacao': SenhaDaFila.Situacao.ATENDIDO,
                    'servico': servico.nome,
                    'atendido_por': autor,
                    'chamado_em': abertura + timedelta(minutes=18),
                    'finalizado_em': fechamento,
                    'criado_em': abertura,
                    'atualizado_em': self.agora,
                },
            )
            senhas_criadas += 1

            if desfecho == Caso.Situacao.ENCAMINHADO:
                Encaminhamento.objects.update_or_create(
                    id=ident(f'encaminhamento:{chave}'),
                    defaults={
                        'caso': caso,
                        'encaminhado_por': autor,
                        'unidade_destino': self.unidades['CREAS-001'],
                        'destino_externo': self.unidades['CREAS-001'].nome,
                        'motivo': 'Indício de violação de direitos identificado na escuta inicial.',
                        'situacao': Encaminhamento.Situacao.PENDENTE,
                        'observacoes': 'Encaminhado nesta data. Aguardando aceite da unidade de destino.',
                        'criado_em': fechamento,
                        'atualizado_em': self.agora,
                    },
                )
                encaminhamentos_criados += 1

            visita, _ = AtendimentoDeRecepcao.objects.update_or_create(
                id=ident(f'recepcao:{chave}'),
                defaults={
                    'cidadao': cidadao,
                    'unidade': self.unidades['CRAS-C'],
                    'atendido_por': self.operadores[Papel.RECEPCIONISTA],
                    'acao_itinerante': None,
                    'demanda': servico.nome,
                    'desfecho': AtendimentoDeRecepcao.Desfecho.ENCAMINHADO,
                    'motivo': None,
                    'caso': caso,
                },
            )
            AtendimentoDeRecepcao.objects.filter(id=visita.id).update(
                criado_em=abertura - timedelta(minutes=10)
            )
            recepcoes_criadas += 1

        # ── senhas de hoje sem caso: chamada em curso e desistência ──
        for n in range(4):
            cidadao = self.cidadaos[(n * 11 + 3) % len(self.cidadaos)]
            sigla = 'CRAS-C'
            prioridade = ['ALTA', 'NORMAL', 'NORMAL', 'BAIXA'][n]
            estado = [
                SenhaDaFila.Situacao.CHAMADO,
                SenhaDaFila.Situacao.CHAMADO,
                SenhaDaFila.Situacao.DESISTIU,
                SenhaDaFila.Situacao.AGUARDANDO,
            ][n]
            criada = self._quando(0, 8, 10 + n * 9)
            SenhaDaFila.objects.update_or_create(
                id=ident(f'senha-avulsa:{n}'),
                defaults={
                    'senha': proxima_senha(sigla, criada.date(), prioridade),
                    'cidadao': cidadao,
                    'unidade': self.unidades[sigla],
                    'prioridade': prioridade,
                    'situacao': estado,
                    'servico': self.rnd.choice(self.servicos[sigla]).nome,
                    'atendido_por': self.operadores[Papel.TECNICO] if estado != SenhaDaFila.Situacao.AGUARDANDO else None,
                    'chamado_em': criada + timedelta(minutes=20) if estado != SenhaDaFila.Situacao.AGUARDANDO else None,
                    'finalizado_em': criada + timedelta(minutes=35) if estado == SenhaDaFila.Situacao.DESISTIU else None,
                    'criado_em': criada,
                    'atualizado_em': self.agora,
                },
            )
            senhas_criadas += 1

        # ── atendimentos finalizados no próprio balcão (sem caso) ──
        for n in range(24):
            cidadao = self.cidadaos[(n * 13 + 7) % len(self.cidadaos)]
            sigla = ['CRAS-C', 'CRAS-C', 'CRAS-N', 'CRAS-S', 'CREAS-001'][n % 5]
            dias = 0 if n < 6 else self.rnd.randint(1, 120)
            if sigla == 'CRAS-C' and dias == 0:
                recepcionista = self.operadores[
                    Papel.ADMIN if n % 2 else Papel.RECEPCIONISTA
                ]
            else:
                recepcionista = self._recepcionista_de(sigla)
            visita, _ = AtendimentoDeRecepcao.objects.update_or_create(
                id=ident(f'balcao:{n:02d}'),
                defaults={
                    'cidadao': cidadao,
                    'unidade': recepcionista.unidade,
                    'atendido_por': recepcionista,
                    'acao_itinerante': None,
                    'demanda': SITUACOES_DE_RECEPCAO[n % len(SITUACOES_DE_RECEPCAO)],
                    'desfecho': AtendimentoDeRecepcao.Desfecho.FINALIZADO,
                    'motivo': MOTIVOS_DE_BALCAO[n % len(MOTIVOS_DE_BALCAO)],
                    'caso': None,
                },
            )
            AtendimentoDeRecepcao.objects.filter(id=visita.id).update(
                criado_em=self._quando(dias, 9 + n % 7, (n * 13) % 60)
            )
            recepcoes_criadas += 1

        beneficios = self._beneficios()
        self._fechar_balanco_das_acoes()

        return {
            'casos': casos_criados,
            'senhas': senhas_criadas,
            'recepcoes': recepcoes_criadas,
            'encaminhamentos': encaminhamentos_criados,
            'beneficios': beneficios,
        }

    def _beneficios(self) -> int:
        """
        Inclui de proposito o cenario que o historico municipal existe para pegar:
        a mesma pessoa recebendo no CRAS Centro e voltando a pedir no CRAS Sul
        dentro do mes corrente.
        """
        tipos = [
            BeneficioEventual.Tipo.VULNERABILIDADE,
            BeneficioEventual.Tipo.NASCIMENTO,
            BeneficioEventual.Tipo.MORTE,
            BeneficioEventual.Tipo.CALAMIDADE,
            BeneficioEventual.Tipo.OUTROS,
        ]
        descricoes = {
            BeneficioEventual.Tipo.VULNERABILIDADE: 'Cesta básica — insegurança alimentar após perda de renda.',
            BeneficioEventual.Tipo.NASCIMENTO: 'Kit enxoval — auxílio natalidade concedido à gestante.',
            BeneficioEventual.Tipo.MORTE: 'Auxílio funeral — translado e urna.',
            BeneficioEventual.Tipo.CALAMIDADE: 'Kit de limpeza e colchões — família atingida pela cheia do Solimões.',
            BeneficioEventual.Tipo.OUTROS: 'Passagem fluvial para tratamento de saúde em Manaus.',
        }
        criados = 0
        for n in range(34):
            cidadao = self.cidadaos[(n * 3 + 1) % len(self.cidadaos)]
            sigla = ['CRAS-C', 'CRAS-N', 'CRAS-S', 'CRAS-C', 'CREAS-001'][n % 5]
            tipo = tipos[n % len(tipos)]
            dias = 0 if n < 3 else self.rnd.randint(1, 300)
            equipe = self._tecnicos_de(sigla)
            BeneficioEventual.objects.update_or_create(
                id=ident(f'beneficio:{n:02d}'),
                defaults={
                    'cidadao': cidadao,
                    'nome_da_pessoa': cidadao.nome,
                    'tipo': tipo,
                    'tipo_outro': 'Passagem fluvial' if tipo == BeneficioEventual.Tipo.OUTROS else None,
                    'descricao': descricoes[tipo],
                    'registrado_por': equipe[n % len(equipe)],
                    'unidade': self.unidades[sigla],
                    'acao_itinerante': cidadao.acao_itinerante,
                    'criado_em': self._quando(dias, 10, (n * 17) % 60),
                    'atualizado_em': self.agora,
                    'excluido_em': None,
                },
            )
            criados += 1

        # O par que a recepcao precisa enxergar: duas concessoes no mes corrente,
        # em unidades diferentes, para a mesma pessoa.
        reincidente = self.cidadaos[0]
        # Os dias sao presos ao mes corrente: `no_mes_corrente` compara mes de
        # calendario, nao janela de 30 dias. Um valor fixo cai no mes anterior
        # sempre que o seed roda no comeco do mes, e o alerta que o cenario
        # existe para mostrar simplesmente nao aparece.
        no_mes = lambda d: min(d, max(self.agora.day - 1, 0))
        for n, (sigla, dias) in enumerate([('CRAS-C', no_mes(6)), ('CRAS-S', no_mes(1))]):
            equipe = self._tecnicos_de(sigla)
            BeneficioEventual.objects.update_or_create(
                id=ident(f'beneficio-duplicado:{n}'),
                defaults={
                    'cidadao': reincidente,
                    'nome_da_pessoa': reincidente.nome,
                    'tipo': BeneficioEventual.Tipo.VULNERABILIDADE,
                    'tipo_outro': None,
                    'descricao': 'Cesta básica — concessão registrada no mês corrente.',
                    'registrado_por': equipe[0],
                    'unidade': self.unidades[sigla],
                    'acao_itinerante': None,
                    'criado_em': self._quando(dias, 11),
                    'atualizado_em': self.agora,
                    'excluido_em': None,
                },
            )
            criados += 1
        return criados

    def _fechar_balanco_das_acoes(self) -> None:
        """
        Os contadores manuais passam a refletir os vinculos reais.

        Eles sao herdados de quando o numero era digitado a mao. Deixa-los em
        zero ao lado de vinculos existentes faria a tela de acoes mostrar uma
        acao "sem ninguem" que na verdade cadastrou dezenas de pessoas.
        """
        for acao in self.acoes:
            balanco = acao.balanco()
            acao.cidadaos_atendidos = balanco['cidadaos_cadastrados']
            acao.casos_abertos = balanco['casos_abertos_vinculados']
            acao.beneficios_concedidos = balanco['beneficios_vinculados']
            acao.participantes = max(
                balanco['cidadaos_cadastrados'] * 3,
                0 if not acao.concluida else 25,
            )
            acao.atualizada_em = self.agora
            acao.save(update_fields=[
                'cidadaos_atendidos', 'casos_abertos', 'beneficios_concedidos',
                'participantes', 'atualizada_em',
            ])

    def _auditoria(self) -> None:
        """
        Trilha no mesmo formato do middleware — inclusive as tentativas barradas.

        Uma trilha so com sucesso nao serve para o que ela existe: o registro que
        importa numa apuracao costuma ser o acesso negado.
        """
        atores = [
            self.operadores[Papel.ADMIN],
            self.operadores[Papel.TECNICO],
            self.operadores[Papel.RECEPCIONISTA],
            self.operadores['Ana Cláudia Ferreira'],
            self.operadores['Fábio Nogueira Cruz'],
            self.operadores['Marcos Vinícius Tavares'],
        ]
        navegadores = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/18.0',
            'Mozilla/5.0 (Linux; Android 14; Moto G84) AppleWebKit/537.36 Chrome/140.0 Mobile',
        ]
        receitas = [
            ('READ', 'citizens', None),
            ('READ', 'citizens', None),
            ('CREATE', 'reception', {'desfecho': 'ENCAMINHADO', 'servico_id': '[REDIGIDO]'}),
            ('CREATE', 'queues', {'acao': 'chamar-proximo'}),
            ('UPDATE', 'cases', {'observacao': '[REDIGIDO]'}),
            ('CREATE', 'cases', {'situacao': 'CONCLUIDO', 'relato': '[REDIGIDO]'}),
            ('UPDATE', 'users', {'papel': 'TECNICO'}),
            ('ACESSO_NEGADO', 'cases', None),
            ('ACESSO_NEGADO', 'citizens', None),
            ('DELETE', 'itinerant-actions', None),
        ]
        for n in range(140):
            acao, entidade, corpo = receitas[n % len(receitas)]
            ator = atores[n % len(atores)]
            alvo = self.cidadaos[(n * 7) % len(self.cidadaos)]
            RegistroDeAuditoria.objects.update_or_create(
                id=ident(f'auditoria:{n:03d}'),
                defaults={
                    'operador': ator,
                    'acao': acao,
                    'entidade': entidade,
                    'entidade_id': alvo.id if entidade == 'citizens' else None,
                    'dados_antes': {'papel': 'RECEPCIONISTA'} if entidade == 'users' else None,
                    'dados_depois': corpo,
                    'endereco_ip': f'10.20.{n % 6}.{20 + n % 200}',
                    'navegador': navegadores[n % len(navegadores)],
                    'criado_em': self._quando(n // 6, 8 + n % 9, (n * 11) % 60),
                },
            )

    # ──────────────────────────────── relatório ────────────────────────────────

    def _relatorio(self, totais: dict) -> None:
        escrever = self.stdout.write
        escrever('')
        escrever(self.style.SUCCESS('Base de demonstração semeada.'))
        escrever('')
        linhas = [
            ('coordenações', Coordenacao.objects.count()),
            ('unidades', Unidade.ativas.count()),
            ('demandas (categorias municipais)', Demanda.objects.count()),
            ('serviços', Servico.objects.count()),
            ('serviços sem categoria', Servico.objects.filter(demanda__isnull=True).count()),
            ('operadores', Operador.objects.count()),
            ('pedidos de acesso pendentes',
             PedidoDeAcesso.objects.filter(situacao=PedidoDeAcesso.Situacao.PENDENTE).count()),
            ('cidadãos', Cidadao.vigentes.count()),
            ('ações itinerantes', AcaoItinerante.vigentes.count()),
            ('casos', Caso.vigentes.count()),
            ('senhas na fila (total)', SenhaDaFila.objects.count()),
            ('senhas aguardando hoje',
             SenhaDaFila.objects.filter(
                 situacao=SenhaDaFila.Situacao.AGUARDANDO, criado_em__date=self.hoje
             ).count()),
            ('atendimentos de recepção', AtendimentoDeRecepcao.objects.count()),
            ('benefícios eventuais', BeneficioEventual.vigentes.count()),
            ('encaminhamentos', Encaminhamento.objects.count()),
            ('registros de auditoria', RegistroDeAuditoria.objects.count()),
        ]
        largura = max(len(rotulo) for rotulo, _ in linhas)
        for rotulo, valor in linhas:
            escrever(f'  {rotulo.ljust(largura)} : {valor}')
        escrever('')
        escrever('  Entre em: http://localhost:3001/api/auth/dev-login')
        escrever('')
