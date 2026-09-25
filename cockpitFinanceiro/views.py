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

from .models import AnexoCockpit, DocumentoCockpit, UsuarioCockpit, VersaoPainel
import hashlib

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


def _html_original():
    with open(PAGINA, encoding='utf-8') as f:
        return f.read()


def _html_do_painel(versao=None, previa=False):
    """HTML servido: a versão pedida (prévia), senão a ativa, senão o arquivo do servidor."""
    if versao is None:
        versao = VersaoPainel.objects.filter(ativa=True).first()
    html = versao.html if versao else _html_original()
    with open(SHIM, encoding='utf-8') as f:
        shim = f.read()
    html = html.replace(XLSX_ANTIGO, XLSX_NOVO)
    # O shim tem de existir antes de qualquer script do painel rodar.
    injetar = f'<script>{shim}</script>'
    if previa:
        injetar += ('<div style="position:fixed;top:0;left:0;right:0;z-index:99999;padding:6px 12px;'
                    'background:#b45309;color:#fff;font:600 13px system-ui,sans-serif;text-align:center">'
                    'PRÉVIA — esta versão ainda não está publicada. '
                    '<a href="publicar" style="color:#fff;text-decoration:underline">Voltar para Publicar</a></div>')
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
    previa = request.GET.get('previa')
    if previa and u.pode_publicar:
        v = VersaoPainel.objects.filter(id=previa).first()
        if v:
            return _seguranca(HttpResponse(_html_do_painel(v, previa=True), content_type='text/html; charset=utf-8'))
    return _seguranca(HttpResponse(_html_do_painel(), content_type='text/html; charset=utf-8'))


# ─── publicar nova versão da página ──────────────────────────────────────────────────

MAX_HTML = 16 * 1024 * 1024


def _hora(dt):
    """dd/mm/aaaa hh:mm no horário de Brasília (o banco guarda em UTC)."""
    import zoneinfo
    return timezone.localtime(dt, zoneinfo.ZoneInfo('America/Sao_Paulo')).strftime('%d/%m/%Y %H:%M') if dt else ''


def _valida_html(bruto):
    """Devolve (html, erro). Confere que é o painel (usa o runtime do Claude ou traz os
    dados embutidos) — pega o caso de subir o arquivo errado."""
    if len(bruto) > MAX_HTML:
        return None, 'Arquivo grande demais (máximo 16 MB).'
    try:
        html = bruto.decode('utf-8-sig')
    except UnicodeDecodeError:
        return None, 'O arquivo não é um HTML em UTF-8.'
    baixo = html[:5000].lower()
    if '<html' not in baixo and '<!doctype html' not in baixo:
        return None, 'O arquivo não parece ser uma página HTML.'
    if 'claude.use' not in html and 'dashboard-data' not in html:
        return None, ('Não reconheci o painel neste arquivo (não achei o uso do runtime do Claude '
                      'nem os dados embutidos). Confira se é o HTML baixado do artifact.')
    return html, None


def _tela_publicar(u, msg='', erro='', status=200):
    versoes = list(VersaoPainel.objects.all()[:30])
    ativa = next((v for v in versoes if v.ativa), None)
    linhas = []
    for v in versoes:
        acoes = (f'<a href="./?previa={v.id}" target="_blank">Prévia</a>'
                 + ('' if v.ativa else
                    f' · <form method="post" style="display:inline"><input type="hidden" name="acao" value="ativar">'
                    f'<input type="hidden" name="id" value="{v.id}"><button class="lnk" type="submit">Publicar esta</button></form>'))
        linhas.append(
            f'<tr{" class=on" if v.ativa else ""}><td>{_hora(v.enviado_em)}</td><td>{escape(v.enviado_por)}</td>'
            f'<td>{escape(v.nome_arquivo)}<div class="mut">{escape(v.observacao)}</div></td>'
            f'<td>{v.tamanho // 1024} KB</td><td>{"<b>no ar</b>" if v.ativa else ""}{acoes}</td></tr>')
    tabela = ('<table><tr><th>Enviada em</th><th>Por</th><th>Arquivo</th><th>Tamanho</th><th></th></tr>'
              + ''.join(linhas) + '</table>') if linhas else '<p>Nenhuma versão enviada ainda — está no ar o arquivo original do servidor.</p>'
    original = ('' if not ativa else
                '<form method="post"><input type="hidden" name="acao" value="original">'
                '<button class="sec" type="submit">Voltar ao arquivo original do servidor</button></form>')
    html = (_ESTILO.replace('max-width:360px', 'max-width:860px') +
            '<style>table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}'
            'th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--bd);vertical-align:top}'
            'tr.on td{background:rgba(31,95,191,.08)}.mut{color:var(--mut);font-size:12px}'
            '.ok{color:#15803d;margin:10px 0}.lnk{all:unset;color:var(--pri);cursor:pointer;text-decoration:underline}'
            '.sec{background:transparent;color:var(--tx);border:1px solid var(--bd);width:auto;padding:8px 14px}'
            'input[type=file]{padding:8px}.box{width:100%;max-width:860px}.box>form{margin-top:14px}'
            'td form{all:unset;display:inline}td a{white-space:nowrap}</style>'
            '<div class="box"><form method="post" enctype="multipart/form-data">'
            '<h1>Publicar nova versão do painel</h1>'
            '<p>No Claude, abra o artifact do Cockpit, baixe o HTML e envie aqui. A versão entra como '
            '<b>prévia</b>: confira e depois clique em <b>Publicar esta</b>. Planilha e anexos não são afetados.</p>'
            + (f'<div class="ok">{escape(msg)}</div>' if msg else '')
            + (f'<div class="err">{escape(erro)}</div>' if erro else '') +
            '<input type="hidden" name="acao" value="enviar">'
            '<label for="f">Arquivo HTML</label><input id="f" name="arquivo" type="file" accept=".html,text/html" required>'
            '<label for="o">O que mudou (opcional)</label><input id="o" name="observacao" maxlength="250">'
            '<button type="submit">Enviar como prévia</button>'
            '<div class="mini"><a href="./">Voltar ao painel</a></div></form>'
            '<div style="margin-top:14px;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:20px 28px">'
            '<h1 style="font-size:17px">Versões</h1>' + tabela + '</div>'
            + original + '</div></body></html>')
    return _seguranca(HttpResponse(html, status=status))


