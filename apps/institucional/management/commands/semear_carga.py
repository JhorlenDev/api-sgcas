"""
Carga de porte real — o SGCAS de um municipio de ~100 mil habitantes.

O `semear_demo` produz uma base *legivel*: 45 pessoas, cenarios montados a mao,
boa para conferir se cada tela mostra o que deveria. Esta aqui produz uma base
*pesada*, para responder outra pergunta: o que acontece quando a tabela tem
centenas de milhares de linhas e a consulta nao tem indice.

    docker compose run --rm api python manage.py semear_carga
    docker compose run --rm api python manage.py semear_carga --cidadaos 250000

Como e construida:

- **Em lotes, com `bulk_create`.** Uma linha por vez levaria horas. O lote e
  commitado sozinho: uma transacao unica de 1,4 milhao de linhas incha o WAL e,
  se falhar no fim, joga fora tudo o que ja custou.
- **`ignore_conflicts=True` com id deterministico.** Rodar de novo nao duplica e
  nao explode — o Postgres descarta o que ja existe. E o que torna a carga
  retomavel depois de uma interrupcao.
- **A fila viva e so a de HOJE.** Senha de dois anos atras em `AGUARDANDO` nao
  existe no mundo real: ou foi atendida, ou a pessoa desistiu. Sem essa regra a
  carga inventaria uma fila de milhares de pessoas esperando desde 2024, e o
  numero que aparece na tela deixaria de significar coisa alguma.

Depende do `semear_demo` ter rodado antes: as unidades, os servicos e o catalogo
de demandas vem de la. Esta carga acrescenta a rede que falta para o porte
(mais unidades, mais servidores) e o volume por cima.
"""
from __future__ import annotations

import random
import unicodedata
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.atendimentos.models import (
    AtendimentoDeRecepcao,
    BeneficioEventual,
    Caso,
    Encaminhamento,
    SenhaDaFila,
)
from apps.auditoria.models import RegistroDeAuditoria
from apps.cidadaos.models import Cidadao
from apps.contas.models import Operador
from apps.contas.papeis import Papel
from apps.institucional.models import Demanda, Servico, Unidade

# Namespace proprio: os ids da carga nao podem colidir com os do `semear_demo`,
# senao uma carga grande sobrescreveria os cenarios montados a mao.
NS = uuid.UUID('b2d7c410-93a6-4f8b-8f0d-1c5a6e2d47b9')

PRIMEIROS_M = [
    'José', 'João', 'Antônio', 'Francisco', 'Carlos', 'Paulo', 'Pedro', 'Lucas',
    'Luiz', 'Marcos', 'Raimundo', 'Sebastião', 'Manoel', 'Edilson', 'Valdemir',
    'Benedito', 'Jorge', 'Ivan', 'Wilson', 'Osvaldo', 'Getúlio', 'Ricardo',
    'Adalberto', 'Nilton', 'Domingos', 'Genésio', 'Roberto', 'Elias', 'Fábio',
    'Márcio', 'Rogério', 'Anderson', 'Cláudio', 'Erivaldo', 'Josué', 'Nonato',
]
PRIMEIROS_F = [
    'Maria', 'Ana', 'Francisca', 'Antônia', 'Raimunda', 'Josefa', 'Cleuza',
    'Rosilene', 'Adriana', 'Luciana', 'Vanderlúcia', 'Márcia', 'Elizângela',
    'Nazaré', 'Simone', 'Iracema', 'Silvana', 'Terezinha', 'Fernanda', 'Débora',
    'Patrícia', 'Aparecida', 'Joelma', 'Cristiane', 'Regina', 'Sônia', 'Lúcia',
    'Rosângela', 'Edinalva', 'Marlene', 'Ivanilde', 'Célia', 'Jocilene', 'Núbia',
]
MEIOS = [
    'da Silva', 'dos Santos', 'de Oliveira', 'Pereira', 'Ferreira', 'Rodrigues',
    'Almeida', 'Nascimento', 'Lima', 'Araújo', 'Carvalho', 'Gomes', 'Martins',
    'Rocha', 'Barbosa', 'Ribeiro', 'Alves', 'Monteiro', 'Cardoso', 'Teixeira',
    'Bentes', 'Tavares', 'Maciel', 'Braga', 'Vieira', 'Pinheiro', 'Cordeiro',
    'Nogueira', 'Trindade', 'Cavalcante', 'Batalha', 'Sampaio', 'Amorim',
    'Guimarães', 'Marinho', 'Serrão', 'Bezerra', 'Furtado', 'Mourão', 'Peixoto',
]

