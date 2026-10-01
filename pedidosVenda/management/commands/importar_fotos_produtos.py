"""
Importa fotos de produto em lote a partir de uma pasta com `mapeamento.json`:

    [{"arquivo": "primor-hidraulica.jpg", "descricao": "PRIMOR CAL HIDRÁULICA 20 KG", "codigos": [2743, 11598]}, ...]

    venv/bin/python manage.py importar_fotos_produtos /caminho/da/pasta [--substituir] [--simular]

Sem --substituir, código que já tem foto fica como está (a foto cadastrada na
tela vale mais que a do lote). Com --substituir, a foto do lote troca a atual.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pedidosVenda import fotos
from pedidosVenda.models import FotoProduto


class Command(BaseCommand):
    help = 'Importa fotos de produto em lote a partir de mapeamento.json'

    def add_arguments(self, parser):
        parser.add_argument('pasta')
        parser.add_argument('--substituir', action='store_true', help='Troca a foto de quem já tem')
        parser.add_argument('--simular', action='store_true', help='Só mostra o que faria')

    def handle(self, pasta, substituir, simular, **_):
        base = Path(pasta)
        try:
            entradas = json.loads((base / 'mapeamento.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Não consegui ler {base / "mapeamento.json"}: {exc}')

        criadas = trocadas = puladas = 0
        for e in entradas:
            arquivo = base / e['arquivo']
            codigos = sorted({int(c) for c in e['codigos']})
            if not arquivo.exists():
                self.stderr.write(self.style.ERROR(f'Falta o arquivo {arquivo}'))
                continue

            existentes = [f for f in FotoProduto.objects.all() if set(f.codigos) & set(codigos)]
            if existentes and not substituir:
                puladas += 1
                self.stdout.write(f'  pula  {e["descricao"]}: já tem foto ({", ".join(str(f.pk) for f in existentes)})')
                continue
            if simular:
                self.stdout.write(f'  {"troca" if existentes else "cria "} {e["descricao"]} → {codigos}')
                continue

            with transaction.atomic(), arquivo.open('rb') as fh:
                imagem, miniatura = fotos.processar(fh)
                # A foto do lote leva os códigos; quem os tinha perde só esses códigos.
                for f in existentes:
                    restantes = [c for c in f.codigos if c not in codigos]
                    if restantes:
                        f.codigos = restantes
                        f.save(update_fields=['codigos', 'atualizado_em'])
                    else:
                        f.imagem.delete(save=False)
                        f.miniatura.delete(save=False)
                        f.delete()
                FotoProduto.objects.create(codigos=codigos, descricao=e.get('descricao', ''), imagem=imagem, miniatura=miniatura)
            if existentes:
                trocadas += 1
            else:
                criadas += 1
            self.stdout.write(self.style.SUCCESS(f'  ok    {e["descricao"]} → {codigos}'))

        self.stdout.write(self.style.SUCCESS(f'Criadas {criadas}, trocadas {trocadas}, puladas {puladas}.'))
