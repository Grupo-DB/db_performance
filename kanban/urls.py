from rest_framework.routers import DefaultRouter
from rest_framework_nested.routers import NestedDefaultRouter
from .views import KanbanColumnViewSet, KanbanTaskViewSet, KanbanAnexoViewSet

router = DefaultRouter()
router.register(r'listas', KanbanColumnViewSet, basename='kanban-column')
router.register(r'tarefas', KanbanTaskViewSet, basename='kanban-task')
tarefas_router = NestedDefaultRouter(router, r'tarefas', lookup='tarefa')
tarefas_router.register(r'anexos', KanbanAnexoViewSet, basename='tarefa-anexos')

urlpatterns = router.urls + tarefas_router.urls