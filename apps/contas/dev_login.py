"""
Entrada local sem Tefe Cidadao — SO para desenvolvimento.

O SGCAS nao tem senha propria: a sessao nasce no callback do Keycloak. Sem o
segredo do client `sgcas-web` (e sem o redirect local registrado no realm) nao
ha como entrar na maquina do desenvolvedor, e o sistema inteiro fica atras da
tela de login.

Esta rota cria — ou reusa — um operador local e abre a sessao dele, do mesmo
jeito que `views.callback` faz depois do SSO.

So existe com DEBUG ligado: `apps/contas/urls.py` nem registra o caminho
quando DEBUG e falso, entao em producao a URL responde 404 pelo roteador.
"""
from __future__ import annotations

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


@require_GET
def entrar_local(request):
    if not settings.DEBUG:
        return JsonResponse({'detalhe': 'Indisponível.'}, status=404)

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

    destino = request.GET.get('destino') or '/dashboard'
    return HttpResponseRedirect(f'{settings.FRONTEND_URL.rstrip("/")}{destino}')
