# API do SGCAS — guia para o front

O que você precisa saber para consumir o backend em Django: como a sessão é
criada pelo Tefé Cidadão, quais rotas existem, quem pode chamar cada uma, e as
regras de negócio que devolvem `400` — que costumam ser a maior parte do
trabalho de integração.

Tudo abaixo é verificado pelo suite de testes (`manage.py test testes`).

---

## Antes de tudo: a sessão mudou

O backend anterior emitia JWT próprio nos cookies `sgcas_access_token` e
`sgcas_refresh_token`, com rotação de refresh. **Isso deixou de existir.**

Agora é **sessão do Django**, no cookie `sessionid`. O front não gerencia token
nenhum — só precisa enviar os cookies (`credentials: 'include'`).

> Se o front verifica cookie para decidir rota pública ou protegida, é
> `sessionid` que ele deve procurar.

### O fluxo de entrada

1. **Botão "Entrar com Tefé Cidadão"** → navega o browser para
   `/api/auth/keycloak/login`. Não é `fetch` — é navegação, porque o destino é
   a tela do Keycloak.

2. **A pessoa se autentica.** O backend valida a assinatura do token e lê o
   papel dela.

3. **Um de três destinos:**
   - **Tem papel** → sessão criada, redireciona para `/dashboard`
   - **Não tem papel** → abre um pedido de acesso e vai para `/waiting-approval`
   - **Erro** → volta para `/login?erro=…`
     (`sem-acesso`, `estado-invalido`, `sem-codigo`)

4. **Sair** → `POST /api/auth/logout` devolve `{ "urlDeLogout": "…" }`. O front
   precisa **navegar para essa URL**, não apenas limpar a tela: ela encerra a
   sessão no próprio Tefé Cidadão.

   Parar antes disso faz a próxima entrada reabrir a conta anterior sem pedir
   credencial. Num CRAS, onde vários servidores usam o mesmo computador, isso é
   entrar na conta do colega.

### Quem está logado

```
GET /api/auth/me

{ "id": "…", "nome": "José Técnico", "email": "…",
  "papel": "TECNICO", "ativo": true,
  "unidade": { "id": "…", "nome": "CRAS Centro" } }
```

`unidade` **pode vir nula**: quem entra pelo SSO é criado sem lotação, definida
depois. Várias telas dependem dela — trate o caso.

---

## Rotas

Todas sob `/api`. Sem sessão, tudo responde `403`.

| Rota | Quem pode | O que faz |
|---|---|---|
| `GET /auth/me` | autenticado | Operador da sessão |
| `POST /auth/logout` | público | Encerra sessão, devolve `urlDeLogout` |
| `GET /citizens/?busca=` | consulta | Busca por CPF, NIS, e-mail ou nome |
| `POST /citizens/novo` | recepção | Cadastro completo |
| `GET /citizens/{id}` | atendimento | Prontuário completo |
| `GET /citizens/{id}/historico` | consulta | Linha do tempo municipal |
| `GET POST /citizens/{id}/anexos` | atendimento | Lista e envia documentos |
| `GET /citizens/{id}/anexos/{anexo}` | atendimento | Baixa o arquivo · `?miniatura=true` |
| `DELETE /citizens/{id}/anexos/{anexo}/remover` | supervisão | Remove do prontuário |
| `POST /reception/atendimento` | recepção | Finaliza no balcão ou encaminha |
| `GET /queues/` | atendimento | Fila da unidade |
| `POST /queues/chamar-proximo` | atendimento | Chama e monta o atendimento |
| `GET /cases/` | consulta | Casos da unidade |
| `POST /cases/{id}/encaminhar` | atendimento | Encaminha a outra unidade ou serviço |
| `POST /cases/{id}/concluir` | atendimento | Encerra e libera a senha |
| `GET /institutional/units` | consulta | Unidades da rede |
| `GET /institutional/coordinations` | consulta | Coordenações |
| `GET /institutional/demands` | consulta | Categorias municipais |
| `GET /institutional/services` | consulta | **Serviços da unidade** — o que a recepção seleciona |
| `GET /reports/dashboard` | consulta | Números do painel |
| `GET /reports/acoes-itinerantes` | supervisão | Balanço das ações em campo |
| `GET POST /itinerant-actions/` | atendimento | Listar e criar ações |
| `GET /users/` | supervisão | Operadores, inclusive os sem lotação |
| `GET /users/{id}` | próprio ou supervisão | Um operador |
| `PUT /users/{id}/atualizar` | admin | Define lotação e estado |
| `DELETE /users/{id}/desligar` | admin | Desliga e retira o papel no realm |
| `GET /access-requests/` | admin | Fila de pedidos pendentes |
| `GET /access-requests/historico` | admin | Inclui os recusados |
| `POST /access-requests/{id}/aprovar` | admin | Concede o papel no Tefé Cidadão |
| `POST /access-requests/{id}/recusar` | admin | Recusa, mantendo no histórico |
| `GET /auditoria/` | admin | Trilha de auditoria |

