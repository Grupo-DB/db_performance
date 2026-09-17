"""Unifica grafias divergentes de `Amostra.finalidade`.

A finalidade é gravada como TEXTO na amostra, e por anos cada tela ofereceu a sua
lista: a de Amostras dizia "Desenvolvimento de Produto" e a de Ordens de Serviço
"Desenvolvimento de Produtos". O resultado são duas fatias para a mesma coisa nos
gráficos e nos relatórios.

Ver o que existe hoje na base:

    venv/bin/python manage.py unificar_finalidade --listar

Unificar (o `--simular` mostra quantas mudariam, sem gravar):

    venv/bin/python manage.py unificar_finalidade \\
        --de "Desenvolvimento de Produtos" --para "Desenvolvimento de Produto" --simular
    venv/bin/python manage.py unificar_finalidade \\
        --de "Desenvolvimento de Produtos" --para "Desenvolvimento de Produto"

O destino é criado no cadastro se ainda não existir, e a grafia de origem é
removida de lá — senão ela voltaria a ser oferecida no select e o problema
recomeçaria.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from controleQualidade.amostra.models import Amostra
from controleQualidade.ensaio.models import Finalidade


class Command(BaseCommand):
    help = 'Lista ou unifica grafias de finalidade gravadas nas amostras.'

    def add_arguments(self, parser):
        parser.add_argument('--listar', action='store_true',
                            help='Só mostra as finalidades em uso, com a contagem de amostras.')
        parser.add_argument('--de', help='Grafia a ser substituída (exata).')
        parser.add_argument('--para', help='Grafia que fica.')
        parser.add_argument('--simular', action='store_true',
                            help='Mostra quantas amostras mudariam e não grava nada.')

    def handle(self, *args, **options):
        if options['listar'] or not (options['de'] or options['para']):
            self._listar()
            return

        de = (options['de'] or '').strip()
        para = (options['para'] or '').strip()
        if not de or not para:
            raise CommandError('Informe --de e --para (ou use --listar).')
        if de == para:
            raise CommandError('--de e --para são iguais; nada a fazer.')

        alvo = Amostra.objects.filter(finalidade=de)
        total = alvo.count()

        if options['simular']:
            self.stdout.write(f'{total} amostra(s) passariam de "{de}" para "{para}".')
            return

        if total:
            alvo.update(finalidade=para)
        self.stdout.write(self.style.SUCCESS(f'{total} amostra(s) atualizada(s) para "{para}".'))

        # O cadastro precisa acompanhar, senão a grafia antiga continua no select.
        destino, criado = Finalidade.objects.get_or_create(nome=para)
        if criado:
            self.stdout.write(self.style.SUCCESS(f'Finalidade "{para}" criada no cadastro.'))

        removidas = Finalidade.objects.filter(nome=de).delete()[0]
        if removidas:
            self.stdout.write(self.style.SUCCESS(f'Finalidade "{de}" removida do cadastro.'))

    def _listar(self):
        usos = (Amostra.objects
                .values('finalidade')
                .annotate(quantas=Count('id'))
                .order_by('-quantas'))

        cadastradas = set(Finalidade.objects.values_list('nome', flat=True))

        self.stdout.write('Finalidades em uso nas amostras:')
        for uso in usos:
            nome = uso['finalidade']
            rotulo = repr(nome) if nome in (None, '') else nome
            marca = '' if nome in cadastradas else '   <- fora do cadastro'
            self.stdout.write(f"  {uso['quantas']:>6}  {rotulo}{marca}")

        orfas = cadastradas - {u['finalidade'] for u in usos}
        if orfas:
            self.stdout.write('\nNo cadastro e sem nenhuma amostra:')
            for nome in sorted(orfas):
                self.stdout.write(f'         {nome}')
