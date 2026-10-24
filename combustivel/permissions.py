"""
Quem pode o quê no combustível. ``DEFAULT_PERMISSION_CLASSES`` está vazio no projeto: toda
view daqui declara a sua, senão ficaria aberta.

* Gestão (Admin, Master, CombustivelGestor): tudo — tanques, conferência, cancelamento,
  arquivos e chaves de integração.
* Operador (CombustivelOperador): SÓ faz as baixas — registra abastecimento, transferência e
  lubrificação (cadastros do formulário e os próprios registros). Painéis, tanques, estoque e
  preventivas ficam de fora (23/10).
* Leitura (CombustivelLeitura): painel e listas, sem alterar nada.

A integração com o SGA não usa usuário: usa ``ChaveIntegracao`` (ver ``AutenticacaoChave``).
"""
import hmac
import ipaddress

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.throttling import SimpleRateThrottle

from .models import ChaveIntegracao

GRUPOS_GESTAO = ('Admin', 'Master', 'CombustivelGestor')
GRUPOS_OPERADOR = GRUPOS_GESTAO + ('CombustivelOperador',)
# Painéis e listas: gestão e leitura, não o operador (ele só faz as baixas).
GRUPOS_LEITURA = GRUPOS_GESTAO + ('CombustivelLeitura',)
# Qualquer papel do módulo: o que o formulário de baixa precisa (cadastros, última leitura, fotos).
GRUPOS_MODULO = GRUPOS_OPERADOR + ('CombustivelLeitura',)


def _no_grupo(user, grupos) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=grupos).exists()


def eh_gestor(user) -> bool:
    return _no_grupo(user, GRUPOS_GESTAO)


class PodeVer(BasePermission):
    message = 'Acesso restrito ao controle de combustível.'

    def has_permission(self, request, view):
        return _no_grupo(request.user, GRUPOS_LEITURA)


class PodeUsarFormulario(BasePermission):
    """Leitura do que o formulário de baixa usa: qualquer papel do módulo, inclusive o operador."""
    message = 'Acesso restrito ao controle de combustível.'

    def has_permission(self, request, view):
        return _no_grupo(request.user, GRUPOS_MODULO)


class PodeGerir(BasePermission):
    message = 'Só a gestão do combustível pode fazer isso.'

    def has_permission(self, request, view):
        return _no_grupo(request.user, GRUPOS_GESTAO)


class LeituraOuGestao(BasePermission):
    """GET para quem vê o painel; o resto só para a gestão."""
    message = 'Só a gestão do combustível pode alterar isso.'

    def has_permission(self, request, view):
        grupos = GRUPOS_LEITURA if request.method in SAFE_METHODS else GRUPOS_GESTAO
        return _no_grupo(request.user, grupos)


class PodeRegistrar(BasePermission):
    """
    Ler: qualquer papel (o operador só os seus, ver get_queryset). Criar: operador.
    Alterar/cancelar: gestão (o operador não mexe depois).
    """
    message = 'Sem permissão para registrar abastecimentos.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return _no_grupo(request.user, GRUPOS_MODULO)
        if request.method == 'POST' and getattr(view, 'action', None) == 'create':
            return _no_grupo(request.user, GRUPOS_OPERADOR)
        return _no_grupo(request.user, GRUPOS_GESTAO)


# ── Integração por chave ────────────────────────────────────────────────────────
def ip_do_pedido(request) -> str | None:
    """
    IP de quem chamou, como o nginx viu. ``X-Real-IP`` é escrito pelo nginx; no
    ``X-Forwarded-For`` só vale o ÚLTIMO item (o que o nginx acrescentou) — os primeiros
    vêm do próprio cliente e podem ser inventados para passar pela lista de IPs.
    """
    real = request.META.get('HTTP_X_REAL_IP', '').strip()
    if real:
        return real
    encaminhado = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if encaminhado:
        return encaminhado.split(',')[-1].strip() or None
    return request.META.get('REMOTE_ADDR')


def ip_permitido(chave: ChaveIntegracao, ip: str | None) -> bool:
    redes = [linha.strip() for linha in (chave.ips_permitidos or '').splitlines() if linha.strip()]
    if not redes:
        return True
    try:
        endereco = ipaddress.ip_address(ip or '')
    except ValueError:
        return False
    for rede in redes:
        try:
            if endereco in ipaddress.ip_network(rede, strict=False):
                return True
        except ValueError:
            continue
    return False


class UsuarioDaChave:
    """Identidade de quem chega com chave: não é um User, não tem grupo nem sessão."""
    is_authenticated = True
    is_superuser = False
    is_staff = False
    pk = id = None

    def __init__(self, chave):
        self.chave = chave
        self.username = f'chave:{chave.prefixo}'

    def __str__(self):
        return self.username


class AutenticacaoChave(BaseAuthentication):
    """``Authorization: Chave <prefixo>.<segredo>``. Compara o hash, nunca o texto."""
    palavra = b'chave'

    def authenticate(self, request):
        partes = get_authorization_header(request).split()
        if not partes or partes[0].lower() != self.palavra:
            return None
        if len(partes) != 2:
            raise AuthenticationFailed('Cabeçalho de chave inválido.')
        try:
            prefixo, segredo = partes[1].decode().split('.', 1)
        except (UnicodeDecodeError, ValueError):
            raise AuthenticationFailed('Chave inválida.')

        chave = ChaveIntegracao.objects.filter(prefixo=prefixo).first()
        # Mesma mensagem para chave inexistente, errada, revogada ou vencida: não ajuda quem tenta adivinhar.
        if not chave or not hmac.compare_digest(chave.hash_segredo, ChaveIntegracao.hash(segredo)) or not chave.valida:
            raise AuthenticationFailed('Chave inválida.')
        ip = ip_do_pedido(request)
        if not ip_permitido(chave, ip):
            raise AuthenticationFailed('Origem não autorizada para esta chave.')

        ChaveIntegracao.objects.filter(pk=chave.pk).update(
            ultimo_uso_em=timezone.now(), ultimo_ip=ip, usos=chave.usos + 1)
        return UsuarioDaChave(chave), chave

    def authenticate_header(self, request):
        return 'Chave'


class TemChave(BasePermission):
    message = 'Use a chave de integração.'

    def has_permission(self, request, view):
        return isinstance(request.auth, ChaveIntegracao)


class TemChaveQueConfirma(TemChave):
    message = 'Esta chave não pode confirmar baixas.'

    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.auth.pode_confirmar


class LimiteIntegracao(SimpleRateThrottle):
    """Por chave: o SGA consulta a cada ~5 min, 30/min sobra e corta força bruta."""
    scope = 'combustivel_integracao'
    rate = '30/min'

    def get_cache_key(self, request, view):
        ident = request.auth.prefixo if isinstance(request.auth, ChaveIntegracao) else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class LimiteRegistro(SimpleRateThrottle):
    """Por usuário: nenhum frentista registra 60 abastecimentos por minuto."""
    scope = 'combustivel_registro'
    rate = '60/min'

    def get_cache_key(self, request, view):
        if request.method != 'POST':
            return None
        ident = request.user.pk if request.user and request.user.is_authenticated else self.get_ident(request)
        return self.cache_format % {'scope': self.scope, 'ident': ident}
