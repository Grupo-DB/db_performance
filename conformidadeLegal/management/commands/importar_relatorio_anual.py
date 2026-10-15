"""
Importa um Relatório Anual de Acompanhamento já entregue (PDF) para uma licença.

    manage.py importar_relatorio_anual --norma 4 --pdf "/root/Item 14.2.pdf"            # só mostra a prévia
    manage.py importar_relatorio_anual --norma 4 --pdf "/root/Item 14.2.pdf" --aplicar  # grava

Mesma regra da tela (Relatório anual → Importar relatório entregue): ver importar_relatorio.py.
"""
from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from conformidadeLegal import importar_relatorio
from conformidadeLegal.models import Norma


class Command(BaseCommand):
    help = 'Importa as respostas e fotos de um relatório anual (PDF) para a licença.'

    def add_arguments(self, parser):
        parser.add_argument('--norma', type=int, required=True)
        parser.add_argument('--pdf', required=True)
        parser.add_argument('--data', help='Data das verificações (AAAA-MM-DD). Padrão: último dia do mês da capa.')
        parser.add_argument('--usuario', default='', help='Login de quem fica como verificador (padrão: nenhum).')
        parser.add_argument('--aplicar', action='store_true')
        parser.add_argument('--nao-criar', action='store_true', help='Não criar as condicionantes que faltam.')
        parser.add_argument('--manter-ausentes', action='store_true',
                            help='Não tirar do relatório as condicionantes que o PDF não traz.')

    def handle(self, *args, **o):
        try:
            norma = Norma.objects.get(pk=o['norma'])
        except Norma.DoesNotExist:
            raise CommandError(f'Norma {o["norma"]} não existe.')
        with open(o['pdf'], 'rb') as f:
            try:
                lido = importar_relatorio.ler(f.read())
            except importar_relatorio.PdfIlegivel as e:
                raise CommandError(str(e))
        resumo = importar_relatorio.resumo_json(norma, lido, importar_relatorio.planejar(norma, lido))
        t = resumo['totais']
        self.stdout.write(f'Licença: {norma.identificacao}')
        self.stdout.write(f'PDF: {t["condicionantes"]} condicionantes ({t["casadas"]} já no sistema, {t["novas"]} novas), '
                          f'{t["com_resposta"]} com resposta, {t["figuras"]} figuras.')
        self.stdout.write(f'No sistema e fora do PDF: {t["ausentes"]} '
                          f'({", ".join(a["referencia"] or "s/ nº" for a in resumo["ausentes"])})')
        self.stdout.write(f'Passam a "Aplicável": {t["viram_aplicavel"]}')
        self.stdout.write(f'Capa lida: {resumo["capa"]} | data: {resumo["data"]}')
        for aviso in resumo['avisos']:
            self.stdout.write(self.style.WARNING(f'Aviso: {aviso}'))
        if not o['aplicar']:
            self.stdout.write('Prévia apenas (use --aplicar para gravar).')
            return
        data_vcl = date.fromisoformat(o['data']) if o['data'] else (lido['data'] or date.today())
        usuario = User.objects.filter(username=o['usuario']).first() if o['usuario'] else None
        r = importar_relatorio.aplicar(norma, lido, usuario, data_vcl, criar_faltantes=not o['nao_criar'],
                                       tirar_ausentes=not o['manter_ausentes'], nome_pdf=o['pdf'].rsplit('/', 1)[-1])
        self.stdout.write(self.style.SUCCESS(
            f'Gravado em {data_vcl:%d/%m/%Y}: {r["respondidos"]} respostas, {r["fotos"]} fotos, {r["criados"]} condicionantes '
            f'criadas, {r["fora"]} fora do relatório, {r["repetidos"]} já existiam.'))
