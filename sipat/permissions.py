from rest_framework.permissions import BasePermission

# 'Sipat' é o grupo para quem organiza o evento (CIPA/SESMT) sem precisar de RHGestor.
GRUPOS_SIPAT = ('Admin', 'Master', 'RHGestor', 'Sipat')


class IsSipat(BasePermission):
    """
    O projeto está com ``DEFAULT_PERMISSION_CLASSES`` vazio, então a permissão
    precisa ser declarada aqui — sem ela a API ficaria aberta sem login.
    """

    message = 'Acesso restrito à organização da SIPAT.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name__in=GRUPOS_SIPAT).exists()
