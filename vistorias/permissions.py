"""
Perfis (seção 2) = grupos do Django. Um usuário pode ter mais de um.
``DEFAULT_PERMISSION_CLASSES`` está vazio no projeto: toda view daqui declara a sua.

* VistoriaGestor — Gerente Executivo Operacional e Diretoria: cadastros, fichas, programa,
  validação, abono, dispensa, liberação, fechamento. NÃO executa vistorias.
* VistoriaAvaliador — executa vistorias (programadas e extraordinárias) e registra impedimentos.
* VistoriaGerente — consulta só os equipamentos sob sua responsabilidade.
* VistoriaPCM — consulta NCs, registra correções dos suspensos, marca "em manutenção".
* VistoriaSESMT — acompanha suspensos, valida correções e libera.
"""
from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission

GESTOR = 'VistoriaGestor'
AVALIADOR = 'VistoriaAvaliador'
GERENTE = 'VistoriaGerente'
PCM = 'VistoriaPCM'
SESMT = 'VistoriaSESMT'
PERFIS = [GESTOR, AVALIADOR, GERENTE, PCM, SESMT]

GRUPOS_GESTAO = ('Admin', 'Master', GESTOR)
GRUPOS_MODULO = GRUPOS_GESTAO + (AVALIADOR, GERENTE, PCM, SESMT)


def grupos(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if not hasattr(user, '_grupos_vistoria'):
        user._grupos_vistoria = set(user.groups.values_list('name', flat=True))
    return user._grupos_vistoria


def tem(user, *nomes) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(grupos(user) & set(nomes))


def eh_gestor(user) -> bool:
    return tem(user, *GRUPOS_GESTAO)


def eh_avaliador(user) -> bool:
    # o GEO não executa vistorias; Admin/superusuário passa para conseguir testar
    if user and user.is_authenticated and (user.is_superuser or 'Admin' in grupos(user)):
        return True
    return AVALIADOR in grupos(user)


def pode_corrigir(user) -> bool:
    return tem(user, *GRUPOS_GESTAO, PCM)


def pode_liberar(user) -> bool:
    return tem(user, *GRUPOS_GESTAO, SESMT)


def so_os_seus(user) -> bool:
    """Gerente de setor sem outro perfil amplo: vê só os equipamentos dele."""
    if not user or not user.is_authenticated or user.is_superuser:
        return False
    g = grupos(user)
    amplos = set(GRUPOS_GESTAO) | {AVALIADOR, PCM, SESMT}
    return GERENTE in g and not (g & amplos)


def unidades_de_atuacao(user) -> list[int]:
    """Unidades do perfil; vazio = todas. O GEO sempre vê tudo."""
    if not user or not user.is_authenticated or eh_gestor(user):
        return []
    perfil = getattr(user, 'perfil_vistoria', None)
    try:
        return list(perfil.unidades.values_list('id', flat=True)) if perfil else []
    except Exception:  # noqa: BLE001 — perfil ainda não criado
        return []


def filtro_equipamentos(user, prefixo: str = '') -> Q:
    """Q para limitar equipamentos (ou objetos com FK ``<prefixo>``) ao que o usuário pode ver."""
    q = Q()
    if so_os_seus(user):
        q &= Q(**{f'{prefixo}gerente': user})
    unidades = unidades_de_atuacao(user)
    if unidades:
        q &= Q(**{f'{prefixo}unidade__in': unidades})
    return q


class NoModulo(BasePermission):
    message = 'Acesso restrito ao módulo de vistorias.'

    def has_permission(self, request, view):
        return tem(request.user, *GRUPOS_MODULO)


class Gestao(BasePermission):
    message = 'Só o Gerente Executivo Operacional pode fazer isso.'

    def has_permission(self, request, view):
        return eh_gestor(request.user)


class LeituraOuGestao(BasePermission):
    message = 'Só o Gerente Executivo Operacional altera os cadastros.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return tem(request.user, *GRUPOS_MODULO)
        return eh_gestor(request.user)


class Avaliador(BasePermission):
    message = 'Só avaliadores executam vistorias.'

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return tem(request.user, *GRUPOS_MODULO)
        return eh_avaliador(request.user)
