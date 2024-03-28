from rolepermissions.roles import AbstractUserRole

class Rh(AbstractUserRole):
    available_permissions = {
        'cadastrar_user': True,
        'deletar_user': True,
    }
class Avaliador(AbstractUserRole):
    available_permissions = {
       'fazer_avaliacao': True, 

    }    