# api-sgcas

Backend Django/DRF do SGCAS — Sistema de Gestão de Casos da Assistência Social de Tefé.

Este projeto expõe a API consumida pelo `front-sgcas`, integra login via Keycloak/Tefé Cidadão e organiza o fluxo de recepção, fila, atendimento e acompanhamentos.

## Stack

- Python 3.12
- Django 5.1
- Django REST Framework
- PostgreSQL
- Keycloak/Tefé Cidadão

## Como rodar localmente

### 1. Criar ambiente Python

```bash
cd api-sgcas
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` e confira principalmente:

```env
DATABASE_URL=postgresql://sgcas:change-me@localhost:5434/sgcas
DJANGO_SECRET_KEY=inseguro-apenas-para-desenvolvimento
FRONTEND_URL=http://localhost:3000
CORS_ORIGIN=http://localhost:3000

KEYCLOAK_URL=https://sso.tefe.am.gov.br
KEYCLOAK_REALM=prefeitura
KEYCLOAK_CLIENT_ID=sgcas-web
KEYCLOAK_CLIENT_SECRET=troque-pelo-secret-real
KEYCLOAK_REDIRECT_URI=http://localhost:3000/api/auth/keycloak/callback
```

### 3. Subir banco com Docker

```bash
docker compose up -d postgres
```

Por padrão o PostgreSQL local fica em:

```txt
localhost:5434
database: sgcas
user: sgcas
password: change-me
```

### 4. Rodar migrations

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py migrate
```

### 5. Cadastrar dados institucionais básicos

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py cadastrar_servicos
```