BAIRROS = [
    'Abial', 'Aeroporto', 'Alvorada', 'Bom Jesus', 'Bruno Fernandes', 'Caeté',
    'Colônia Ventura', 'Fátima', 'Jerusalém', 'Juruá', 'Monte Cristo',
    'Nossa Senhora de Nazaré', 'Olaria', 'Santa Luzia', 'Santo Antônio',
    'São Francisco', 'São João', 'Trapiche', 'Vila Nova', 'Jutaí', 'Bela Vista',
]

RACAS = ['PARDA', 'PRETA', 'BRANCA', 'INDIGENA', 'AMARELA', 'NAO_DECLARADA']
ESCOLARIDADES = [
    'SEM_INSTRUCAO', 'FUNDAMENTAL_INCOMPLETO', 'FUNDAMENTAL_COMPLETO',
    'MEDIO_INCOMPLETO', 'MEDIO_COMPLETO', 'SUPERIOR_INCOMPLETO', 'SUPERIOR_COMPLETO',
]
ESTADOS_CIVIS = ['SOLTEIRO', 'CASADO', 'UNIAO_ESTAVEL', 'SEPARADO', 'DIVORCIADO', 'VIUVO']

# Unidades que faltam para o porte. Um municipio de 100 mil habitantes nao opera
# a rede com 6 equipamentos — o `semear_demo` cadastra os do catalogo do
# repositorio, que e menor do que a realidade que se quer medir.
UNIDADES_EXTRAS = [
    ('CRAS-JU', 'CRAS Juruá', 'CRAS'),
    ('CRAS-AL', 'CRAS Alvorada', 'CRAS'),
    ('CRAS-SF', 'CRAS São Francisco', 'CRAS'),
    ('CRAS-TR', 'CRAS Trapiche', 'CRAS'),
    ('CRAS-JE', 'CRAS Jerusalém', 'CRAS'),
    ('CPOP-001', 'Centro POP', 'CENTRO_POP'),
    ('CASA-001', 'Casa de Passagem', 'ABRIGO'),
    ('SEDE-001', 'SEMAS — Sede', 'SEDE'),
]

SERVICOS_PADRAO = [
    ('PAIF — Proteção e Atendimento Integral à Família',
     'Acompanhamento familiar continuado.', 'Acompanhamento Familiar'),
    ('Cadastro Único — inclusão e atualização',
     'Inclusão e atualização cadastral.', 'Cadastro Único'),
    ('Benefício eventual — cesta básica',
     'Concessão de cesta básica por vulnerabilidade temporária.', 'Benefício Eventual'),
    ('Orientação e acesso a documentação civil',
     'Encaminhamento para 2ª via de documentos e registro civil.', 'Documentação Civil'),
    ('Serviço de Convivência e Fortalecimento de Vínculos',
     'Grupos por faixa etária.', 'Acompanhamento Familiar'),
    ('Visita domiciliar', 'Visita técnica ao domicílio.', 'Acompanhamento Familiar'),
    ('Abordagem social', 'Busca ativa em espaços públicos.', 'Situação de Rua'),
]

DEMANDAS_DE_BALCAO = [
    'Solicitação de cesta básica', 'Atualização do Cadastro Único',
    'Orientação sobre BPC', 'Pedido de auxílio funeral',
    'Encaminhamento para 2ª via de documentos', 'Denúncia de violação de direitos',
    'Solicitação de passagem para tratamento de saúde',
    'Acompanhamento de medida socioeducativa', 'Inclusão em serviço de convivência',
    'Situação de rua — abordagem social', 'Auxílio natalidade',
    'Orientação sobre Bolsa Família',
]

MOTIVOS_DE_BALCAO = [
    'Orientada no balcão: documentação incompleta, retornar com RG e comprovante de residência.',
    'Resolvido na recepção: agendamento do Cadastro Único realizado.',
    'Pessoa já possui atendimento em aberto na unidade.',
    'Benefício concedido há menos de 30 dias na rede. Orientada sobre o intervalo mínimo.',
    'Demanda é da saúde. Orientada a procurar a UBS do bairro.',
]

DESTINOS_EXTERNOS = [
    'Conselho Tutelar de Tefé', 'Defensoria Pública do Estado do Amazonas',
    'Ministério Público — Promotoria da Infância', 'UBS Nossa Senhora de Fátima',
    'Hospital Regional de Tefé', 'CAPS Tefé', 'Delegacia da Mulher',
]

NAVEGADORES = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/18.0',
    'Mozilla/5.0 (Linux; Android 14; Moto G84) AppleWebKit/537.36 Chrome/140.0 Mobile',
]

