"""Importação da planilha de uniformes — usada pela tela (linhas lidas no navegador) e pelo
comando ``importar_uniformes`` (lê o xlsx no servidor)."""
from datetime import datetime

from django.db import transaction

from avaliacoes.management.models import Colaborador

from .models import ItemPedido, Pedido
from .regras import ler_celula, ler_entrega, ler_ziper, peca_do_pedido, sem_acento


def importar_linhas(campanha, linhas: list) -> dict:
    """``linhas``: ``{aba, nome, cpf, setor, jaqueta, sueter, camisa, soft, ziper, entrega, entrega_jaqueta}``."""
    por_nome = {sem_acento(c.nome): c for c in Colaborador.objects.select_related('cargo', 'setor')}
    criados = atualizados = 0
    sem_peca = set()
    with transaction.atomic():
        for linha in linhas:
            nome = ' '.join(str(linha.get('nome') or '').split())
            aba = sem_acento(linha.get('aba'))
            if not nome or ('FEMININ' not in aba and 'MASCULIN' not in aba):
                continue
            genero = 'F' if 'FEMININ' in aba else 'M'
            modalidade = Pedido.GANHA if 'GANHA' in aba else Pedido.COMPRA
            colaborador = por_nome.get(sem_acento(nome))
            pedido = Pedido.objects.filter(campanha=campanha, modalidade=modalidade, nome__iexact=nome).first()
            dados = {
                'cpf': str(linha.get('cpf') or '').strip(), 'setor': str(linha.get('setor') or '').strip(),
                'genero': genero, 'colaborador': colaborador,
                'cargo': colaborador.cargo.nome if colaborador and colaborador.cargo_id else '',
            }
            if pedido:
                for k, v in dados.items():
                    setattr(pedido, k, v)
                pedido.save()
                pedido.itens.all().delete()
                atualizados += 1
            else:
                pedido = Pedido.objects.create(campanha=campanha, nome=nome, modalidade=modalidade, **dados)
                criados += 1

            entregue, data, obs = ler_entrega(linha.get('entrega'))
            jaq_entregue, jaq_data, jaq_obs = ler_entrega(linha.get('entrega_jaqueta'))
            for campo, nome_peca in (('jaqueta', 'Jaqueta'), ('sueter', 'Suéter'), ('camisa', 'Camisa'), ('soft', 'Soft')):
                celula = ler_celula(linha.get(campo))
                if not celula:
                    continue
                peca = peca_do_pedido(campanha, nome_peca, genero)
                if not peca:
                    sem_peca.add(nome_peca)
                    continue
                if campo == 'jaqueta':
                    # A jaqueta chegou depois: vale a coluna dela; sem ela, a entrega geral
                    # só conta se for nota ("Jak levou", "DEMITIDO"), não data das outras peças.
                    e, d, o = (jaq_entregue, jaq_data, jaq_obs) if (jaq_entregue or jaq_obs) else \
                        ((entregue, None, obs) if not data else (False, None, ''))
                else:
                    e, d, o = entregue, data, obs
                ItemPedido.objects.create(
                    pedido=pedido, peca=peca, quantidade=celula[0], tamanho=celula[1],
                    ziper=ler_ziper(linha.get('ziper')) if peca.tem_ziper else '',
                    entregue=e, entregue_em=d, entrega_obs=o,
                )
    return {'criados': criados, 'atualizados': atualizados, 'pecas_nao_encontradas': sorted(sem_peca)}


def linhas_do_xlsx(caminho) -> list:
    """Abas FEMININOS/MASCULINOS × GANHA/COMPRA; cabeçalho = linha com CPF; colunas pelo nome."""
    import openpyxl

    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    saida = []
    for ws in wb.worksheets:
        aba = sem_acento(ws.title)
        if 'GANHA' not in aba and 'COMPRA' not in aba:
            continue
        cab = None
        for r in ws.iter_rows(values_only=True):
            valores = [sem_acento(v) for v in r]
            if 'CPF' in valores:
                cab = valores
                continue
            if not cab or not r or not r[0]:
                continue

            def col(*nomes):
                for n in nomes:
                    if n in cab and cab.index(n) < len(r):
                        return r[cab.index(n)]
                return None

            data = lambda v: v.date().isoformat() if isinstance(v, datetime) else (str(v) if v is not None else '')
            saida.append({
                'aba': ws.title, 'nome': r[0], 'cpf': col('CPF'), 'setor': col('SETOR'), 'jaqueta': col('JAQUETA'),
                'sueter': col('SUETER'), 'camisa': col('CAMISA'), 'soft': col('SOFT'), 'ziper': col('ZIPER DO SOFT'),
                'entrega': data(col('ENTREGA')), 'entrega_jaqueta': data(col('ENTREGA JAQUETA', 'ENTREGA DA JAQUETA')),
            })
    return saida