---

## Quem enxerga o quê

| Papel | Buscar cidadão | Prontuário | Atender | Fila de acesso | Auditoria |
|---|:---:|:---:|:---:|:---:|:---:|
| ADMIN | ✓ | ✓ | ✓ | ✓ | ✓ |
| COORDENADOR | ✓ | ✓ | ✓ | — | — |
| ASSISTENTE_SOCIAL | ✓ | ✓ | ✓ | — | — |
| TECNICO | ✓ | ✓ | ✓ | — | — |
| RECEPCIONISTA | ✓ | — | — | — | — |
| VISUALIZADOR | ✓ | — | — | — | — |
| GESTOR_ACOES_ITINERANTES | ✓ | — | — | — | — |

### Duas regras que atravessam tudo

**O cidadão é municipal; o atendimento é da unidade.** Cadastro, prontuário e
histórico não são filtrados por unidade — a pessoa circula entre os CRAS. Fila,
casos em andamento e indicadores são restritos à unidade de quem consulta. Só o
ADMIN vê todas.

**Operador desativado é recusado na hora**, inclusive em `/auth/me`, sem
esperar a sessão expirar. Trate um `403` repentino como fim de sessão.

---

## O fluxo da recepção

É onde estão as regras que mais devolvem `400`.

```
POST /api/reception/atendimento

{ "cidadao_id": "…",
  "servico_id": "…",              // de /institutional/services
  "unidade_destino_id": "…",      // opcional — só ao encaminhar de imediato
  "desfecho": "FINALIZADO",       // ou "ENCAMINHADO"
  "motivo": "Já retirou no CRAS Centro em 12/08",
  "observacao": "…"               // opcional
}
```

### Três recusas para tratar

**`motivo` é obrigatório quando o desfecho é `FINALIZADO`.** É o que a próxima
unidade lê quando a pessoa aparecer lá. Sem ele, o mesmo pedido volta na semana
seguinte sem rastro.

**A prioridade não é aceita da recepção.** Mandar `"prioridade": "URGENTE"` não
dá erro — o campo é ignorado e tudo entra como `NORMAL`. Dizer que um caso é
urgente é avaliação técnica; quem atende reprioriza ao ver a situação.
**Não coloque esse seletor na tela da recepção.**

**O serviço tem de pertencer à unidade de destino.** A recepção *vê* os
serviços de outras unidades — é assim que descobre para onde encaminhar — mas
não pode marcá-los como atendimento da própria. Sem `unidade_destino_id`, o
destino é a unidade de quem registra.

### Negar não abre caso

Com `desfecho: FINALIZADO`, **nenhum caso é criado e ninguém entra na fila** — a
resposta traz `caso: null` e `senha: null`. Fica apenas o registro do
atendimento, que aparece no histórico municipal da pessoa.