ACOES_DE_AUDITORIA = [
    ('READ', 'citizens'), ('READ', 'citizens'), ('READ', 'citizens'),
    ('CREATE', 'reception'), ('CREATE', 'queues'), ('UPDATE', 'cases'),
    ('CREATE', 'cases'), ('UPDATE', 'users'), ('ACESSO_NEGADO', 'cases'),
    ('ACESSO_NEGADO', 'citizens'), ('DELETE', 'itinerant-actions'),
]

PREFIXO_DA_SENHA = {'URGENTE': 'UR', 'ALTA': 'PR', 'NORMAL': 'NR', 'BAIXA': 'BX'}


def ident(chave: str) -> str:
    return str(uuid.uuid5(NS, chave))


def sem_acento(texto: str) -> str:
    return (
        unicodedata.normalize('NFKD', texto)
        .encode('ascii', 'ignore').decode('ascii')
    )


def cpf_de(semente: int) -> str:
    """CPF com digitos verificadores validos — a busca por documento e exercitada."""
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
    help = 'Gera uma base de porte municipal (~100 mil cidadãos) para medir o sistema sob carga.'

    def add_arguments(self, parser):
        parser.add_argument('--cidadaos', type=int, default=100_000)
        parser.add_argument('--anos', type=int, default=3,
                            help='Janela de histórico. Padrão: 3 anos.')
        parser.add_argument('--lote', type=int, default=2_000)
        parser.add_argument('--servidores', type=int, default=200)

    def handle(self, *args, **opcoes):
        self.rnd = random.Random(20260908)
        self.agora = timezone.localtime(timezone.now())
        self.lote = opcoes['lote']
        self.dias = max(opcoes['anos'], 1) * 365

        total_cidadaos = opcoes['cidadaos']
        # Proporcoes de um municipio com ~3 anos de sistema rodando. Nao sao
        # arredondamentos bonitos: sao a ordem de grandeza que faz a consulta
        # sem indice doer, que e o ponto do exercicio.
        total_casos = int(total_cidadaos * 2.2)
        total_balcao = int(total_cidadaos * 1.3)   # alem dos que viraram caso
        total_beneficios = int(total_cidadaos * 1.1)
        total_auditoria = int(total_cidadaos * 4.0)

        if not Servico.objects.exists():
            raise CommandError(
                'Rode primeiro: python manage.py semear_demo — as unidades, os '
                'serviços e o catálogo de demandas vêm de lá.'
            )

        inicio = timezone.now()
        self._aviso(
            f'Alvo: {total_cidadaos:,} cidadãos · {total_casos:,} casos · '
            f'{total_casos + total_balcao:,} passagens de recepção · '
            f'{total_beneficios:,} benefícios · {total_auditoria:,} registros de auditoria'
            .replace(',', '.')
        )

        self._rede()
        self.cidadaos = self._cidadaos(total_cidadaos)
        self._casos_e_fila(total_casos)
        self._balcao(total_balcao)
        self._beneficios(total_beneficios)
        self._auditoria(total_auditoria)

        self._relatorio(timezone.now() - inicio)

    # ─────────────────────────────── utilidades ───────────────────────────────

    def _aviso(self, texto: str) -> None:
        self.stdout.write(texto)
        self.stdout.flush()

    def _quando(self, dias_atras: int, hora: int = 9, minuto: int = 0):
        return (self.agora - timedelta(days=dias_atras)).replace(
            hour=hora, minute=minuto, second=0, microsecond=0
        )

    def _gravar(self, modelo, linhas: list, rotulo: str, feitos: int, alvo: int) -> int:
        modelo.objects.bulk_create(linhas, batch_size=self.lote, ignore_conflicts=True)
        feitos += len(linhas)
        self._aviso(f'  {rotulo}: {feitos:>9,}/{alvo:,}'.replace(',', '.'))
        return feitos

    # ──────────────────────────── rede institucional ────────────────────────────

    def _rede(self) -> None:
        """Unidades, serviços e servidores que faltam para o porte do município."""
        agora = timezone.now()
        demandas = {d.nome: d for d in Demanda.objects.all()}
        coordenacao = Unidade.objects.exclude(coordenacao__isnull=True).first()

        # O id NUNCA entra no `defaults` de um `update_or_create` cuja chave de
        # busca e outra coluna. No caminho de update o Django atribuiria uma PK
        # nova, o UPDATE por pk nao acharia linha, o ORM cairia para INSERT e a
        # constraint de unicidade estouraria. E o mesmo defeito que faz o
        # `cadastrar_servicos` do repositorio quebrar na segunda execucao.
        for sigla, nome, tipo in UNIDADES_EXTRAS:
            unidade = Unidade.objects.filter(sigla=sigla).first()
            if unidade is None:
                unidade = Unidade(id=ident(f'unidade:{sigla}'), sigla=sigla,
                                  criada_em=self._quando(self.dias))
            unidade.nome = nome
            unidade.tipo = tipo
            unidade.endereco = f'Rua {self.rnd.choice(MEIOS)}, {self.rnd.randint(10, 900)}'
            unidade.telefone = f'(97) 3343-{self.rnd.randint(1000, 9999)}'
            unidade.coordenacao = coordenacao.coordenacao if coordenacao else None
            unidade.ativa = True
            unidade.atualizada_em = agora
            unidade.excluida_em = None
            unidade.save()

        self.unidades = list(Unidade.ativas.all())

        for unidade in self.unidades:
            for nome_servico, descricao, categoria in SERVICOS_PADRAO:
                servico = Servico.objects.filter(unidade=unidade, nome=nome_servico).first()
                if servico is None:
                    servico = Servico(
                        id=ident(f'servico:{unidade.sigla}:{nome_servico}'),
                        unidade=unidade, nome=nome_servico,
                    )
                servico.descricao = descricao
                servico.demanda = demandas.get(categoria)
                servico.ativo = True
                servico.save()

        self.servicos_por_unidade = {}
        for servico in Servico.objects.select_related('unidade').all():
            self.servicos_por_unidade.setdefault(servico.unidade_id, []).append(servico)

        # Servidores. Papel operacional so — quem administra ja veio do demo.
        papeis = [Papel.TECNICO] * 5 + [Papel.ASSISTENTE_SOCIAL] * 3 + \
                 [Papel.RECEPCIONISTA] * 3 + [Papel.COORDENADOR]
        novos = []
        for i in range(200):
            nome = self._nome(i * 977 + 13)
            slug = sem_acento(nome).lower().replace(' ', '.')
            novos.append(Operador(
                id=ident(f'operador:{i}'),
                email=f'{slug}.{i}@tefe.am.gov.br',
                nome=nome,
                papel=papeis[i % len(papeis)],
                ativo=self.rnd.random() > 0.06,
                unidade=self.unidades[i % len(self.unidades)],
                cpf=cpf_de(500000 + i),
                keycloak_id=f'kc-carga-{i}',
                criado_em=self._quando(self.dias - i % 100),
                atualizado_em=agora,
            ))
        Operador.objects.bulk_create(novos, batch_size=self.lote, ignore_conflicts=True)

        self.operadores_por_unidade = {}
        for operador in Operador.objects.filter(ativo=True, excluido_em__isnull=True):
            self.operadores_por_unidade.setdefault(operador.unidade_id, []).append(operador)
        # Unidade sem equipe usaria uma lista vazia e quebraria o sorteio.
        reserva = list(Operador.objects.filter(ativo=True)[:20])
        for unidade in self.unidades:
            self.operadores_por_unidade.setdefault(unidade.id, reserva)

        self._aviso(
            f'  rede: {len(self.unidades)} unidades · '
            f'{Servico.objects.count()} serviços · {Operador.objects.count()} operadores'
        )

    def _nome(self, semente: int) -> str:
        r = random.Random(semente)
        feminino = semente % 2 == 0
        primeiro = r.choice(PRIMEIROS_F if feminino else PRIMEIROS_M)
        return f'{primeiro} {r.choice(MEIOS)} {r.choice(MEIOS)}'

    # ────────────────────────────────- cidadaos ────────────────────────────────

    def _cidadaos(self, alvo: int) -> list[str]:
        ids: list[str] = []
        linhas: list[Cidadao] = []
        feitos = 0

        for i in range(alvo):
            r = random.Random(i * 7919 + 3)
            identificador = ident(f'cidadao:{i}')
            ids.append(identificador)

            feminino = i % 2 == 0
            primeiro = r.choice(PRIMEIROS_F if feminino else PRIMEIROS_M)
            nome = f'{primeiro} {r.choice(MEIOS)} {r.choice(MEIOS)}'
            idade = r.randint(0, 92)
            bairro = BAIRROS[i % len(BAIRROS)]
            renda = r.choice([0, 218, 350, 706, 900, 1412, 1518, 2200])
            no_domicilio = r.randint(1, 7)

            linhas.append(Cidadao(
                id=identificador,
                nome=nome,
                cpf=cpf_de(i + 1000),
                nis=f'{(10000000000 + i * 7):011d}',
                email=f'{sem_acento(primeiro).lower()}.{i}@exemplo.tefe.am',
                rg=f'{(1000000 + i):07d} SSP/AM',
                telefone=f'(97) 9{(80000000 + i) % 100000000:08d}',
                endereco=f'Rua {r.choice(MEIOS)}, {r.randint(1, 2000)}',
                nascimento=self._quando(idade * 365 + r.randint(0, 364), 0),
                sexo='FEMININO' if feminino else 'MASCULINO',
                naturalidade=r.choice(['Tefé/AM', 'Alvarães/AM', 'Uarini/AM', 'Coari/AM', 'Manaus/AM']),
                escolaridade=r.choice(ESCOLARIDADES),
                identidade_de_genero='CISGENERO',
                raca=r.choice(RACAS),
                tem_deficiencia=r.random() < 0.08,
                estado_civil=r.choice(ESTADOS_CIVIS),
                bairro=bairro,
                cidade='Tefé',
                uf='AM',
                cep=f'6947{(i % 10000):04d}',
                observacoes=None,
                documentos={'cpf': cpf_de(i + 1000), 'orgaoExpedidor': 'SSP/AM'},
                endereco_detalhado={
                    'bairro': bairro, 'municipio': 'Tefé', 'uf': 'AM',
                    'zona': 'RURAL' if i % 9 == 0 else 'URBANA',
                },
                socioeconomico={
                    'rendaFamiliar': renda,
                    'rendaPerCapita': round(renda / no_domicilio, 2),
                    'pessoasNoDomicilio': no_domicilio,
                    'situacaoMoradia': r.choice(['PROPRIA', 'ALUGADA', 'CEDIDA', 'OCUPACAO']),
                },
                ingresso={'origem': 'DEMANDA_ESPONTANEA'},
                membros_da_familia=[],
                termo_de_responsabilidade={'aceito': True},
                anexos=[],
                autoriza_imagem=r.random() > 0.2,
                consentiu_tefe_cidadao_em=self._quando(r.randint(1, self.dias)),
                situacao_beneficiario=r.choice(['ATIVO', 'ATIVO', 'ATIVO', 'EM_ANALISE', 'INATIVO']),
                sincronizado=True,
                situacao_sincronizacao='SINCRONIZADO',
                familia_id=ident(f'familia:{i // 4}'),
                ativo=True,
                criado_em=self._quando(r.randint(1, self.dias)),
                atualizado_em=self._quando(r.randint(0, 120)),
            ))

            if len(linhas) >= self.lote:
                feitos = self._gravar(Cidadao, linhas, 'cidadãos', feitos, alvo)
                linhas = []

        if linhas:
            self._gravar(Cidadao, linhas, 'cidadãos', feitos, alvo)
        return ids

    # ───────────────────────────── casos e fila ─────────────────────────────

    def _casos_e_fila(self, alvo: int) -> None:
        """
        Caso, senha e a passagem de balcao que os originou — gerados juntos.

        Separar em tres passagens exigiria reler os casos do banco para achar a
        senha correspondente. Juntos, o estado de um determina o do outro sem ida
        e volta: e o mesmo acoplamento que `registrar_recepcao` tem no codigo.
        """
        contadores: dict[tuple, int] = {}
        # Duas distribuicoes, porque o dia de hoje nao se parece com o passado.
        # O historico esta quase todo encerrado; o que entrou hoje ainda esta em
        # curso. Aplicar a mesma proporcao aos dois faria a fila de hoje nascer
        # com 3% de gente esperando — um numero que nao descreve nenhuma manha
        # de CRAS e esvazia justamente a tela que se quer medir.
        situacoes = (
            [Caso.Situacao.CONCLUIDO] * 70 + [Caso.Situacao.ENCAMINHADO] * 15 +
            [Caso.Situacao.CANCELADO] * 10 + [Caso.Situacao.EM_TRIAGEM] * 3 +
            [Caso.Situacao.EM_ATENDIMENTO] * 2
        )
        situacoes_de_hoje = (
            [Caso.Situacao.EM_TRIAGEM] * 35 + [Caso.Situacao.EM_ATENDIMENTO] * 12 +
            [Caso.Situacao.CONCLUIDO] * 40 + [Caso.Situacao.ENCAMINHADO] * 8 +
            [Caso.Situacao.CANCELADO] * 5
        )
        prioridades = ['URGENTE'] * 4 + ['ALTA'] * 14 + ['NORMAL'] * 66 + ['BAIXA'] * 16

        casos: list[Caso] = []
        senhas: list[SenhaDaFila] = []
        visitas: list[AtendimentoDeRecepcao] = []
        encaminhamentos: list[Encaminhamento] = []
        feitos = 0

        # `criado_em` do atendimento de recepcao e `auto_now_add`: no bulk_create
        # o Django sobrescreveria tudo com o instante da carga, e os 350 mil
        # registros nasceriam com a mesma data. Desligar o automatismo durante a
        # carga e a unica forma de datar o historico sem cair em UPDATE linha a
        # linha depois.
        campo_data = AtendimentoDeRecepcao._meta.get_field('criado_em')
        campo_data.auto_now_add = False
        try:
            for i in range(alvo):
                r = random.Random(i * 104729 + 17)
                chave = f'caso:{i}'
                cidadao_id = self.cidadaos[r.randrange(len(self.cidadaos))]
                unidade = self.unidades[r.randrange(len(self.unidades))]
                servico = r.choice(self.servicos_por_unidade[unidade.id])
                equipe = self.operadores_por_unidade[unidade.id]
                tecnico = equipe[r.randrange(len(equipe))]
                prioridade = prioridades[i % len(prioridades)]

                # Sorteio uniforme na janela: o volume de hoje sai da propria
                # media diaria (~1/1095 do total em 3 anos), em vez de um numero
                # escolhido a mao que nao conversa com o resto do historico.
                dias = r.randint(0, self.dias)
                situacao = (
                    situacoes_de_hoje[i % len(situacoes_de_hoje)] if dias == 0
                    else situacoes[i % len(situacoes)]
                )
                abertura = self._quando(dias, r.randint(8, 16), r.randint(0, 59))
                encerrado = situacao in (
                    Caso.Situacao.CONCLUIDO, Caso.Situacao.ENCAMINHADO, Caso.Situacao.CANCELADO
                )
                fechamento = abertura + timedelta(days=r.randint(0, 30)) if encerrado else None
                if fechamento and fechamento > self.agora:
                    fechamento = self.agora

                em_triagem = situacao == Caso.Situacao.EM_TRIAGEM
                casos.append(Caso(
                    id=ident(chave),
                    protocolo=f'{abertura:%Y%m%d}-{ident(chave)[:6].upper()}',
                    situacao=situacao,
                    prioridade=prioridade,
                    descricao=(
                        f'[{abertura:%d/%m/%Y %H:%M}] {tecnico.nome}: '
                        f'Atendimento registrado para {servico.nome}.'
                    ),
                    cidadao_id=cidadao_id,
                    unidade=unidade,
                    tecnico=None if em_triagem else tecnico,
                    familia_id=None,
                    demanda_id=servico.demanda_id,
                    servico=servico,
                    aberto_em=abertura,
                    fechado_em=fechamento,
                    ativo=True,
                    criado_em=abertura,
                    atualizado_em=fechamento or abertura,
                ))

                # A senha so fica viva se for do dia. Senha de ontem em
                # AGUARDANDO nao existe: a fila zera no fechamento da unidade.
                if dias == 0:
                    estado = {
                        Caso.Situacao.EM_TRIAGEM: SenhaDaFila.Situacao.AGUARDANDO,
                        Caso.Situacao.EM_ATENDIMENTO: SenhaDaFila.Situacao.EM_ATENDIMENTO,
                        Caso.Situacao.CONCLUIDO: SenhaDaFila.Situacao.ATENDIDO,
                        Caso.Situacao.ENCAMINHADO: SenhaDaFila.Situacao.ATENDIDO,
                        Caso.Situacao.CANCELADO: SenhaDaFila.Situacao.DESISTIU,
                    }[situacao]
                else:
                    estado = (
                        SenhaDaFila.Situacao.DESISTIU
                        if situacao == Caso.Situacao.CANCELADO
                        else SenhaDaFila.Situacao.ATENDIDO
                    )

                prefixo = PREFIXO_DA_SENHA[prioridade]
                chave_contador = (unidade.id, abertura.date(), prefixo)
                contadores[chave_contador] = contadores.get(chave_contador, 0) + 1
                viva = estado == SenhaDaFila.Situacao.AGUARDANDO

                senhas.append(SenhaDaFila(
                    id=ident(f'senha:{chave}'),
                    senha=f'{prefixo}{contadores[chave_contador]:03d}',
                    cidadao_id=cidadao_id,
                    unidade=unidade,
                    prioridade=prioridade,
                    situacao=estado,
                    servico=servico.nome,
                    atendido_por=None if viva else tecnico,
                    chamado_em=None if viva else abertura + timedelta(minutes=r.randint(5, 90)),
                    finalizado_em=(
                        None if estado in (SenhaDaFila.Situacao.AGUARDANDO,
                                           SenhaDaFila.Situacao.EM_ATENDIMENTO)
                        else (fechamento or abertura + timedelta(hours=1))
                    ),
                    criado_em=abertura,
                    atualizado_em=abertura,
                ))

                recepcionista = equipe[(i + 3) % len(equipe)]
                visitas.append(AtendimentoDeRecepcao(
                    id=ident(f'recepcao:{chave}'),
                    cidadao_id=cidadao_id,
                    unidade=recepcionista.unidade,
                    atendido_por=recepcionista,
                    demanda=servico.nome,
                    desfecho=AtendimentoDeRecepcao.Desfecho.ENCAMINHADO,
                    motivo=None,
                    caso_id=ident(chave),
                    criado_em=abertura - timedelta(minutes=r.randint(5, 40)),
                ))

                if situacao == Caso.Situacao.ENCAMINHADO:
                    interno = r.random() < 0.45
                    destino = self.unidades[r.randrange(len(self.unidades))] if interno else None
                    encaminhamentos.append(Encaminhamento(
                        id=ident(f'encaminhamento:{chave}'),
                        caso_id=ident(chave),
                        encaminhado_por=tecnico,
                        unidade_destino=destino,
                        destino_externo=destino.nome if destino else r.choice(DESTINOS_EXTERNOS),
                        motivo='Demanda excede a competência da unidade de origem.',
                        situacao=r.choice([
                            Encaminhamento.Situacao.PENDENTE, Encaminhamento.Situacao.ACEITO,
                            Encaminhamento.Situacao.CONCLUIDO, Encaminhamento.Situacao.RECUSADO,
                        ]),
                        observacoes='Relatório técnico enviado ao destino.',
                        criado_em=fechamento or abertura,
                        atualizado_em=fechamento or abertura,
                    ))

                if len(casos) >= self.lote:
                    feitos = self._descarregar(
                        casos, senhas, visitas, encaminhamentos, feitos, alvo)
                    casos, senhas, visitas, encaminhamentos = [], [], [], []

            if casos:
                self._descarregar(casos, senhas, visitas, encaminhamentos, feitos, alvo)
        finally:
            campo_data.auto_now_add = True

    def _descarregar(self, casos, senhas, visitas, encaminhamentos, feitos, alvo) -> int:
        Caso.objects.bulk_create(casos, batch_size=self.lote, ignore_conflicts=True)
        SenhaDaFila.objects.bulk_create(senhas, batch_size=self.lote, ignore_conflicts=True)
        AtendimentoDeRecepcao.objects.bulk_create(
            visitas, batch_size=self.lote, ignore_conflicts=True)
        if encaminhamentos:
            Encaminhamento.objects.bulk_create(
                encaminhamentos, batch_size=self.lote, ignore_conflicts=True)
        feitos += len(casos)
        self._aviso(f'  casos+fila+recepção: {feitos:>9,}/{alvo:,}'.replace(',', '.'))
        return feitos

    # ───────────────────────── balcao sem caso e o resto ─────────────────────────

    def _balcao(self, alvo: int) -> None:
        """Passagens que terminaram na própria recepção — o 'não' também é atendimento."""
        campo_data = AtendimentoDeRecepcao._meta.get_field('criado_em')
        campo_data.auto_now_add = False
        linhas, feitos = [], 0
        try:
            for i in range(alvo):
                r = random.Random(i * 15485863 + 29)
                unidade = self.unidades[r.randrange(len(self.unidades))]
                equipe = self.operadores_por_unidade[unidade.id]
                operador = equipe[r.randrange(len(equipe))]
                dias = r.randint(0, self.dias)
                linhas.append(AtendimentoDeRecepcao(
                    id=ident(f'balcao:{i}'),
                    cidadao_id=self.cidadaos[r.randrange(len(self.cidadaos))],
                    unidade=operador.unidade,
                    atendido_por=operador,
                    demanda=r.choice(DEMANDAS_DE_BALCAO),
                    desfecho=AtendimentoDeRecepcao.Desfecho.FINALIZADO,
                    motivo=r.choice(MOTIVOS_DE_BALCAO),
                    caso_id=None,
                    criado_em=self._quando(dias, r.randint(8, 16), r.randint(0, 59)),
                ))
                if len(linhas) >= self.lote:
                    feitos = self._gravar(
                        AtendimentoDeRecepcao, linhas, 'balcão', feitos, alvo)
                    linhas = []
            if linhas:
                self._gravar(AtendimentoDeRecepcao, linhas, 'balcão', feitos, alvo)
        finally:
            campo_data.auto_now_add = True

    def _beneficios(self, alvo: int) -> None:
        tipos = [
            BeneficioEventual.Tipo.VULNERABILIDADE, BeneficioEventual.Tipo.VULNERABILIDADE,
            BeneficioEventual.Tipo.NASCIMENTO, BeneficioEventual.Tipo.MORTE,
            BeneficioEventual.Tipo.CALAMIDADE, BeneficioEventual.Tipo.OUTROS,
        ]
        linhas, feitos = [], 0
        for i in range(alvo):
            r = random.Random(i * 32452843 + 41)
            unidade = self.unidades[r.randrange(len(self.unidades))]
            equipe = self.operadores_por_unidade[unidade.id]
            tipo = tipos[i % len(tipos)]
            quando = self._quando(r.randint(0, self.dias), r.randint(8, 16), r.randint(0, 59))
            linhas.append(BeneficioEventual(
                id=ident(f'beneficio:{i}'),
                cidadao_id=self.cidadaos[r.randrange(len(self.cidadaos))],
                nome_da_pessoa='—',
                tipo=tipo,
                tipo_outro='Passagem fluvial' if tipo == BeneficioEventual.Tipo.OUTROS else None,
                descricao='Concessão registrada no atendimento.',
                registrado_por=equipe[r.randrange(len(equipe))],
                unidade=unidade,
                criado_em=quando,
                atualizado_em=quando,
            ))
            if len(linhas) >= self.lote:
                feitos = self._gravar(BeneficioEventual, linhas, 'benefícios', feitos, alvo)
                linhas = []
        if linhas:
            self._gravar(BeneficioEventual, linhas, 'benefícios', feitos, alvo)

        # `nome_da_pessoa` e obrigatorio e sai do cadastro. Preencher no laco
        # exigiria carregar os 100 mil nomes em memoria; um UPDATE com join
        # resolve no banco, que e onde o dado ja esta.
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE eventual_benefits AS b
                   SET "personName" = c.name
                  FROM citizens AS c
                 WHERE c.id = b."citizenId" AND b."personName" = '—'
            """)

    def _auditoria(self, alvo: int) -> None:
        atores = [o for equipe in self.operadores_por_unidade.values() for o in equipe][:120]
        linhas, feitos = [], 0
        for i in range(alvo):
            r = random.Random(i * 49979687 + 53)
            acao, entidade = ACOES_DE_AUDITORIA[i % len(ACOES_DE_AUDITORIA)]
            linhas.append(RegistroDeAuditoria(
                id=ident(f'auditoria:{i}'),
                operador=atores[r.randrange(len(atores))],
                acao=acao,
                entidade=entidade,
                entidade_id=(
                    self.cidadaos[r.randrange(len(self.cidadaos))]
                    if entidade == 'citizens' else None
                ),
                dados_antes=None,
                dados_depois=None if acao in ('READ', 'ACESSO_NEGADO') else {'campo': '[REDIGIDO]'},
                endereco_ip=f'10.20.{r.randint(0, 20)}.{r.randint(2, 250)}',
                navegador=NAVEGADORES[i % len(NAVEGADORES)],
                criado_em=self._quando(r.randint(0, self.dias), r.randint(7, 18), r.randint(0, 59)),
            ))
            if len(linhas) >= self.lote:
                feitos = self._gravar(RegistroDeAuditoria, linhas, 'auditoria', feitos, alvo)
                linhas = []
        if linhas:
            self._gravar(RegistroDeAuditoria, linhas, 'auditoria', feitos, alvo)

    # ──────────────────────────────── relatório ────────────────────────────────

    def _relatorio(self, duracao) -> None:
        hoje = self.agora.date()
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
            tamanho = cursor.fetchone()[0]

        linhas = [
            ('unidades', Unidade.ativas.count()),
            ('serviços', Servico.objects.count()),
            ('operadores', Operador.objects.count()),
            ('cidadãos', Cidadao.vigentes.count()),
            ('casos', Caso.vigentes.count()),
            ('senhas', SenhaDaFila.objects.count()),
            ('senhas aguardando hoje', SenhaDaFila.objects.filter(
                situacao=SenhaDaFila.Situacao.AGUARDANDO, criado_em__date=hoje).count()),
            ('atendimentos de recepção', AtendimentoDeRecepcao.objects.count()),
            ('benefícios eventuais', BeneficioEventual.vigentes.count()),
            ('encaminhamentos', Encaminhamento.objects.count()),
            ('registros de auditoria', RegistroDeAuditoria.objects.count()),
        ]
        largura = max(len(r) for r, _ in linhas)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Carga concluída.'))
        self.stdout.write('')
        total = 0
        for rotulo, valor in linhas:
            total += valor
            self.stdout.write(f'  {rotulo.ljust(largura)} : {valor:>10,}'.replace(',', '.'))
        self.stdout.write('')
        self.stdout.write(f'  {"total de linhas".ljust(largura)} : {total:>10,}'.replace(',', '.'))
        self.stdout.write(f'  {"tamanho do banco".ljust(largura)} : {tamanho:>10}')
        self.stdout.write(f'  {"tempo".ljust(largura)} : {str(duracao).split(".")[0]:>10}')
        self.stdout.write('')
