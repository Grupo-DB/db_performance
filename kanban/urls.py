from rest_framework.routers import DefaultRouter
from .views import KanbanColumnViewSet, KanbanTaskViewSet

router = DefaultRouter()
router.register(r'listas', KanbanColumnViewSet, basename='kanban-column')
router.register(r'tarefas', KanbanTaskViewSet, basename='kanban-task')

urlpatterns = router.urls