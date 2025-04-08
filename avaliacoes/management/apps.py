from django.apps import AppConfig

class ManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'avaliacoes.management'

    def ready(self):
        import avaliacoes.management.tasks
        