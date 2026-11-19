"""Converte o GeoTIFF do MapBiomas (recorte do RS baixado na plataforma) no bitmap de lavoura.

Uso: manage.py importar_mapbiomas /caminho/mapbiomas_rs_2024.tif --ano 2024

Precisa de `rasterio` só onde roda (pode ser na máquina do dev; depois é copiar a pasta
MEDIA_ROOT/comercialAgro/mapbiomas para o servidor). O resultado é 1 bit por pixel
(lavoura sim/não) em lavoura.npy + lavoura.json; o servidor lê só com numpy.
"""
import json

import numpy as np
from django.core.management.base import BaseCommand, CommandError

from comercialAgro import geo

LINHAS_POR_BLOCO = 512


class Command(BaseCommand):
    help = 'Converte o GeoTIFF de cobertura do MapBiomas (RS) no bitmap de lavoura do Comercial Agro.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo')
        parser.add_argument('--ano', type=int, required=True)
        parser.add_argument('--banda', type=int, default=1, help='Banda do ano no arquivo (o recorte anual tem só a 1)')

    def handle(self, *args, **opts):
        try:
            import rasterio
        except ImportError:
            raise CommandError('Instale o rasterio onde for converter: pip install rasterio')
        pasta = geo.pasta_mapas()
        pasta.mkdir(parents=True, exist_ok=True)
        classes = np.array(geo.CLASSES_LAVOURA, dtype=np.uint8)
        with rasterio.open(opts['arquivo']) as src:
            if src.crs and src.crs.to_epsg() not in (4326, None):
                raise CommandError(f'Esperava EPSG:4326 (padrão do MapBiomas); veio {src.crs}.')
            t = src.transform
            altura, largura = src.height, src.width
            saida = np.lib.format.open_memmap(pasta / 'lavoura.tmp.npy', mode='w+', dtype=np.uint8,
                                              shape=(altura, (largura + 7) // 8))
            lavoura = 0
            for l0 in range(0, altura, LINHAS_POR_BLOCO):
                n = min(LINHAS_POR_BLOCO, altura - l0)
                bloco = src.read(opts['banda'], window=((l0, l0 + n), (0, largura)))
                m = np.isin(bloco, classes)
                lavoura += int(m.sum())
                saida[l0:l0 + n] = np.packbits(m, axis=1)
            saida.flush()
            del saida
        (pasta / 'lavoura.tmp.npy').replace(pasta / 'lavoura.npy')
        (pasta / 'lavoura.json').write_text(json.dumps({
            'ano': opts['ano'], 'x0': t.c, 'dx': t.a, 'y0': t.f, 'dy': t.e, 'largura': largura, 'altura': altura,
        }))
        ha = lavoura * abs(t.a * t.e) * (111_320 ** 2) * 0.86 / 10_000  # aproximado (latitude do RS)
        self.stdout.write(self.style.SUCCESS(
            f'{largura}×{altura} px; ~{ha / 1e6:.1f} mi ha de lavoura em {opts["ano"]}. Salvo em {pasta}.'))
