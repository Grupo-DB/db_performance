"""Importação da planilha antiga — usada pela tela (linhas lidas no navegador) e pelo
comando ``importar_experiencia`` (lê o xlsx no servidor). As duas montam as mesmas linhas."""
from collections import defaultdict
from datetime import date, datetime

from django.db import transaction

from avaliacoes.management.models import Colaborador

from .models import Acompanhamento, Etapa
from .regras import checklist_do_texto, chave_nome, data_da_planilha, situacao_da_planilha, tipo_da_planilha


def _dados_do_colaborador(c: Colaborador) -> dict:
    return {
        'colaborador': c,
        'nome': c.nome.strip(),
        'setor': getattr(c.setor, 'nome', '') or '',
        'cargo': getattr(c.cargo, 'nome', '') or '',
        'data_admissao': c.data_admissao.date() if c.data_admissao else None,
    }


def importar_linhas(linhas: list) -> dict:
    """``linhas``: ``{aba, nome, setor, cargo, tipo, vencimento, situacao, observacao}``."""
    por_nome = {chave_nome(c.nome): c for c in Colaborador.objects.select_related('setor', 'cargo')}
    criados = atualizadas = etapas_criadas = 0
    ignoradas = []
    # Pessoa → acompanhamentos já existentes (a mesma pessoa pode ter voltado).
    existentes = defaultdict(list)
    for a in Acompanhamento.objects.prefetch_related('etapas'):
        existentes[chave_nome(a.nome)].append(a)

    linhas_ordenadas = sorted(
        [l for l in linhas if isinstance(l, dict)],
        key=lambda l: (data_da_planilha(l.get('vencimento')) or date.max),
    )
    with transaction.atomic():
        for i, linha in enumerate(linhas_ordenadas):
            nome = str(linha.get('nome') or '').strip()
            tipo = tipo_da_planilha(linha.get('tipo'))
            venc = data_da_planilha(linha.get('vencimento'))
            texto_tipo = chave_nome(linha.get('tipo'))
            if not nome or (not tipo and texto_tipo != 'DEMITIDO'):
                ignoradas.append({'linha': linha.get('aba', ''), 'nome': nome, 'motivo': 'sem nome ou tipo desconhecido'})
                continue
            situacao, pendencia = situacao_da_planilha(linha.get('situacao'))
            if texto_tipo == 'DEMITIDO':  # tipo "DEMITIDO": a pessoa saiu antes da etapa
                tipo, situacao = Etapa.PRORROGACAO, Etapa.DESLIGADO
            if not venc:
                # "PEDIDO DE DEMISSÃO" escrito no lugar da data: guarda a etapa no mês da aba.
                aba = str(linha.get('aba') or '')
                venc = date(int(aba[2:6]), int(aba[:2]), 1) if len(aba) == 6 and aba.isdigit() else None
                situacao_texto, _ = situacao_da_planilha(linha.get('vencimento'))
                if situacao_texto != Etapa.PENDENTE:
                    situacao = situacao_texto
            if not venc:
                ignoradas.append({'linha': linha.get('aba', ''), 'nome': nome, 'motivo': 'sem vencimento'})
                continue

            chave = chave_nome(nome)
            acompanhamento = next(
                (a for a in existentes[chave]
                 if not any(e.tipo == tipo and e.vencimento != venc for e in a.etapas.all())),
                None,
            )
            if acompanhamento is None:
                colaborador = por_nome.get(chave)
                base = _dados_do_colaborador(colaborador) if colaborador else {'nome': nome}
                base['setor'] = str(linha.get('setor') or '').strip() or base.get('setor', '')
                base['cargo'] = str(linha.get('cargo') or '').strip() or base.get('cargo', '')
                base['nome'] = colaborador.nome.strip() if colaborador else nome
                acompanhamento = Acompanhamento.objects.create(**base)
                existentes[chave].append(acompanhamento)
                criados += 1

            observacao = str(linha.get('observacao') or '').strip()
            etapa = next((e for e in acompanhamento.etapas.all() if e.tipo == tipo), None)
            campos = {
                'vencimento': venc, 'situacao': situacao,
                'avaliacao_feita': situacao == Etapa.CONCLUIDO,
                'pendencia': pendencia, 'observacao': observacao,
                **checklist_do_texto(observacao), **checklist_do_texto(pendencia),
            }
            if 'INFORMADO' in chave_nome(observacao):
                campos['plano_saude_informado'] = True
            if etapa is None:
                Etapa.objects.create(acompanhamento=acompanhamento, tipo=tipo, **campos)
                etapas_criadas += 1
            else:
                for k, v in campos.items():
                    setattr(etapa, k, v)
                etapa.save()
                atualizadas += 1
            acompanhamento._prefetched_objects_cache = {}

        for lista in existentes.values():
            for a in lista:
                a.atualizar_situacao()

    return {
        'pessoas_criadas': criados, 'etapas_criadas': etapas_criadas,
        'etapas_atualizadas': atualizadas, 'ignoradas': ignoradas,
    }


def linhas_do_xlsx(caminho) -> list:
    """Uma aba por mês: cabeçalho = linha com TIPO; colunas pelo nome (as abas variam)."""
    import openpyxl

    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    saida = []
    for ws in wb.worksheets:
        cab = None
        for r in ws.iter_rows(values_only=True):
            valores = [chave_nome(v) for v in r]
            if 'TIPO' in valores:
                cab = valores
                continue
            if not cab or not any(v not in (None, '') and str(v).strip() for v in r):
                continue

            def col(*nomes):
                for n in nomes:
                    if n in cab and cab.index(n) < len(r):
                        return r[cab.index(n)]
                return None

            i_tipo = cab.index('TIPO')
            nome = col('NOME') if 'NOME' in cab else (r[i_tipo - 1] if i_tipo > 0 else None)
            venc = col('VENCIMENTO')
            obs = ' · '.join(str(x).strip() for x in (col('OBSERVACAO'), col('PENDENCIA'), col('PLANO DE SAUDE'))
                             if x is not None and str(x).strip() not in ('', '-'))
            saida.append({
                'aba': ws.title, 'nome': nome, 'setor': col('SETOR'), 'cargo': col('CARGO'), 'tipo': col('TIPO'),
                'vencimento': venc.date().isoformat() if isinstance(venc, datetime) else venc,
                'situacao': col('SITUACAO'), 'observacao': obs,
            })
    return saida
