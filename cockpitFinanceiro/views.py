"""
Cockpit Financeiro — página + API que substitui o runtime do Claude.

Acesso: usuário e senha individuais (UsuarioCockpit, desde 25/09/2026 — antes era senha única).
O usuário nasce com senha provisória e é obrigado a trocá-la no primeiro acesso. Perfil
"leitura" vê o painel e baixa anexos; "edição" também carrega planilha e envia/exclui anexos.
A sessão é um cookie assinado (HttpOnly, Secure, SameSite=Strict) com o id e a versão do
usuário — trocar/resetar a senha ou bloquear o usuário derruba as sessões dele.

Não usa DRF de propósito: o DEFAULT_PERMISSION_CLASSES do projeto está aberto (ver pendência
da API sem login) e aqui a checagem de acesso tem de ser explícita em toda view.
"""
import json
import mimetypes
import os
import re
import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.http import (FileResponse, HttpResponse, HttpResponseNotAllowed, JsonResponse)
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt

from .models import AnexoCockpit, DocumentoCockpit, UsuarioCockpit

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PAGINA = os.path.join(APP_DIR, 'pagina', 'cockpit.html')
SHIM = os.path.join(APP_DIR, 'static_src', 'claude-shim.js')

COOKIE = 'cockpit_fin'
SALT = 'cockpitFinanceiro.sessao'
DURACAO_SESSAO = 60 * 60 * 12          # 12 h
MAX_TENTATIVAS = 8                      # por IP, a cada 15 min
JANELA_TENTATIVAS = 60 * 15
SENHA_MIN = 8

NOME_VALIDO = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
TIPOS_ANEXO = {'application/pdf', 'image/png', 'image/jpeg'}
MAX_ANEXO = 25 * 1024 * 1024

# Versão sem as advisories do 0.18.5 (prototype pollution / ReDoS) — o painel abre
# planilhas enviadas por terceiros. A SheetJS só publica no CDN próprio desde o 0.19.3.
XLSX_ANTIGO = 'https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js'
XLSX_NOVO = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js'


# ─── sessão ──────────────────────────────────────────────────────────────────────────

def _usuario(request):
    """UsuarioCockpit logado (ativo e com a versão do cookie), ou None."""
    try:
        valor = request.get_signed_cookie(COOKIE, salt=SALT, max_age=DURACAO_SESSAO)
        dados = json.loads(valor)
    except (KeyError, signing.BadSignature, ValueError):
        return None
    u = UsuarioCockpit.objects.filter(id=dados.get('u'), ativo=True).first()
    if not u or dados.get('v') != u.versao:
        return None
    return u


def _ip(request):
    return (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
            or request.META.get('REMOTE_ADDR', ''))


def _local(request):
    return request.get_host().split(':')[0] in ('localhost', '127.0.0.1')


def _seguranca(resp):
    resp['Cache-Control'] = 'no-store'
    resp['X-Robots-Tag'] = 'noindex, nofollow'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Referrer-Policy'] = 'same-origin'
    resp['X-Frame-Options'] = 'DENY'
    return resp


def _grava_sessao(request, resp, u):
    resp.set_signed_cookie(
        COOKIE, json.dumps({'u': u.id, 'v': u.versao}), salt=SALT,
        max_age=DURACAO_SESSAO, httponly=True, samesite='Strict',
        # Pelo host, não pelo DEBUG: a produção roda com DEBUG=True (ver pendência), e o
        # cookie tem de ser "Secure" lá. Só o teste em http://localhost fica sem.
        secure=not _local(request),
    )
    return resp


