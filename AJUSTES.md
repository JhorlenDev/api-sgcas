# Ajustes da branch `ajustes-marreira` — api-sgcas

Este arquivo existe para quem chega depois: **o que foi mexido, por quê, e como
conferir**. Serve tanto para pessoa quanto para agente de IA que abrir o
repositório sem ter acompanhado a conversa.

Base da branch: `main` (`baa5c26`).

> Nada aqui foi para a `main`. Tudo vive em `ajustes-marreira`, para revisão.

---

## Resumo

| # | O que | Tipo | Issue |
| --- | --- | --- | --- |
| 1 | Formato de `unidade` unificado entre `/users/` e `/auth/me` | correção (perda de dado) | [#6](https://github.com/JhorlenDev/api-sgcas/issues/6) |
| 2 | Paginação e filtros em todas as listagens | melhoria | — |
| 3 | `GET /api/cases/resumo` | melhoria | [front#2](https://github.com/JhorlenDev/front-sgcas/issues/2) |
| 4 | N+1 em `/api/cases/` | correção | [#7](https://github.com/JhorlenDev/api-sgcas/issues/7) |
| 5 | Busca de cidadão: 3 varreduras → 1 | correção | — |
| 6 | Índices de data e status + trigrama | desempenho | [#8](https://github.com/JhorlenDev/api-sgcas/issues/8) |
| 7 | `/api/queues/` ganhou teto | correção | [#9](https://github.com/JhorlenDev/api-sgcas/issues/9) |
| 8 | Entrada local sem SSO, atrás de `DEBUG` | ferramenta de dev | — |
| 9 | `semear_demo` e `semear_carga` | ferramenta de dev | — |
| 10 | 28 testes novos | teste | — |
| 11 | Merge da `atualização-jhorlen` + detalhe dos indicadores paginado | integração | — |

---

## 1. Formato de `unidade` unificado

**Era:** `/api/auth/me` devolvia `unidade` como objeto; `/api/users/` devolvia a
mesma chave como string com o id. Um nome, dois significados.

**Estragava:** quem lesse `unidade.id` na lista recebia `undefined` sem erro. Na
tela de usuários o select de lotação caía para vazio, o submit mandava
`unidade_id: ""` e `atualizar_operador` gravava `None` — **salvar um operador
apagava a unidade dele**. Como a unidade escopa fila, casos e painel
(`apps/contas/escopo.py`), a pessoa passava a ver lista vazia em tudo que é
operacional, sem mensagem nenhuma.

**Ficou:** `OperadorNaListaSerializer` usa o mesmo `UnidadeResumidaSerializer`.
`unidade_id` e `unidade_nome` continuam expostos.

- `apps/contas/serializers.py` · commit `b8c6d24`
- Confere: `testes/test_paginacao.py::ContratoDoOperador`

## 2. Paginação e filtros

**Era:** corte fixo no fim da consulta (`[:100]`, `[:200]`, `[:50]`). Evita a
resposta gigante, mas não é paginação: quem chama não sabe que há mais, não tem
como pedir o resto, e o total que a tela mostra vira o tamanho do corte.

**Ficou:** envelope em todas as listagens grandes.

```json
{ "itens": [...], "total": 220065, "pagina": 1, "por_pagina": 25, "paginas": 8803 }
```

`total` sai de um `count()` com os mesmos filtros. **Isto quebra quem consumia a
lista solta** — o front foi atualizado na branch irmã (`front-sgcas`,
`ajustes-marreira`).

Decisões que valem registro, todas em `apps/comum/consultas.py`:

- **Teto de 100 por página.** Paginação sem teto é o corte de antes com outro
  nome: `?limit=999999` traria a tabela inteira.
- **Parâmetro inválido devolve 400**, não cai para o padrão. Silenciar `?page=abc`
  faria a tela mostrar a página 1 achando que mostra outra.
- **Ordenação só pelo que a rota declara.** Repassar o parâmetro cru para o
  `order_by` deixaria qualquer autenticado ordenar por coluna interna e provocar
  500 com um nome inexistente.
- **Período comparado no fuso do projeto** (`__date`). Em UTC, tudo depois das
  20h locais cairia no dia seguinte e sumiria do recorte.

Filtros por rota estão no [README](README.md#listagens-paginação-e-filtros).

- `apps/comum/consultas.py` (novo), `apps/{atendimentos,cidadaos,contas,auditoria}/api.py`
- `apps/auditoria/serializers.py` (novo) · commit `0700306`

## 3. `GET /api/cases/resumo`

Contagem por situação no mesmo recorte da listagem. Existe porque contar no
cliente sobre a página recebida responde outra pergunta: quantos casos há
*naquela página*, e não na rede. Com 220 mil casos e página de 25, a diferença
é de três ordens de grandeza — e é o número em que alguém decide escala de
equipe.

## 4. N+1 em `/api/cases/`

O `select_related` não trazia `servico`, mas o `CasoSerializer` lê
`servico.nome`. Medido com `CaptureQueriesContext`: **101 consultas para 100
casos**; com `select_related('servico')`, **1**.

## 5. Busca de cidadão

Três avaliações da mesma consulta — `exists()`, o `count()` da paginação e a
fatia. Com a cifragem desligada a comparação cai nas colunas em texto, que não
têm índice, e cada avaliação custava uma varredura do cadastro. Agora resolve
uma vez em `id__in`.

Dois cuidados junto: termo sem dígito e sem arroba **não** tenta o ramo de
documento (buscar "maria" varria o cadastro comparando texto contra colunas de
CPF antes de desistir); e a listagem usa `only()` — mostra seis campos e
carregava sete colunas JSON com o prontuário inteiro.

## 6. Índices

Nenhuma coluna de data ou status tinha índice. Toda listagem ordenada por data
varria a tabela e ordenava.

| Migration | O que cria |
| --- | --- |
| `atendimentos/0007` | `caso_aberto_em_idx`, `caso_unidade_situacao_idx`, `caso_atualizado_em_idx`, `senha_unidade_situacao_idx`, `senha_criado_em_idx`, `beneficio_criado_em_idx` |
| `auditoria/0002` | `auditoria_criado_em_idx`, `auditoria_entidade_idx` |
| `cidadaos/0003` | `cidadao_atualizado_em_idx` |
| `cidadaos/0004` | `cidadao_nome_trgm_idx` (GIN, `pg_trgm`) |

> **Antes de aplicar em produção**
>
> - `pg_trgm` exige privilégio elevado. A migration cria a extensão, mas em
>   Postgres gerenciado pode ser preciso liberá-la no painel antes. Se falhar
>   por permissão, é isso — não erro de esquema.
> - A migration do trigrama usa `CONCURRENTLY` e não roda em transação. **As
>   demais não usam** e bloqueiam escrita enquanto constroem. Numa tabela já
>   grande: janela de manutenção, ou converta-as antes.

## 7. `/api/queues/` ganhou teto

Era a única listagem sem limite algum — para um ADMIN, devolvia toda senha
`AGUARDANDO` do sistema. Em dia comum é pequeno; o risco é a senha que fica
presa em `AGUARDANDO` por um atendimento interrompido e o acúmulo aparecer de
uma vez, na tela que a equipe mais usa.

## 8. Entrada local sem SSO (`apps/contas/dev_login.py`)

O SGCAS não tem senha própria: a sessão nasce no callback do Keycloak. Sem o
segredo do client `sgcas-web` e sem o redirect local registrado no realm, quem
clona o repositório **para na tela de login** e não alcança nenhuma tela.

`GET /api/auth/dev-login` cria ou reusa um operador local e abre a sessão dele.
Aceita `papel`, `unidade`, `email`, `destino`.

> **A rota só é registrada com `DEBUG=True`** (`apps/contas/urls.py`) e a view
> ainda devolve 404 por conta própria se for alcançada de outro jeito. Em
> produção ela não existe no roteador. Se esta branch for revisada para merge,
> **este é o ponto que merece o olhar mais atento** — é uma decisão de
> arquitetura sobre o repositório de vocês, não uma correção.

## 9. Seeds

| Comando | Para quê |
| --- | --- |
| `manage.py semear_demo` | Base legível: 45 pessoas, cenários montados à mão, todas as telas populadas. |
| `manage.py semear_carga` | Base pesada: 100 mil cidadãos, 1,43 milhão de linhas (~9 min). Para medir o sistema sob volume. |

Os dois são idempotentes (id determinístico por `uuid5`) e **nunca apagam nada**
— não há `delete()` neles, de propósito.

`semear_demo` também preenche o catálogo de demandas, que o repositório não traz
(ver [#5](https://github.com/JhorlenDev/api-sgcas/issues/5)) e sem o qual os 43
serviços ficam sem categoria municipal.

## 10. Testes

De 84 para **112**. Os 28 novos cobrem o que a suíte não tinha como pegar: ela
só conferia código de status, e numa base pequena o corte de 100 nunca era
alcançado.

`testes/test_paginacao.py` — envelope, páginas, teto, parâmetro inválido,
ordenação restrita, resumo (rede inteira, mesmos filtros, escopo por unidade) e
o contrato de `unidade`.

## 11. Merge da `atualização-jhorlen`

A branch do Jhorlen (commit `d7b10de`, 09/09) entrou por **merge real**, com a
autoria dele preservada. Ela partia da mesma base que esta (`baa5c26`) e junta
sem conflito.

O que ela trouxe:

| Rota | O que faz |
| --- | --- |
| `GET /api/queues/atendimento-atual` | devolve a senha que o operador deixou aberta, montada como o `chamar-proximo` |
| `GET /api/queues/em-atendimento` | senhas em atendimento na unidade, com quem atende e `pode_retomar` |
| `GET /api/queues/:senha_id/retomar` | reabre uma senha **do próprio operador**; de outro, 404 |
| `GET /api/queues/painel/:grupo` | registros por trás de cada número do painel do atendente |
| `POST /api/queues/chamar-proximo` | agora devolve a senha já aberta em vez de chamar outra pessoa |

O defeito que isso fecha: quem recarregava a página no meio de um atendimento
deixava a senha presa em `EM_ATENDIMENTO`, e o próximo "Chamar próximo" puxava
outra pessoa. O `select_for_update` no operador serializa chamadas do mesmo
operador em abas diferentes.

**Ajuste nosso por cima:** `/painel/:grupo` devolvia todos os registros de uma
vez. Medido na base de carga, "casos em acompanhamento" do CRAS Centro deu
**3.121 casos, 2,2 MB de JSON, 1,3 s** só para serializar. Passou a usar o mesmo
envelope das outras listagens — `{ tipo, itens, total, pagina, por_pagina,
paginas }` —, e os testes dele passaram a comparar o número do painel com
`total`, não com o tamanho da página. Um teste novo confere o corte
(`limit=1&page=2`).

`/em-atendimento` continua lista simples: são as senhas abertas de uma unidade,
um conjunto pequeno por natureza.

Testes: de 112 para **125** (12 do Jhorlen + 1 de paginação).

---

## Medições

Base de 100.046 cidadãos, 220.065 casos, 400 mil registros de auditoria
(1,43 milhão de linhas), após `VACUUM ANALYZE`. Mediana de 3 execuções.

| Endpoint | Antes | Depois |
| --- | --- | --- |
| `/api/cases/` | 377 ms | **82 ms** |
| `/api/auditoria/` | 198 ms | **51 ms** |
| `/api/citizens/` (recentes) | 264 ms | **114 ms** |
| `/api/queues/` | 104 ms | **49 ms** |
| busca por nome (contagem, no banco) | 147 ms | **8,9 ms** |
| `/api/cases/` (consultas ao banco) | 101 | **1** |

---

## Como revisar

```bash
git fetch origin && git checkout ajustes-marreira
docker compose up -d
docker compose run --rm api python manage.py migrate
docker compose run --rm api python manage.py test testes --noinput   # 125 OK
docker compose run --rm api python manage.py semear_demo             # base para clicar
```

Depois, `GET /api/auth/dev-login` abre a sessão e a interface do
`front-sgcas` (branch `ajustes-marreira`) consome esta API.

---

## O que **não** foi feito

Levantado e registrado como issue, mas sem código nesta branch:

| Issue | Por que não |
| --- | --- |
| [#1](https://github.com/JhorlenDev/api-sgcas/issues/1) `cadastrar_servicos` quebra na 2ª execução | Só contornado no seed (`semear_demo` só o chama com a base vazia). O comando em si segue com o defeito. |
| [#2](https://github.com/JhorlenDev/api-sgcas/issues/2) compose não publica a porta do Postgres | Resolvido só localmente, em `docker-compose.override.yml`. O `docker-compose.yml` do repositório não foi tocado. |
| [#3](https://github.com/JhorlenDev/api-sgcas/issues/3) healthcheck aponta para rota inexistente | Idem — corrigido apenas no override local. |
| [#4](https://github.com/JhorlenDev/api-sgcas/issues/4) não existe endpoint de health | Decisão de arquitetura de vocês; deixei a sugestão na issue. |
| [#5](https://github.com/JhorlenDev/api-sgcas/issues/5) catálogo de demandas vazio | O seed preenche, o comando oficial não. |

O `docker-compose.override.yml` **é arquivo de desenvolvimento local**: publica
a porta do Postgres, monta o fonte com `runserver` e corrige o healthcheck. Ele
não altera o compose de produção.
