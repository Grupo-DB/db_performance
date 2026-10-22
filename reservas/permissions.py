from rest_framework.permissions import SAFE_METHODS, BasePermission

# Quem cria, edita e exclui reservas e objetos (mesmos grupos do menu de antes).
GRUPOS_GESTAO_RESERVAS = ('Admin', 'Master', 'gestorReservas')


def pode_gerir_reservas(user) -> bool:
    return bool(user and user.is_authenticated and (
        user.is_superuser or user.groups.filter(name__in=GRUPOS_GESTAO_RESERVAS).exists()))


class VerTodosGerirGestores(BasePermission):
    """
    Agenda de reservas: qualquer usuário logado VÊ (calendário e lista); criar, editar e excluir
    só a gestão. O projeto está com DEFAULT_PERMISSION_CLASSES vazio — sem esta classe a API
    ficava aberta até sem login (22/10/2026).
    """
    message = 'Só a gestão de reservas pode alterar a agenda.'

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or pode_gerir_reservas(request.user)
