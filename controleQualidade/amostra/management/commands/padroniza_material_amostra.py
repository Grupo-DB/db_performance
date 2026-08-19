"""
Padroniza a grafia de `Amostra.material` (acento e caixa) para a lista oficial.

Motivo: a tela de OS Encerradas mostrava "Calcario" e "Calcário" como dois materiais
diferentes — o filtro de material agrupa por texto exato. O select da tela já oferece
só a grafia certa ("Calcário"); as divergências são de registros antigos, gravados
antes de o select existir (6 amostras em 19/08/2026, além de 1 "Mineracao").

    python manage.py padroniza_material_amostra --dry-run   # só mostra o que mudaria
    python manage.py padroniza_material_amostra             # grava

⚠️ NÃO mexe em `ProdutoAmostra.material` nem em `TipoAmostra.material`: nessas duas
tabelas o campo é CHAVE DE BUSCA, gravada de propósito sem acento e em minúsculas
('calcario', 'argamassa'), porque o frontend consulta produtos/tipos com o material
normalizado (`normalize()` em amostra.ts). Trocar por "Calcário" ali quebraria o
carregamento de produto e de local de coleta. Como a normalização remove o acento,
corrigir a Amostra não afeta essas buscas.
"""
import unicodedata
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from controleQualidade.amostra.models import Amostra

# Mesma lista do select de material em amostra.ts (frontend).
MATERIAIS_OFICIAIS = [
    'Aditivos', 'Areia', 'Argamassa', 'Cal', 'Calcário', 'Dolomita', 'Cimento',
    'Cinza Pozolana', 'Finaliza', 'Mineração', 'Padrão', 'Outros',
]


def chave(texto):
    """'CALCARIO', 'Calcario', ' calcário ' → 'calcario' (sem acento, minúsculo)."""
    if not texto:
        return ''
    sem_acento = unicodedata.normalize('NFD', str(texto))
    sem_acento = ''.join(c for c in sem_acento if unicodedata.category(c) != 'Mn')
    return sem_acento.lower().strip()


OFICIAL_POR_CHAVE = {chave(m): m for m in MATERIAIS_OFICIAIS}


class Command(BaseCommand):
    help = 'Uniformiza a grafia de Amostra.material (ex.: Calcario → Calcário).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Mostra as mudanças sem gravar.')

    def handle(self, *args, **opcoes):
        simular = opcoes['dry_run']

        # A comparação é feita em PYTHON, linha a linha, e não com distinct()/filter()
        # do banco: a collation do MySQL é insensível a acento e a caixa, então
        # `values_list('material').distinct()` junta 'Calcario' com 'Calcário' e
        # `filter(material='Calcário')` casa com as duas — o comando não veria nada
        # para corrigir e ainda arriscaria atualizar a linha errada.
        por_oficial = {}          # 'Calcário' → [ids]
        mudancas = Counter()      # ('Calcario', 'Calcário') → quantas
        desconhecidos = Counter()

        for pk, material in Amostra.objects.values_list('id', 'material').iterator():
            oficial = OFICIAL_POR_CHAVE.get(chave(material))
            if oficial is None:
                if material:
                    desconhecidos[material] += 1
                continue
            if material == oficial:
                continue
            por_oficial.setdefault(oficial, []).append(pk)
            mudancas[(material, oficial)] += 1

        for (atual, oficial), quantas in sorted(mudancas.items()):
            self.stdout.write(f'{atual!r} → {oficial!r}: {quantas} amostra(s)')

        if desconhecidos:
            self.stdout.write(self.style.WARNING(
                'Fora da lista oficial (não mexi): '
                + ', '.join(f'{m!r} ({q})' for m, q in sorted(desconhecidos.items()))))

        total = sum(mudancas.values())
        if simular:
            self.stdout.write(self.style.WARNING(
                f'--dry-run: nada gravado ({total} amostra(s) mudariam).'))
            return

        with transaction.atomic():
            for oficial, ids in por_oficial.items():
                # Atualiza por ID: `filter(material=...)` pegaria as duas grafias.
                Amostra.objects.filter(id__in=ids).update(material=oficial)
        self.stdout.write(self.style.SUCCESS(f'{total} amostra(s) padronizada(s).'))
