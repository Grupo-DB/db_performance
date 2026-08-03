from rest_framework.permissions import BasePermission

GRUPOS_RH = ('Admin', 'Master', 'RHGestor')


class IsRH(BasePermission):
    """
    Libera o módulo apenas para Admin, Master e RHGestor.

    O projeto está com ``DEFAULT_PERMISSION_CLASSES`` vazio, então cada view
    precisa declarar a sua permissão explicitamente -- não confie no default.
    """

    message = 'Acesso restrito aos grupos Admin, Master e RHGestor.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name__in=GRUPOS_RH).exists()
