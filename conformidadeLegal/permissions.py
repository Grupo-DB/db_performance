from rest_framework.permissions import BasePermission

# 'ConformidadeLegal' é o grupo da equipe de SGI/meio ambiente/SST que mantém os requisitos.
GRUPOS_CONFORMIDADE = ('Admin', 'Master', 'ConformidadeLegal')


class IsConformidade(BasePermission):
    """
    O projeto está com ``DEFAULT_PERMISSION_CLASSES`` vazio, então a permissão
    precisa ser declarada aqui — sem ela a API ficaria aberta sem login.
    """

    message = 'Acesso restrito à equipe de Conformidade Legal.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name__in=GRUPOS_CONFORMIDADE).exists()
