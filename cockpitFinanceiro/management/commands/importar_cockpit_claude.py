"""Importa para o servidor o histórico de anexos que estava guardado dentro do artifact do
Claude (coleções `docs_*` + arquivos). Pode rodar de novo: documento já importado é pulado.

    python manage.py importar_cockpit_claude /caminho/importacao_claude

Estrutura esperada da pasta (gerada a partir do artifact em 25/09/2026):
    docs/<colecao>/<doc_id>.json   — {asset_id, filename, uploaded_at, uploaded_by, url, ...}
    arquivos/<asset_id>.<pdf|png>
    pessoas.json                   — {"u_...": "Nome"} para o "enviado por"
"""
import json
import os

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cockpitFinanceiro.models import AnexoCockpit, DocumentoCockpit

TIPOS = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}


class Command(BaseCommand):
    help = 'Importa os anexos que estavam no artifact do Claude.'

    def add_arguments(self, parser):
        parser.add_argument('pasta')

    def handle(self, pasta, **opts):
        docs_dir = os.path.join(pasta, 'docs')
        arq_dir = os.path.join(pasta, 'arquivos')
        if not os.path.isdir(docs_dir) or not os.path.isdir(arq_dir):
            raise CommandError(f'Pasta inválida: esperava {docs_dir} e {arq_dir}')
        try:
            with open(os.path.join(pasta, 'pessoas.json'), encoding='utf-8') as f:
                pessoas = json.load(f)
        except FileNotFoundError:
            pessoas = {}

        arquivos = {os.path.splitext(n)[0]: n for n in os.listdir(arq_dir)}
        novos = pulados = faltando = 0

        for colecao in sorted(os.listdir(docs_dir)):
            col_dir = os.path.join(docs_dir, colecao)
            if not os.path.isdir(col_dir):
                continue
            for nome_json in sorted(os.listdir(col_dir)):
                doc_id = os.path.splitext(nome_json)[0]
                if DocumentoCockpit.objects.filter(colecao=colecao, doc_id=doc_id).exists():
                    pulados += 1
                    continue
                with open(os.path.join(col_dir, nome_json), encoding='utf-8') as f:
                    dados = json.load(f)
                arquivo = arquivos.get(dados.get('asset_id') or '')
                if not arquivo:
                    faltando += 1
                    self.stderr.write(f'  sem arquivo: {colecao}/{doc_id} ({dados.get("filename")})')
                    continue

                ext = os.path.splitext(arquivo)[1].lower()
                tipo = dados.get('content_type') or TIPOS.get(ext, 'application/pdf')
                quem = pessoas.get(dados.get('uploaded_by') or '', dados.get('uploaded_by') or '')
                caminho = os.path.join(arq_dir, arquivo)

                with transaction.atomic():
                    anexo = AnexoCockpit(
                        nome=(dados.get('filename') or arquivo)[:255], content_type=tipo,
                        tamanho=os.path.getsize(caminho), enviado_por=quem[:120],
                    )
                    with open(caminho, 'rb') as fh:
                        anexo.arquivo.save(arquivo, File(fh), save=True)
                    dados.update({
                        'asset_id': str(anexo.id),
                        'url': f'api/anexos/{anexo.id}',
                        'uploaded_by': quem,
                    })
                    DocumentoCockpit.objects.create(
                        colecao=colecao, doc_id=doc_id, dados=dados, atualizado_por=quem[:120],
                    )
                novos += 1

        self.stdout.write(self.style.SUCCESS(
            f'Importados: {novos} · já existiam: {pulados} · sem arquivo: {faltando}'))
