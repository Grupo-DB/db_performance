"""
Carga inicial das fichas da planilha "Vistoria Máquinas - Versão 1.0.xlsx" (Anexo A).

Criticidade sugerida pela pontuação da planilha (10 = GRAVE → crítica, 5 = MÉDIO → média,
2,5 = PEQUENO → leve); abono só em "Danos na pintura" e "Danos na lataria/estrutura".
O GEO revisa na tela antes de começar (seção 4 / Anexo A). Idempotente: ficha que já existe fica.
"""
import json
from pathlib import Path

from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from PIL import Image

from vistorias import servicos
from vistorias.models import Ficha, ImagemTipo, TipoEquipamento

DADOS = Path(__file__).resolve().parents[2] / 'dados' / 'fichas_v1.json'
IMAGENS = DADOS.parent / 'imagens'


class Command(BaseCommand):
    help = 'Cria as fichas e os tipos de equipamento da planilha de vistoria (versão 1).'

    @transaction.atomic
    def handle(self, *args, **opts):
        dados = json.loads(DADOS.read_text(encoding='utf-8'))
        for f in dados['fichas']:
            ficha, criada = Ficha.objects.get_or_create(nome=f['nome'], defaults={'descricao': f['origem'][:300]})
            if criada or ficha.versao_atual() is None:
                servicos.nova_versao(ficha, f['questoes'], None, 'Carga inicial da planilha (versão 1.0 de 21/03/2023)')
                self.stdout.write(f'Ficha {ficha.nome}: {len(f["questoes"])} questões')
            for t in f['tipos']:
                tipo, novo = TipoEquipamento.objects.get_or_create(
                    codigo=t['codigo'], defaults={'descricao': t['descricao'], 'ficha': ficha, 'medicao': t['medicao']})
                if novo:
                    self.stdout.write(f'  tipo {t["codigo"]}')
                # desenhos para marcar avarias: só se o tipo ainda não tem nenhum (não duplica nem desfaz o que o GEO trocou)
                if not tipo.imagens.exists():
                    for ordem, nome in enumerate(t.get('imagens', []), 1):
                        caminho = IMAGENS / nome
                        with Image.open(caminho) as im:
                            larg, alt = im.size
                        img = ImagemTipo(tipo=tipo, ordem=ordem, largura=larg, altura=alt)
                        with open(caminho, 'rb') as fh:
                            img.arquivo.save(nome, File(fh), save=True)
                    if t.get('imagens'):
                        self.stdout.write(f'  {t["codigo"]}: {len(t["imagens"])} desenho(s)')
