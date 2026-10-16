from rest_framework.permissions import BasePermission

# Quem acompanha o período de experiência é o RH.
GRUPOS_APRENDIZES = ('Admin', 'Master', 'RHGestor')


class IsRHAcompanhamento(BasePermission):
    """``DEFAULT_PERMISSION_CLASSES`` está vazio no projeto: sem isto a API ficaria aberta."""

    message = 'Acesso restrito ao RH.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name__in=GRUPOS_APRENDIZES).exists()