@csrf_exempt
def publicar(request):
    u = _usuario(request)
    if not u:
        return redirect('./')
    if u.trocar_senha:
        return redirect('./trocar-senha')
    if not u.pode_publicar:
        return _seguranca(HttpResponse('Sem permissão para publicar.', status=403))
    if request.method != 'POST':
        return _tela_publicar(u)

    acao = request.POST.get('acao')
    if acao == 'enviar':
        arquivo = request.FILES.get('arquivo')
        if not arquivo:
            return _tela_publicar(u, erro='Escolha o arquivo HTML.', status=400)
        html, erro = _valida_html(arquivo.read())
        if erro:
            return _tela_publicar(u, erro=erro, status=400)
        sha = hashlib.sha256(html.encode('utf-8')).hexdigest()
        existente = VersaoPainel.objects.filter(sha256=sha).first()
        if existente:
            return _tela_publicar(u, msg=f'Esse arquivo já foi enviado em {_hora(existente.enviado_em)}.')
        # Primeira versão enviada: guarda antes o arquivo que está no ar, para poder voltar.
        if not VersaoPainel.objects.exists():
            orig = _html_original()
            VersaoPainel.objects.create(
                html=orig, nome_arquivo='cockpit.html (original do servidor)', tamanho=len(orig.encode('utf-8')),
                sha256=hashlib.sha256(orig.encode('utf-8')).hexdigest(), enviado_por='(servidor)',
                observacao='Versão que estava no ar antes da primeira publicação pela tela.')
        v = VersaoPainel.objects.create(
            html=html, nome_arquivo=os.path.basename(arquivo.name)[:255], tamanho=len(html.encode('utf-8')),
            sha256=sha, enviado_por=u.nome, observacao=(request.POST.get('observacao') or '').strip()[:250])
        return _tela_publicar(u, msg=f'Versão enviada como prévia. Abra a prévia e, se estiver certa, clique em "Publicar esta".')

    if acao == 'ativar':
        v = VersaoPainel.objects.filter(id=request.POST.get('id')).first()
        if not v:
            return _tela_publicar(u, erro='Versão não encontrada.', status=404)
        VersaoPainel.objects.filter(ativa=True).update(ativa=False)
        v.ativa = True
        v.ativada_em = timezone.now()
        v.ativada_por = u.nome
        v.save(update_fields=['ativa', 'ativada_em', 'ativada_por'])
        return _tela_publicar(u, msg=f'Publicada a versão de {_hora(v.enviado_em)}. Quem estiver com o painel aberto vê ao recarregar.')

    if acao == 'original':
        VersaoPainel.objects.filter(ativa=True).update(ativa=False)
        return _tela_publicar(u, msg='No ar: arquivo original do servidor.')

    return _tela_publicar(u, erro='Ação inválida.', status=400)


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
    return JsonResponse({'id': u.nome, 'name': u.nome, 'login': u.login,
                         'pode_editar': u.pode_editar, 'pode_publicar': u.pode_publicar})


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
