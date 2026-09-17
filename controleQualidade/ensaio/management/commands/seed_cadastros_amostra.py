"""Carrega finalidades, fornecedores e locais de coleta que estavam fixos no front.

Roda uma vez, depois da migration: sem isto os selects da tela de Amostras caem
no fallback (as mesmas listas, porém sem poder cadastrar). Idempotente — repetir
não duplica, e os locais de coleta que já existirem no cadastro ficam como estão.

    venv/bin/python manage.py seed_cadastros_amostra
"""

from django.core.management.base import BaseCommand

from controleQualidade.amostra.models import TipoAmostra
from controleQualidade.ensaio.models import Finalidade, Fornecedor

FINALIDADES = [
    'Controle de Qualidade',
    'SAC',
    'Desenvolvimento de Produto',
    'Demanda Comercial',
    'Reanálise',
    'Teste Manutenção',
    'Teste',
    'Duplicata',
    'Treinamento',
    'Padrão',
    'Controle Matéria Prima',
    'Outros',
]

FORNECEDORES = [
    'Cibracal',
    'Cliente',
    'Coradassi',
    'Cotrisul',
    'DB',
    'DB ATM',
    'Increment',
]


# Local de Coleta é o cadastro `TipoAmostra`, que já existia — esta lista estava
# num array MORTO dentro de amostra.ts (o select sempre leu o cadastro), então
# boa parte destes nomes pode nunca ter sido cadastrada de fato.
# `natureza` e `material` ficam vazios: o select de Local de Coleta usa a lista
# inteira, sem recorte por material.
LOCAIS_COLETA = [
    '1 hora na estufa',
    '30 minutos na estufa',
    'Área da Indústria',
    'Argamassa',
    'Arroio Grande',
    'Bag Cliente',
    'Big Bag',
    'Britagem',
    'Cascalho Britagem',
    'Cliente',
    'Cliente do Everton',
    'Cliente Lavoura',
    'Cliente/Lavoura',
    'CT-10',
    'CT-09',
    'Despoeiramento CT-16',
    'Estoque',
    'FAB',
    'FAB I',
    'FAB I Carregamento',
    'FAB II',
    'Saco',
]


class Command(BaseCommand):
    help = 'Cria finalidades, fornecedores e locais de coleta que eram fixos no front.'

    def handle(self, *args, **options):
        total = 0
        for modelo, nomes in ((Finalidade, FINALIDADES), (Fornecedor, FORNECEDORES)):
            for ordem, nome in enumerate(nomes, start=1):
                obj, novo = modelo.objects.get_or_create(nome=nome, defaults={'ordem': ordem})
                if novo:
                    total += 1
                    self.stdout.write(self.style.SUCCESS(f'criado: {modelo.__name__} "{obj}"'))

        # TipoAmostra não tem `nome` único no banco: `get_or_create` por nome é o
        # que evita uma segunda "Britagem" para quem já cadastrou algumas à mão.
        for nome in LOCAIS_COLETA:
            obj, novo = TipoAmostra.objects.get_or_create(
                nome=nome, defaults={'natureza': '', 'material': ''},
            )
            if novo:
                total += 1
                self.stdout.write(self.style.SUCCESS(f'criado: Local de Coleta "{obj.nome}"'))

        self.stdout.write(self.style.SUCCESS(f'{total} registro(s) criado(s).'))
