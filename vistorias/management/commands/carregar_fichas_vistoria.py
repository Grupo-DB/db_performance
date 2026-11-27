"""
Carga inicial das fichas da planilha "Vistoria Máquinas - Versão 1.0.xlsx" (Anexo A).

Criticidade sugerida pela pontuação da planilha (10 = GRAVE → crítica, 5 = MÉDIO → média,
2,5 = PEQUENO → leve); abono só em "Danos na pintura" e "Danos na lataria/estrutura".
O GEO revisa na tela antes de começar (seção 4 / Anexo A). Idempotente: ficha que já existe fica.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from vistorias import servicos
from vistorias.models import Ficha, TipoEquipamento

DADOS = Path(__file__).resolve().parents[2] / 'dados' / 'fichas_v1.json'


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
                _, novo = TipoEquipamento.objects.get_or_create(
                    codigo=t['codigo'], defaults={'descricao': t['descricao'], 'ficha': ficha, 'medicao': t['medicao']})
                if novo:
                    self.stdout.write(f'  tipo {t["codigo"]}')
