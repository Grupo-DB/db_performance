"""Religa uma amostra à sua original: grava o vínculo e a renumera como derivada.

Existe para consertar as duplicatas/reanálises cadastradas ANTES de o vínculo
funcionar em todos os caminhos da tela — elas nasceram com finalidade 'Duplicata'
ou 'Reanálise' mas com `amostra_origem` nulo e um sequencial novo
('calcario 00.0587' onde devia ser 'calcario 00.0530.1').

    python manage.py religa_derivada --amostra "calcario 00.0587" \
                                     --origem  "calcario 00.0530"           # simula
    python manage.py religa_derivada --amostra ... --origem ... --aplicar   # grava

`--amostra` e `--origem` aceitam o número ou o id. Sem `--aplicar` nada é gravado:
imprime o de-para e sai.

⚠️ Renumerar amostra que JÁ CIRCULOU muda o que a etiqueta e o laudo impressos
dizem. O comando avisa quando a amostra tem OS ou análise — é o caso normal aqui,
já que o erro só aparece depois de a análise existir.

O sequencial liberado volta a ser o próximo do material: 'calcario 00.0587' vira
derivada e o próximo calcário nasce 0587 de novo, sem buraco na numeração.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from controleQualidade.amostra.numeracao import (
    proximo_numero_derivada, separar_derivada)


def achar(referencia):
    """Amostra por id ou por número. Erro claro em vez de DoesNotExist cru."""
    from controleQualidade.amostra.models import Amostra

    texto = str(referencia).strip()
    if texto.isdigit():
        amostra = Amostra.objects.filter(pk=int(texto)).first()
        if amostra:
            return amostra
    amostra = Amostra.objects.filter(numero__iexact=texto).first()
    if not amostra:
        raise CommandError(f'Nenhuma amostra com id ou número {referencia!r}.')
    return amostra


class Command(BaseCommand):
    help = 'Aponta uma amostra para a original e a renumera como .1, .2…'

    def add_arguments(self, parser):
        parser.add_argument('--amostra', required=True,
                            help='A duplicata/reanálise a corrigir (número ou id).')
        parser.add_argument('--origem', required=True,
                            help='A amostra original (número ou id).')
        parser.add_argument('--aplicar', action='store_true',
                            help='Grava. Sem isto, apenas simula.')
        parser.add_argument('--manter-numero', action='store_true',
                            help='Grava só o vínculo, sem mexer no número.')

    def handle(self, *args, **opcoes):
        derivada = achar(opcoes['amostra'])
        origem = achar(opcoes['origem'])

        if derivada.pk == origem.pk:
            raise CommandError('A amostra não pode ser origem dela mesma.')

        # Renumerar um tronco deixaria as filhas dele com o número de uma família
        # que não existe mais.
        filhas = list(derivada.derivadas.values_list('numero', flat=True))
        if filhas and not opcoes['manter_numero']:
            raise CommandError(
                f'{derivada.numero} já é origem de {", ".join(filhas)}. '
                'Renumerá-la deixaria essas órfãs — trate-as antes, ou use '
                '--manter-numero.')

        with transaction.atomic():
            novo_numero = None
            if not opcoes['manter_numero']:
                novo_numero = proximo_numero_derivada(origem, travar=True)
                if not novo_numero:
                    raise CommandError(
                        f'Não deu para montar o número a partir de {origem.numero!r}.')

                base, _ = separar_derivada(derivada.numero)
                if base == separar_derivada(origem.numero)[0]:
                    self.stdout.write(self.style.WARNING(
                        f'{derivada.numero} já é da família de {origem.numero}.'))

            self.stdout.write(f'  amostra : {derivada.numero} (id {derivada.pk})')
            self.stdout.write(f'  origem  : {origem.numero} (id {origem.pk})')
            self.stdout.write(f'  vínculo : amostra_origem = {origem.pk}')
            if novo_numero:
                self.stdout.write(f'  número  : {derivada.numero} → {novo_numero}')

            tem_os = derivada.ordem_id or derivada.expressa_id
            if tem_os or derivada.analise.exists():
                self.stdout.write(self.style.WARNING(
                    '  ⚠ esta amostra já tem OS/análise: etiqueta ou laudo impressos '
                    'passam a divergir do número novo.'))

            if not opcoes['aplicar']:
                self.stdout.write(self.style.WARNING(
                    'Simulação — nada gravado. Repita com --aplicar.'))
                return

            derivada.amostra_origem = origem
            campos = ['amostra_origem']
            if novo_numero:
                derivada.numero = novo_numero
                campos.append('numero')
            derivada.save(update_fields=campos)

        self.stdout.write(self.style.SUCCESS(f'Pronto: {derivada.numero}.'))
