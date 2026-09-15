"""
Entrada local sem Tefe Cidadao — SO para desenvolvimento.

O SGCAS nao tem senha propria: a sessao nasce no callback do Keycloak. Sem o
segredo do client `sgcas-web` (e sem o redirect local registrado no realm) nao
ha como entrar na maquina do desenvolvedor, e o sistema inteiro fica atras da
tela de login.

Esta rota cria — ou reusa — um operador local e abre a sessao dele, do mesmo
jeito que `views.callback` faz depois do SSO.

Tres travas, todas precisam passar (senao 404, como se a rota nao existisse):

1. `DEBUG` ligado e `DEV_LOGIN_ENABLED=true` — `apps/contas/urls.py` nem
   registra o caminho sem os dois, e a view confere de novo. DEBUG sozinho
   era trava fraca: um DEBUG=True esquecido abria sessao de ADMIN para
   qualquer um.
2. Pedido de localhost entra direto, como sempre foi no dia a dia.
3. Pedido de fora (tunel publico, outra maquina da rede) so entra com
   `?chave=` igual a `DEV_LOGIN_CHAVE`. Sem isso, quem achasse o link do tunel
   virava ADMIN — foi o que a revisao de seguranca de 15/09 reproduziu.

"De onde veio" sai do host que o navegador usou. Atras do proxy do Next ele
chega em `X-Forwarded-Host`, que o proprio Next preenche com o `Host` original
(`next/dist/server/lib/router-utils/proxy-request.js`) — quem chega pelo
tunel nao escolhe esse valor, porque a borda da Cloudflare so roteia pelo host
do tunel. O IP nao serve: com a API no Docker, local e tunel chegam do mesmo
gateway.

Limite conhecido: quem estiver na mesma rede e acessar a porta direto pode
forjar `Host: localhost`. Por isso a chave vale para o tunel, e a rede local
e tratada como a maquina do desenvolvedor.
"""
from __future__ import annotations

import hmac
import uuid

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.contas.autenticacao import CHAVE_OPERADOR
from apps.contas.models import Operador
from apps.contas.papeis import PRECEDENCIA, Papel
from apps.institucional.models import Unidade

EMAIL_PADRAO = 'contato@marreiradigital.com.br'
NOME_PADRAO = 'Paulo Marreira'
DESTINO_PADRAO = '/dashboard'
HOSTS_LOCAIS = {'localhost', '127.0.0.1', '[::1]', '::1'}


def _nome_do_host(valor: str) -> str:
    """`localhost:3001` → `localhost`; `[::1]:3001` → `[::1]`; lista → o primeiro."""
    host = valor.split(',')[0].strip().lower()
    if host.startswith('['):
        return host.split(']')[0] + ']'
    return host.split(':')[0]


def _pedido_local(request) -> bool:
    host = request.META.get('HTTP_X_FORWARDED_HOST') or request.META.get('HTTP_HOST') or ''
    return _nome_do_host(host) in HOSTS_LOCAIS


def _chave_confere(request) -> bool:
    esperada = settings.DEV_LOGIN_CHAVE
    recebida = request.GET.get('chave') or ''
    # Chave vazia no .env nunca libera: sem ela, só o localhost entra.
    return bool(esperada) and hmac.compare_digest(recebida.encode(), esperada.encode())


def _destino_seguro(destino: str | None) -> str:
    """
    Só caminho do próprio front.

    O destino é concatenado ao FRONTEND_URL. `@exemplo.com/x` virava
    `https://front@exemplo.com/x` — o navegador trata o front como usuário e
    vai para exemplo.com. `//host` e `/\\host` também saem do domínio.
    """
    if not destino or not destino.startswith('/') or destino.startswith(('//', '/\\')):
        return DESTINO_PADRAO
    return destino


@require_GET
def entrar_local(request):
    indisponivel = JsonResponse({'detalhe': 'Indisponível.'}, status=404)
    if not (settings.DEBUG and settings.DEV_LOGIN_ENABLED):
        return indisponivel
    # Mesma resposta da rota inexistente: quem sonda de fora não descobre que
    # ela existe e só falta a chave.
    if not _pedido_local(request) and not _chave_confere(request):
        return indisponivel

    papel = (request.GET.get('papel') or Papel.ADMIN).upper()
    if papel not in PRECEDENCIA:
        return JsonResponse(
            {
                'detalhe': f'Papel desconhecido: {papel}',
                'papeis': list(PRECEDENCIA),
            },
            status=400,
        )

    email = request.GET.get('email') or EMAIL_PADRAO
    agora = timezone.now()

    # Uma conta por papel: trocar de perfil no teste nao pode reescrever o
    # operador anterior, senao o historico de auditoria do papel antigo passa a
    # apontar para alguem que virou outra coisa.
    email_do_papel = email if papel == Papel.ADMIN else f'{papel.lower()}.{email}'

    # A unidade so e imposta quando vem no pedido. Sobrescrever sempre moveria
    # de lotacao o operador que o seed criou — e com ele o painel da unidade,
    # que conta pelo `unidade_id` de quem esta logado.
    unidade_id = request.GET.get('unidade')
    unidade = None
    if unidade_id:
        unidade = Unidade.objects.filter(id=unidade_id).first()
        if unidade is None:
            return JsonResponse({'detalhe': f'Unidade não encontrada: {unidade_id}'}, status=400)

    operador = Operador.objects.filter(email=email_do_papel).first()
    if operador is None:
        unidade = unidade or Unidade.objects.order_by('nome').first()
        operador = Operador.objects.create(
            id=str(uuid.uuid4()),
            email=email_do_papel,
            nome=NOME_PADRAO if papel == Papel.ADMIN else f'{NOME_PADRAO} ({papel})',
            papel=papel,
            ativo=True,
            unidade=unidade,
            keycloak_id=f'dev-{papel.lower()}',
            criado_em=agora,
            atualizado_em=agora,
        )
    else:
        operador.papel = papel
        operador.ativo = True
        operador.excluido_em = None
        if unidade is not None:
            operador.unidade = unidade
        operador.atualizado_em = agora
        operador.save()

    request.session.cycle_key()
    request.session[CHAVE_OPERADOR] = operador.id

    destino = _destino_seguro(request.GET.get('destino'))
    return HttpResponseRedirect(f'{settings.FRONTEND_URL.rstrip("/")}{destino}')
