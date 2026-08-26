# api-sgcas

Backend Django/DRF do SGCAS, separado do monorepo original.

## Stack

- Python 3.12
- Django 5.1
- Django REST Framework
- PostgreSQL
- Keycloak/Tefe Cidadao para login

## Rodar Local

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edite `.env` e coloque o `KEYCLOAK_CLIENT_SECRET` real do client `sgcas-web`.

Suba a API:

```bash
DEBUG=True ./.venv/bin/python manage.py runserver 0.0.0.0:8000
```

URL local:

```text
http://localhost:8000
```

## Rodar Com Docker

```bash
cp .env.example .env
docker compose up -d --build
```

## Login

O login nao usa usuario/senha local. Ele comeca no endpoint:

```text
GET /api/auth/keycloak/login
```

O Keycloak deve ter um client `sgcas-web` com:

```text
Valid redirect URI: http://localhost:3000/api/auth/keycloak/callback
Web origin: http://localhost:3000
```

Client roles esperadas:

```text
ADMIN
COORDENADOR
ASSISTENTE_SOCIAL
TECNICO
RECEPCIONISTA
GESTOR_ACOES_ITINERANTES
VISUALIZADOR
```

## Rotas

Todas as rotas da API ficam em `/api`.

Veja o guia do front em:

```text
docs/api.md
```

## Testes

```bash
DEBUG=True ./.venv/bin/python manage.py test testes --noinput
```

## Observacao Sobre Migrations

Esta API nasceu sobre o banco existente do SGCAS. Alguns modelos apontam para
tabelas ja criadas pelo backend anterior. Antes de usar em producao, revise as
migrations e escolha uma fonte unica de verdade para o schema.