Com `ENCAMINHADO`, vêm os dois preenchidos.

### Chamar o próximo devolve tudo montado

```
POST /api/queues/chamar-proximo

{ "senha":     { "senha": "001", "situacao": "EM_ATENDIMENTO", … },
  "cidadao":   { … prontuário completo … },
  "caso":      { "protocolo": "20260824-52DF73", … },
  "historico": [ … linha do tempo municipal … ] }
```

É a mudança central do fluxo novo: **não faça uma segunda busca** depois de
chamar. Antes, a fila só mudava o estado da senha e o atendente procurava a
pessoa de novo em outra tela — isso se repetia a cada atendimento.

Fila vazia responde `404`, não lista vazia.

---

## Serviços: o que a recepção seleciona

```
GET /api/institutional/services            → os da minha unidade
GET /api/institutional/services?unidade=X  → os de outra unidade
GET /api/institutional/services?unidade=todas
```

Cada unidade oferta seus serviços. Cesta básica, na Residência Inclusiva, é
*Alimentação e nutrição*; no CRAS é *Benefício Eventual*. A recepcionista
escolhe entre o que a unidade dela faz, em vez de encaixar tudo em categorias
amplas.

A **categoria municipal é deduzida do serviço** e gravada por baixo — uma
escolha na tela, duas informações no banco. É o que mantém o relatório da rede
somando, mesmo com serviços diferentes em cada unidade.

### Encaminhar já no balcão

Se a pessoa está no CRAS mas precisa de um serviço da ILPI, a recepção envia
`servico_id` da ILPI **com** `unidade_destino_id` da ILPI: ela é cadastrada
aqui e entra na fila de lá, com os dados prontos, em vez de fazer a viagem e
recomeçar do zero.

Mandar o serviço sem o destino correspondente devolve `400` com a mensagem
dizendo qual unidade oferta aquele serviço — dá para mostrar direto ao
atendente.

---

## O histórico municipal

```
GET /api/citizens/{id}/historico

{ "cidadao": { … },
  "entradas": [
    { "quando": "2026-08-24T…",
      "unidade": "CRAS Centro",
      "o_que": "Benefício concedido: Vulnerabilidade temporária",
      "detalhe": "Cesta básica",
      "quem_atendeu": null,
      "no_mes_corrente": true,
      "e_de_outra_unidade": true }
  ] }
```

Existe para resolver um problema concreto: a pessoa retira cesta básica no CRAS
Centro e pede a mesma coisa no CRAS Sul. Sem uma visão que atravesse as
unidades, o segundo atendimento não sabe do primeiro.

- **Janela de 12 meses**, com `no_mes_corrente` para destacar — é no mês que a
  duplicidade acontece.
- **`quem_atendeu` vem `null`** para quem não é ADMIN ou COORDENADOR. O nome é
  sempre gravado; o que se restringe é a exposição rotineira entre unidades.
  Trate o nulo, não é erro.
- **O sistema avisa, não bloqueia.** Quem decide é quem está no balcão — a
  pessoa pode ter voltado por outra demanda.

---

## Cadastro do cidadão

### E-mail é obrigatório, e o termo também

**`email` não pode faltar nem vir vazio.** É o login da pessoa no Tefé Cidadão —
sem ele não há conta. Se a pessoa não tiver, o atendente ajuda a criar.

**`consentimento: true` é exigido** quando `criar_acesso_tefe_cidadao` está
ligado (o padrão). Criar conta de identidade para alguém sem que a pessoa saiba
não é aceitável — a data do consentimento é gravada porque o Art. 8, §6 da LGPD
exige poder demonstrar que ele era válido.

### A resposta traz o resultado do Tefé Cidadão

```
{ …cidadão…,
  "tefeCidadao": { "situacao": "criado",   // ou ja_existe · incompleto · falhou · desligado
                   "mensagem": null,
                   "faltando": [] } }
```

