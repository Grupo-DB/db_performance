from rest_framework.permissions import BasePermission

# O projeto está com DEFAULT_PERMISSION_CLASSES vazio: cada view declara a sua.
GRUPOS_GESTOR = ('Admin', 'Master', 'despesasGestor')
GRUPOS_MODULO = GRUPOS_GESTOR + ('lancadorDespesas',)


def _grupos(user):
    if not hasattr(user, '_grupos_despesas'):
        user._grupos_despesas = set(user.groups.values_list('name', flat=True))
    return user._grupos_despesas


def eh_gestor(user):
    """Aprova, recusa, lança e reembolsa; vê as despesas de todos."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or bool(_grupos(user) & set(GRUPOS_GESTOR))


class AcessoDespesas(BasePermission):
    message = 'Acesso restrito aos grupos de Despesas (despesasGestor, lancadorDespesas, Admin e Master).'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        return user.is_superuser or bool(_grupos(user) & set(GRUPOS_MODULO))
