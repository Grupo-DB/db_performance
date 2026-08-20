from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (AlunoViewSet, AvaliacaoTreinamentoViewSet, CursoViewSet,
                    MatriculaViewSet, TurmaViewSet, analise_por_aluno, cursos_por_periodo)

router = DefaultRouter()
router.register(r'aluno', AlunoViewSet, basename='Aluno')
router.register(r'curso', CursoViewSet, basename='Curso')
router.register(r'turma', TurmaViewSet, basename='Turma')
router.register(r'matricula', MatriculaViewSet, basename='Matricula')
router.register(r'avaliacao', AvaliacaoTreinamentoViewSet, basename='AvaliacaoTreinamento')

urlpatterns = [
    path('', include(router.urls)),
    path('relatorios/cursos-por-periodo/', cursos_por_periodo, name='UnidbCursosPorPeriodo'),
    path('relatorios/por-aluno/', analise_por_aluno, name='UnidbAnalisePorAluno'),
]
