from rest_framework.permissions import BasePermission

# Campanha de uniformes: RH.
GRUPOS_UNIFORMES = ('Admin', 'Master', 'RHGestor')


class IsRHUniformes(BasePermission):
    """``DEFAULT_PERMISSION_CLASSES`` está vazio no projeto: sem isto a API ficaria aberta."""

    message = 'Acesso restrito ao RH.'

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return user.groups.filter(name__in=GRUPOS_UNIFORMES).exists()
