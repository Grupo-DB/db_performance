from rest_framework.routers import DefaultRouter
from .views import LocalViewSet, RoyaltyViewSet, FaturaViewSet

router = DefaultRouter()
router.register(r'locais', LocalViewSet, basename='local')
router.register(r'royalties', RoyaltyViewSet, basename='royalty')
router.register(r'faturas', FaturaViewSet, basename='fatura')

urlpatterns = router.urls