def _api(view):
    """Exige login (com a senha já trocada) e, em escrita, perfil de edição e o cabeçalho
    X-Cockpit (força preflight de CORS, que só libera managerdb.com.br — junto com o
    SameSite=Strict, faz o papel do CSRF)."""
    @csrf_exempt
    def wrapper(request, *args, **kwargs):
        u = _usuario(request)
        if not u or u.trocar_senha:
            return _seguranca(JsonResponse({'erro': 'nao_autenticado'}, status=401))
        if request.method not in ('GET', 'HEAD'):
            if request.headers.get('X-Cockpit') != '1':
                return _seguranca(JsonResponse({'erro': 'cabecalho_ausente'}, status=403))
            if not u.pode_editar:
                return _seguranca(JsonResponse({'erro': 'somente_leitura'}, status=403))
        request.cockpit_user = u
        request.cockpit_usuario = u.nome
        return _seguranca(view(request, *args, **kwargs))
    return wrapper


# ─── páginas de acesso ───────────────────────────────────────────────────────────────

_ESTILO = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Cockpit Financeiro</title><style>
:root{--bg:#f4f5f7;--card:#fff;--tx:#1b1f24;--mut:#5b6573;--bd:#d8dce2;--pri:#1f5fbf;--err:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--card:#1a1f25;--tx:#e8ebef;--mut:#9aa4b1;--bd:#2c333c;--pri:#5b9bff;--err:#ff7a6b}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--tx);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
form{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:28px;width:100%;max-width:360px}
h1{font-size:20px;margin:0 0 4px}p{color:var(--mut);margin:0 0 20px}label{display:block;font-weight:600;margin:14px 0 6px}
input{width:100%;padding:10px 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--tx);font:inherit}
button{width:100%;margin-top:22px;padding:11px;border:0;border-radius:8px;background:var(--pri);color:#fff;font:inherit;font-weight:600;cursor:pointer}
.err{color:var(--err);margin-top:14px}a{color:var(--pri)}.mini{font-size:13px;margin-top:14px;text-align:center}</style></head><body>"""


def _login(erro='', login='', status=200):
    html = (_ESTILO +
            '<form method="post" action="entrar"><h1>Cockpit Financeiro</h1><p>Acesso restrito.</p>'
            f'<label for="u">Usuário</label><input id="u" name="login" maxlength="60" required autocomplete="username" autocapitalize="none" value="{escape(login)}">'
            '<label for="s">Senha</label><input id="s" name="senha" type="password" required autocomplete="current-password">'
            '<button type="submit">Entrar</button>'
            + (f'<div class="err">{escape(erro)}</div>' if erro else '') +
            '<div class="mini">Esqueceu a senha? Peça ao responsável para gerar uma nova.</div></form></body></html>')
    return _seguranca(HttpResponse(html, status=status))


def _tela_troca(u, erro='', obrigatoria=False, status=200):
    texto = ('Primeiro acesso: crie a sua senha para continuar.' if obrigatoria
             else 'Troque a sua senha.')
    html = (_ESTILO +
            f'<form method="post" action="trocar-senha"><h1>Olá, {escape(u.nome)}</h1><p>{texto}</p>'
            + ('' if obrigatoria else '<label for="a">Senha atual</label><input id="a" name="atual" type="password" required autocomplete="current-password">') +
            f'<label for="n">Nova senha</label><input id="n" name="nova" type="password" required minlength="{SENHA_MIN}" autocomplete="new-password">'
            '<label for="c">Repita a nova senha</label><input id="c" name="confirma" type="password" required autocomplete="new-password">'
            f'<p style="margin:10px 0 0;font-size:13px">Mínimo de {SENHA_MIN} caracteres.</p>'
            '<button type="submit">Salvar senha</button>'
            + (f'<div class="err">{escape(erro)}</div>' if erro else '') +
            ('' if obrigatoria else '<div class="mini"><a href="./">Voltar ao painel</a></div>') +
            '</form></body></html>')
    return _seguranca(HttpResponse(html, status=status))


def _html_do_painel():
    with open(PAGINA, encoding='utf-8') as f:
        html = f.read()
    with open(SHIM, encoding='utf-8') as f:
        shim = f.read()
    html = html.replace(XLSX_ANTIGO, XLSX_NOVO)
    # O shim tem de existir antes de qualquer script do painel rodar.
    injetar = f'<script>{shim}</script>'
    m = re.search(r'<head[^>]*>', html, re.I)
    return html[:m.end()] + injetar + html[m.end():] if m else injetar + html


def painel(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    u = _usuario(request)
    if not u:
        return _login()
    if u.trocar_senha:
        return redirect('./trocar-senha')
    return _seguranca(HttpResponse(_html_do_painel(), content_type='text/html; charset=utf-8'))


@csrf_exempt
def entrar(request):
    if request.method != 'POST':
        return redirect('./')
    chave = f'cockpitfin:tentativas:{_ip(request)}'
    tentativas = cache.get(chave, 0)
    login = (request.POST.get('login') or '').strip().lower()[:60]
    if tentativas >= MAX_TENTATIVAS:
        return _login('Muitas tentativas. Aguarde 15 minutos.', login, status=429)

    u = UsuarioCockpit.objects.filter(login=login, ativo=True).first()
    senha = request.POST.get('senha') or ''
    if not u or not check_password(senha, u.senha_hash):
        cache.set(chave, tentativas + 1, JANELA_TENTATIVAS)
        return _login('Usuário ou senha inválidos.', login, status=401)

    cache.delete(chave)
    u.ultimo_acesso = timezone.now()
    u.save(update_fields=['ultimo_acesso'])
    return _grava_sessao(request, redirect('./trocar-senha' if u.trocar_senha else './'), u)


@csrf_exempt
def trocar_senha(request):
    u = _usuario(request)
    if not u:
        return redirect('./')
    obrigatoria = u.trocar_senha
    if request.method != 'POST':
        return _tela_troca(u, obrigatoria=obrigatoria)
    # Mesmo cuidado do login: formulário só vale vindo daqui (SameSite=Strict já barra
    # POST de outro site com o cookie).
    atual = request.POST.get('atual') or ''
    nova = request.POST.get('nova') or ''
    confirma = request.POST.get('confirma') or ''
    if not obrigatoria and not check_password(atual, u.senha_hash):
        return _tela_troca(u, 'Senha atual incorreta.', obrigatoria, status=400)
    if len(nova) < SENHA_MIN:
        return _tela_troca(u, f'A nova senha precisa ter pelo menos {SENHA_MIN} caracteres.', obrigatoria, status=400)
    if nova != confirma:
        return _tela_troca(u, 'As duas senhas não conferem.', obrigatoria, status=400)
    if check_password(nova, u.senha_hash):
        return _tela_troca(u, 'A nova senha precisa ser diferente da atual.', obrigatoria, status=400)
    u.senha_hash = make_password(nova)
    u.trocar_senha = False
    u.versao += 1
    u.save(update_fields=['senha_hash', 'trocar_senha', 'versao'])
    return _grava_sessao(request, redirect('./'), u)


@csrf_exempt
def sair(request):
    resp = redirect('./')
    resp.delete_cookie(COOKIE, samesite='Strict')
    return resp


# ─── API: db ─────────────────────────────────────────────────────────────────────────

def _snap(doc):
    return {'id': doc.doc_id, 'exists': True, 'data': doc.dados}


def _nomes_validos(*nomes):
    return all(NOME_VALIDO.match(n or '') for n in nomes)


@_api
def api_eu(request):
    u = request.cockpit_user
    return JsonResponse({'id': u.nome, 'name': u.nome, 'login': u.login, 'pode_editar': u.pode_editar})


@_api
def api_doc(request, colecao, doc_id):
    if not _nomes_validos(colecao, doc_id):
        return JsonResponse({'erro': 'nome_invalido'}, status=400)
    if request.method == 'GET':
        doc = DocumentoCockpit.objects.filter(colecao=colecao, doc_id=doc_id).first()
        return JsonResponse(_snap(doc) if doc else {'id': doc_id, 'exists': False, 'data': None})
    if request.method == 'PUT':
        try:
            dados = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse({'erro': 'json_invalido'}, status=400)
        if not isinstance(dados, dict):
            return JsonResponse({'erro': 'json_invalido'}, status=400)
        DocumentoCockpit.objects.update_or_create(
            colecao=colecao, doc_id=doc_id,
            defaults={'dados': dados, 'atualizado_por': request.cockpit_usuario},
        )
        return JsonResponse({'ok': True})
    if request.method == 'DELETE':
        DocumentoCockpit.objects.filter(colecao=colecao, doc_id=doc_id).delete()
        return JsonResponse({'ok': True})
    return HttpResponseNotAllowed(['GET', 'PUT', 'DELETE'])


@_api
def api_colecao(request, colecao):
    if not _nomes_validos(colecao):
        return JsonResponse({'erro': 'nome_invalido'}, status=400)
    if request.method == 'GET':
        campo = request.GET.get('ordem') or ''
        desc = request.GET.get('dir') == 'desc'
        try:
            limite = max(1, min(int(request.GET.get('limite') or 200), 1000))
        except ValueError:
            limite = 200
        docs = list(DocumentoCockpit.objects.filter(colecao=colecao))
        if campo:
            docs.sort(key=lambda d: str((d.dados or {}).get(campo) or ''), reverse=desc)
        return JsonResponse({'docs': [_snap(d) for d in docs[:limite]]})
    if request.method == 'POST':
        try:
            dados = json.loads(request.body or b'{}')
        except ValueError:
            return JsonResponse({'erro': 'json_invalido'}, status=400)
        if not isinstance(dados, dict):
            return JsonResponse({'erro': 'json_invalido'}, status=400)
        doc = DocumentoCockpit.objects.create(
            colecao=colecao, doc_id=uuid.uuid4().hex, dados=dados,
            atualizado_por=request.cockpit_usuario,
        )
        return JsonResponse({'id': doc.doc_id})
    return HttpResponseNotAllowed(['GET', 'POST'])


# ─── API: anexos ─────────────────────────────────────────────────────────────────────

@_api
def api_anexos(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    arquivo = request.FILES.get('arquivo')
    if not arquivo:
        return JsonResponse({'erro': 'arquivo_ausente'}, status=400)
    tipo = (request.POST.get('tipo') or arquivo.content_type or '').lower()
    if tipo == 'image/jpg':
        tipo = 'image/jpeg'
    if tipo not in TIPOS_ANEXO:
        return JsonResponse({'erro': 'tipo_nao_permitido'}, status=400)
    if arquivo.size > MAX_ANEXO:
        return JsonResponse({'erro': 'arquivo_grande'}, status=400)
    # Confere a assinatura do arquivo — o tipo declarado vem do navegador.
    inicio = arquivo.read(8)
    arquivo.seek(0)
    assinaturas = {'application/pdf': b'%PDF', 'image/png': b'\x89PNG', 'image/jpeg': b'\xff\xd8\xff'}
    if not inicio.startswith(assinaturas[tipo]):
        return JsonResponse({'erro': 'conteudo_nao_confere'}, status=400)

    anexo = AnexoCockpit(
        nome=os.path.basename(arquivo.name)[:255], content_type=tipo,
        tamanho=arquivo.size, enviado_por=request.cockpit_usuario,
    )
    ext = mimetypes.guess_extension(tipo) or ''
    anexo.arquivo.save(f'{uuid.uuid4().hex}{ext}', arquivo, save=True)
    return JsonResponse({'id': str(anexo.id), 'url': f'api/anexos/{anexo.id}'})


@_api
def api_anexo(request, anexo_id):
    anexo = AnexoCockpit.objects.filter(id=anexo_id).first()
    if request.method == 'GET':
        if not anexo:
            return JsonResponse({'erro': 'nao_encontrado'}, status=404)
        resp = FileResponse(anexo.arquivo.open('rb'), content_type=anexo.content_type)
        resp['Content-Disposition'] = 'inline'
        return resp
    if request.method == 'DELETE':
        if anexo:
            anexo.arquivo.delete(save=False)
            anexo.delete()
        return JsonResponse({'ok': True})
    return HttpResponseNotAllowed(['GET', 'DELETE'])
