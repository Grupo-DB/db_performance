"""Carrega os planos de peneiramento que estavam fixos no frontend.

Roda uma vez, logo depois da migration: sem isto o cadastro nasce vazio e o
laboratório perde os três planos que já usava para digitar o peneiramento.
É idempotente (get_or_create por descrição + tipo), então repetir não duplica.

    venv/bin/python manage.py seed_planos_peneira
"""

from django.core.management.base import BaseCommand

from controleQualidade.ensaio.models import PlanoPeneira

PLANOS = [
    {
        'descricao': 'Reatividade do Calcário: RE',
        'tipo': PlanoPeneira.SECAS,
        'ordem': 1,
        'peneiras': [
            '# 10 - ABNT/ASTM 10 - 2,00 mm',
            '# 20 - ABNT/ASTM 20 - 0,850 mm',
            '# 50 - ABNT/ASTM 50 - 0,300 mm',
        ],
    },
    {
        'descricao': 'Argamassa e Areias',
        'tipo': PlanoPeneira.SECAS,
        'ordem': 2,
        'peneiras': [
            '# 8 - ABNT/ASTM 8 - 2,36 mm',
            '# 10 - ABNT/ASTM 10 - 2,00 mm',
            '# 16 - ABNT/ASTM 16 - 1,18 mm',
            '# 30 - ABNT/ASTM 30 - 0,600 mm',
            '# 50 - ABNT/ASTM 50 - 0,300 mm',
            '# 100 - ABNT/ASTM 100 - 0,150 mm',
        ],
    },
    {
        'descricao': 'Argamassa e Areias - Peneira Úmida',
        'tipo': PlanoPeneira.UMIDAS,
        'ordem': 1,
        'peneiras': [
            '# 30 - ABNT/ASTM 30 - 0,600 mm',
            '# 200 - ABNT/ASTM 200 - 0,075 mm',
        ],
    },
]


class Command(BaseCommand):
    help = 'Cria os planos de peneiramento originais (os que eram fixos no front).'

    def handle(self, *args, **options):
        criados = 0
        for plano in PLANOS:
            obj, novo = PlanoPeneira.objects.get_or_create(
                descricao=plano['descricao'],
                tipo=plano['tipo'],
                defaults={'peneiras': plano['peneiras'], 'ordem': plano['ordem']},
            )
            if novo:
                criados += 1
                self.stdout.write(self.style.SUCCESS(f'criado: {obj}'))
            else:
                self.stdout.write(f'já existia: {obj}')
        self.stdout.write(self.style.SUCCESS(f'{criados} plano(s) criado(s).'))
