"""Páginas legais públicas exigidas pela Meta para publicar o app do WhatsApp.

A Meta pede uma URL de Política de Privacidade e uma de Termos de Uso no cadastro do
app, e busca essas páginas durante a revisão. São servidas aqui, renderizadas no
servidor, e não como rota do Angular: o revisor pode buscar a URL com um cliente HTTP
que não executa JavaScript, e uma rota do SPA devolveria página em branco.

Precisam ficar acessíveis SEM autenticação — daí `AllowAny` explícito, já que o
DEFAULT_PERMISSION_CLASSES do projeto não é confiável para esse fim.
"""
from django.utils import timezone
from django.views.generic import TemplateView


# Nome curto usado no título e no rodapé das páginas. Os dados cadastrais (razão social,
# CNPJ, endereço) ficam como campos a preencher dentro dos templates, para ninguém
# publicar com valor inventado.
EMPRESA_NOME = 'Grupo DB'

# Data mostrada como "última atualização". Fixa de propósito: se viesse de
# `timezone.now()`, a página anunciaria alteração a cada acesso, o que é enganoso num
# documento legal. Atualize junto com o texto.
ATUALIZADO_EM = '04/08/2026'


class PaginaLegalView(TemplateView):
    """Página estática pública. Sem login, sem dado de usuário."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['empresa_nome'] = EMPRESA_NOME
        ctx['atualizado_em'] = ATUALIZADO_EM
        return ctx


class PoliticaPrivacidadeView(PaginaLegalView):
    template_name = 'legal/privacidade.html'


class TermosUsoView(PaginaLegalView):
    template_name = 'legal/termos.html'