Mostre isso ao atendente. A conta **nasce sem senha**: quem define é o próprio
cidadão, no primeiro acesso ao portal, com um código enviado por WhatsApp.

**Nada é enviado no momento do cadastro.** A orientação correta no balcão é
*"entre no portal com seu CPF que o código chega na hora"*, e não *"vai chegar
um WhatsApp"*.

Se o SSO estiver fora do ar, `situacao` vem `falhou` e **o cadastro do cidadão
foi salvo assim mesmo** — atendimento presencial não depende do SSO estar de pé.

---

## Anexos do prontuário

```
POST /api/citizens/{id}/anexos          multipart/form-data
     file=<arquivo>  tipo_documento=rg_frente

GET  /api/citizens/{id}/anexos/{anexo}                → o arquivo
GET  /api/citizens/{id}/anexos/{anexo}?miniatura=true → versão reduzida
```

- Aceita **JPG, PNG, WEBP e PDF**, até 25 MB. Outro formato devolve `400`.
- Imagem é **recomprimida e ganha miniatura** — use a miniatura em listagens.
- A listagem **não devolve o caminho no disco**; use o `id` do anexo para baixar.
- **Remover é ato de supervisão** — técnico e assistente social recebem `403`.

O download passa pela API em vez de servir a pasta: assim respeita permissão e
entra na trilha de auditoria.

---

## Lotação dos operadores

**A tela mais esquecida, e a que trava tudo.**

Quem entra pelo Tefé Cidadão **nasce sem unidade**, e sem lotação não enxerga
dado operacional nenhum — a fila vem vazia, o painel zerado. Não é falha: o
escopo falha fechado de propósito, porque filtro vazio daria acesso a todas as
unidades justamente a quem não tem nenhuma.

`GET /api/users/?sem_unidade=true` lista exatamente quem está nessa situação —
vale um aviso na tela do admin. A lotação é definida em
`PUT /api/users/{id}/atualizar`.

**Papel não é alterável por aqui**: quem concede é o Tefé Cidadão. Mandar
`papel` não dá erro, é ignorado — do contrário a alteração seria sobrescrita no
próximo acesso da pessoa, parecendo ter funcionado.

---

## Rodar localmente

```bash
cd apps/api-django
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage.py migrate --fake-initial
./.venv/bin/python manage.py runserver 0.0.0.0:8000
```

- **Node 20** para o front (o 18 não carrega o `sharp`).
- O `.env` fica na **raiz do repositório**, compartilhado. Precisa de
  `DEBUG=True` para desenvolvimento — sem isso o backend se recusa a iniciar
  sem `DJANGO_SECRET_KEY`.
- Keycloak em `localhost:8090`, realm `prefeitura`. Postgres em `5435`.
- Testes: `./.venv/bin/python manage.py test testes --noinput`
- Catálogo de serviços: `./.venv/bin/python manage.py cadastrar_servicos`
  (idempotente)

### Apontar o front para o Django

O front resolve o backend por `INTERNAL_API_URL`. Para falar com o Django,
aponte para `http://localhost:8000`.

---

## O que ainda não existe

Responderá `404`. Listado aqui para ninguém descobrir por tentativa:

- Edição do prontuário (`PUT /citizens/{id}`)
- Sub-registros do cidadão: atendimentos, benefícios, encaminhamentos
- Fluxos de LGPD: exportação ao titular, eliminação, revogação do consentimento
  de imagem
- Módulo de famílias
- Relatórios por período e por demanda, e as exportações CSV e PDF
- Detalhe do caso (`GET /cases/{id}`) e histórico de evolução
- Modo offline: chave de sessão e idempotência

**`/triage` e `/history` não voltarão.** A triagem virou parte da recepção, e o
encaminhamento passou para o atendimento — foi decisão de projeto, não lacuna.