### 6. Subir API

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py runserver 0.0.0.0:8000
```

API local:

```txt
http://localhost:8000/api
```

## Rodar com Docker

```bash
cp .env.example .env
docker compose up -d --build
```

Se rodar a API dentro do Docker, o serviço `api` usa o PostgreSQL interno do compose.

## Pôr em produção

O container sobe direto no gunicorn e **não roda migrations sozinho**. A ordem é:

```bash
docker compose build api
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py cadastrar_servicos   # só na primeira vez
docker compose up -d
```

Pular o `migrate` deixa a API no ar contra um esquema desatualizado, e os
endpoints que usam as colunas novas falham em tempo de requisição.

### Variáveis que precisam de valor real

`.env.example` traz só marcadores. Antes de expor a API:

| Variável | Observação |
| --- | --- |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | domínio real da API |
| `DJANGO_SECRET_KEY` | a API se recusa a subir com a chave padrão e `DEBUG=False` |
| `POSTGRES_PASSWORD` | senha do banco |
| `CORS_ORIGIN` / `FRONTEND_URL` | domínio do front |
| `KEYCLOAK_CLIENT_SECRET` | segredo do cliente no SSO |

### Cifragem dos dados pessoais

Desligada por padrão. Para ligar, gere **duas** chaves distintas:

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

Preencha `PII_ENCRYPTION_KEY` e `PII_HMAC_KEY`, ponha `PII_ENCRYPTION_ENABLED=true`
e rode o backfill:

```bash
docker compose run --rm api python manage.py cifrar_dados_pessoais --simular
docker compose run --rm api python manage.py cifrar_dados_pessoais
```

O backfill não é opcional numa base que já tem cadastros: com a cifragem ligada
a busca por documento passa a usar índice cego, e quem foi gravado antes não tem
índice — sumiria da consulta por CPF, NIS e e-mail sem erro nenhum na tela.

**Guarde as chaves fora do servidor.** Sem elas não há como decifrar o que já
foi gravado.

### Integração com o Tefé Cidadão

O pré-cadastro cria a conta da pessoa no SSO durante o atendimento. Vem
desligado; para ativar, preencha `PRECADASTRO_CLIENT_ID` e
`PRECADASTRO_CLIENT_SECRET` (conta de serviço no realm) e ponha
`PRECADASTRO_ENABLED=true`.

Falha no SSO nunca derruba o cadastro: a pessoa já foi atendida, o registro
dela existe, e o resultado volta na resposta para o atendente saber o que dizer.

## Login e permissões

O SGCAS não usa senha própria. O login começa aqui:

```txt
GET /api/auth/keycloak/login
```

O Keycloak deve ter o client:

```txt
sgcas-web
```

Com callback:

```txt
http://localhost:3000/api/auth/keycloak/callback
```

Roles esperadas no Keycloak, de preferência como client roles do `sgcas-web`:

```txt
ADMIN
COORDENADOR
ASSISTENTE_SOCIAL
TECNICO
RECEPCIONISTA
GESTOR_ACOES_ITINERANTES
VISUALIZADOR
```

Se o usuário entrar pelo Tefé Cidadão sem role SGCAS, a API registra um pedido de acesso e o front mostra a tela de aguardando liberação. O administrador aprova o pedido, escolhe o perfil e vincula uma unidade.

## Fluxo principal do sistema

### 1. Recepção

A recepção busca ou cadastra o cidadão.

Depois de selecionar o cidadão, o sistema mostra histórico e casos recentes para evitar duplicidade.

A recepção pode:

- finalizar no balcão, registrando o motivo;
- criar um novo caso;
- gerar senha para fila;
- definir prioridade da senha.

Senhas seguem o padrão:

```txt
UR001 = urgente
PR001 = prioridade alta
NR001 = normal
BX001 = baixa
```

### 2. Fila / Atendimento

O atendente chama o próximo da fila.

Ao chamar:

- a senha muda para `EM_ATENDIMENTO`;
- o caso muda para `EM_ATENDIMENTO`;
- o técnico/atendente fica vinculado;
- a API devolve cidadão, caso e histórico.

Durante o atendimento, o atendente pode:

- registrar observação/evolução;
- encaminhar para outra unidade ou órgão externo;
- concluir o atendimento;
- marcar como não compareceu.

### 3. Não compareceu

Quando a pessoa é chamada e não aparece:

- a senha vira `DESISTIU`;
- o caso vira `CANCELADO`;
- uma observação é gravada no caso.

Endpoint:

```txt
POST /api/queues/:senha_id/nao-compareceu
```

### 4. Acompanhamentos

A aba de acompanhamentos mostra os casos por situação:

- `EM_TRIAGEM`
- `EM_ATENDIMENTO`
- `CONCLUIDO`
- `ENCAMINHADO`
- `CANCELADO`

O modal do caso mostra dados conforme a etapa atual.

## Listagens: paginação e filtros

Toda listagem grande é paginada e devolve um envelope, não uma lista solta:

```json
{ "itens": [...], "total": 220065, "pagina": 1, "por_pagina": 25, "paginas": 8803 }
```

`total` é o número de registros que casam com o filtro — contado no banco, não o
tamanho da página. É a distinção que importa: antes as listagens eram cortadas
em 100 e quem consumia não tinha como saber que havia mais, nem como pedir o
resto. Numa base municipal isso virava número errado na tela.

### Parâmetros comuns

| Parâmetro | O que faz |
| --- | --- |
| `page` | Página, começando em 1. |
| `limit` | Itens por página. Teto de **100** — paginação sem teto é o corte antigo com outro nome. |
| `de` / `ate` | Recorte por data (`AAAA-MM-DD`), as duas pontas inclusivas, no fuso do projeto. |
| `ordenar` | Só os valores que a rota declara. Valor não suportado devolve **400** com a lista do que é aceito. |

Parâmetro malformado é **recusado com 400**, não ignorado: cair para o padrão em
silêncio faria a tela mostrar a página 1 achando que mostra outra.

### Filtros por rota

| Rota | Filtros | Ordenações |
| --- | --- | --- |
| `GET /api/cases/` | `situacao`, `prioridade`, `unidade`, `tecnico`, `servico`, `demanda`, `cidadao`, `busca` (protocolo ou nome), `de`, `ate` | `-aberto_em` (padrão), `aberto_em`, `-atualizado_em`, `prioridade` |
| `GET /api/cases/resumo` | os mesmos da listagem | — |
| `GET /api/citizens/` | `busca` (nome, CPF, NIS ou e-mail), `bairro`, `sexo`, `situacao` | `-atualizado_em` (padrão), `nome`, `-nome`, `-criado_em` |
| `GET /api/queues/` | `unidade`, `prioridade`, `situacao` (padrão `AGUARDANDO`) | por prioridade e chegada |
| `GET /api/users/` | `busca` (nome ou e-mail), `papel`, `unidade`, `ativo`, `sem_unidade` | por nome |
| `GET /api/reception/atendimentos` | `desfecho`, `cidadao`, `de`, `ate`, `todos=1` (unidade inteira) | mais recentes |
| `GET /api/auditoria/` | `entidade`, `registro`, `acao`, `operador`, `de`, `ate` | `-criado_em` (padrão), `criado_em` |

### `GET /api/cases/resumo`

Contagem por situação, no mesmo recorte da listagem:

```json
{
  "total": 220065,
  "por_situacao": {"EM_TRIAGEM": 6682, "EM_ATENDIMENTO": 4420, "CONCLUIDO": 153970, ...},
  "em_acompanhamento": 11102,
  "finalizados": 186958
}
```

Existe porque contar no cliente sobre a página recebida responde outra pergunta:
quantos casos há *naquela página*, e não na rede.

## Índices

As consultas de listagem dependem de índice em coluna de data e de status. Eles
vêm nas migrations `atendimentos.0007`, `auditoria.0002` e `cidadaos.0003`.

A busca por nome (`ILIKE '%termo%'`) não é atendida por B-tree e usa índice de
trigrama (`cidadaos.0004`), que exige a extensão **`pg_trgm`**:

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

A migration cria a extensão sozinha, mas `CREATE EXTENSION` pede privilégio
elevado. Em Postgres gerenciado, libere `pg_trgm` no painel antes de migrar — se
a migration falhar por permissão, é isso, e não erro de esquema.

Numa base já grande, `CREATE INDEX` bloqueia escrita enquanto constrói. A
migration do trigrama usa `CONCURRENTLY`; as demais não — rode em janela de
manutenção, ou converta-as antes de aplicar em produção.

## Endpoints principais

```txt
GET  /api/auth/me
GET  /api/auth/keycloak/login
POST /api/auth/logout
POST /api/auth/access-request/resend

