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

## Endpoints principais

```txt
GET  /api/auth/me
GET  /api/auth/keycloak/login
POST /api/auth/logout
POST /api/auth/access-request/resend

GET  /api/access-requests/
POST /api/access-requests/:id/aprovar

GET    /api/users/
PUT    /api/users/:id
PUT    /api/users/:id/perfil
DELETE /api/users/:id

GET  /api/citizens/
POST /api/citizens/novo
GET  /api/citizens/:id
GET  /api/citizens/:id/historico

GET  /api/reception/painel
GET  /api/reception/atendimentos
POST /api/reception/atendimento

GET  /api/queues/
GET  /api/queues/painel
POST /api/queues/chamar-proximo
POST /api/queues/:senha_id/nao-compareceu

GET  /api/cases/
POST /api/cases/:id/observacao
POST /api/cases/:id/encaminhar
POST /api/cases/:id/concluir

GET  /api/institutional/units
GET  /api/institutional/services
GET  /api/institutional/demands
GET  /api/institutional/coordinations
```

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
- Dados sensíveis de cidadão podem ser cifrados ativando `PII_ENCRYPTION_ENABLED`.
- Antes de produção, revise migrations e variáveis do Keycloak.
