"""Páginas legais públicas exigidas pela Meta para publicar o app do WhatsApp.

A Meta pede uma URL de Política de Privacidade e uma de Termos de Uso no cadastro do
app, e busca essas páginas durante a revisão. São servidas aqui, renderizadas no
servidor, e não como rota do Angular: o revisor pode buscar a URL com um cliente HTTP
que não executa JavaScript, e uma rota do SPA devolveria página em branco.

Precisam ficar acessíveis SEM autenticação — daí `AllowAny` explícito, já que o
DEFAULT_PERMISSION_CLASSES do projeto não é confiável para esse fim.

Os dados cadastrais ficam nas constantes abaixo, e não espalhados pelos dois
templates: razão social, CNPJ e endereço aparecem nos dois documentos, e num texto
legal duas cópias que divergem é defeito sério. Para alterar, mexa só aqui — e
atualize `ATUALIZADO_EM` junto.
"""
from django.views.generic import TemplateView


# --- identificação da controladora -------------------------------------------
# Razão social como consta no CNPJ (a Receita grava "S A" sem pontuação).
EMPRESA_RAZAO_SOCIAL = 'DAGOBERTO BARCELLOS S A'
EMPRESA_CNPJ = '87.678.934/0001-65'
EMPRESA_ENDERECO = 'BR 392 SN KM 252,5 — Caieiras, Caçapava do Sul/RS, CEP 96570-000'

# Nome curto usado no título, no cabeçalho e no rodapé.
EMPRESA_NOME = 'Grupo DB'

# --- canal do titular de dados (LGPD art. 41) --------------------------------
# A LGPD exige encarregado nomeado e canal divulgado. O e-mail precisa existir e ser
# lido de fato: é por ele que chegam os pedidos de acesso e exclusão, com prazo legal
# para resposta.
DPO_NOME = 'Jian Carlo Goersch da Silva'
DPO_EMAIL = 'cpd@grupodb.com.br'
DPO_TELEFONE = '0800 808 0144'

# --- atendimento --------------------------------------------------------------
HORARIO_ATENDIMENTO = 'segunda a sexta-feira, das 8h às 12h e das 13h15 às 18h'
FORO = 'Caçapava do Sul/RS'

# Por quanto tempo conversas, mensagens e anexos ficam guardados depois de encerrado
# o atendimento. É promessa pública ao titular: mudar aqui muda o que prometemos.
RETENCAO = '24 (vinte e quatro) meses'

# Data mostrada como "última atualização". Fixa de propósito: se viesse de
# `timezone.now()`, a página anunciaria alteração a cada acesso, o que é enganoso num
# documento legal. Atualize junto com o texto.
ATUALIZADO_EM = '05/08/2026'


class PaginaLegalView(TemplateView):
    """Página estática pública. Sem login, sem dado de usuário."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'empresa_nome': EMPRESA_NOME,
            'razao_social': EMPRESA_RAZAO_SOCIAL,
            'cnpj': EMPRESA_CNPJ,
            'endereco': EMPRESA_ENDERECO,
            'dpo_nome': DPO_NOME,
            'dpo_email': DPO_EMAIL,
            'dpo_telefone': DPO_TELEFONE,
            'horario_atendimento': HORARIO_ATENDIMENTO,
            'foro': FORO,
            'retencao': RETENCAO,
            'atualizado_em': ATUALIZADO_EM,
        })
        return ctx


class PoliticaPrivacidadeView(PaginaLegalView):
    template_name = 'legal/privacidade.html'


class TermosUsoView(PaginaLegalView):
    template_name = 'legal/termos.html'
