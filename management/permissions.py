from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.permissions import DjangoModelPermissions
class IsInGroup(BasePermission):
    """
    Custom permission to only allow users in a specific group.
    """
    def has_permission(self, request, view):
        # Verifique se o usuário está autenticado
        if not request.user.is_authenticated:
            return False
        
        if request.method in SAFE_METHODS:
            # Se o método for seguro (GET, HEAD ou OPTIONS), permita o acesso
            return True
        
        # Verifique se o usuário pertence ao grupo 'your_group_name'
        return request.user.groups.filter(name='teste').exists()
    


   