GET  /api/access-requests/
POST /api/access-requests/:id/aprovar

GET    /api/users/                     paginado + filtros
PUT    /api/users/:id
PUT    /api/users/:id/perfil
DELETE /api/users/:id

GET  /api/citizens/                    paginado + filtros
POST /api/citizens/novo
GET  /api/citizens/:id
GET  /api/citizens/:id/historico

GET  /api/reception/painel
GET  /api/reception/atendimentos       paginado + filtros
POST /api/reception/atendimento

GET  /api/queues/                      paginado + filtros
GET  /api/queues/painel
POST /api/queues/chamar-proximo
POST /api/queues/:senha_id/nao-compareceu

GET  /api/cases/                       paginado + filtros
GET  /api/cases/resumo                 contagem por situação
POST /api/cases/:id/observacao
POST /api/cases/:id/encaminhar
POST /api/cases/:id/concluir

GET  /api/auditoria/                   paginado + filtros

GET  /api/institutional/units
GET  /api/institutional/services
GET  /api/institutional/demands
GET  /api/institutional/coordinations
```

## Popular a base para desenvolvimento

```bash
# rede, cidadãos, casos, fila e auditoria — legível, 45 pessoas
docker compose run --rm api python manage.py semear_demo

# porte municipal: 100 mil cidadãos, 1,43 milhão de linhas (~9 min)
docker compose run --rm api python manage.py semear_carga
docker compose exec postgres psql -U sgcas -d sgcas -c "VACUUM ANALYZE;"
```

Os dois são idempotentes e nunca apagam nada. Com `DEBUG=True` existe também
`GET /api/auth/dev-login` (`?papel=RECEPCIONISTA`, `TECNICO`, …), que abre sessão
local sem passar pelo Tefé Cidadão — a rota não é registrada fora de `DEBUG`.

## Testes

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py test testes --noinput
```

Check rápido:

```bash
set -a; . ./.env; set +a
.venv/bin/python manage.py check
```

## Observações

- Não commite `.env`.
- Use `.env.example` como base.
- Dados sensíveis de cidadão podem ser cifrados ativando `PII_ENCRYPTION_ENABLED` —
  numa base já povoada, rode `manage.py cifrar_dados_pessoais` logo em seguida.
- Antes de produção, revise migrations e variáveis do Keycloak.
