"""
Importação em lote dos equipamentos do SGA (27/11/2026).

O tipo de vistoria sai do prefixo da TAG do SGA (VEC-PC = pá carregadeira, VEC-EH = escavadeira…).
Só entram os que têm ficha na planilha de vistoria; os demais (veículos leves, munck, guindaste,
trator, ônibus, reboque, sonda, rompedor) voltam na lista "sem ficha" para o GEO decidir.

O SGA não tem setor nem gerente do equipamento (o centro de custo é o próprio equipamento), então
eles entram no setor "A definir" da unidade (FCB, ou ATM quando o SGA indica a filial ATM) e sem
gerente — o GEO ajusta em Cadastros → Equipamentos.
"""
from django.db import transaction

from . import servicos
from .models import Equipamento, Setor, TipoEquipamento, Unidade

SETOR_PADRAO = ('AD', 'A definir')


def ignorar(e: dict) -> str | None:
    tag, nome = (e.get('tag') or '').upper(), (e.get('nome') or '').upper()
    if 'LIMPEZA' in tag:
        return 'centro de custo de limpeza, não é equipamento'
    if tag.endswith('-99') or 'TERCEIRO' in nome:
        return 'equipamento de terceiros'
    return None


def sugerir_tipo(e: dict) -> str | None:
    """Código do TipoEquipamento (carga da planilha) para o equipamento do SGA, ou None se não há ficha."""
    tag, nome = (e.get('tag') or '').upper(), (e.get('nome') or '').upper()
    prefixos = {'VEC-MC': 'MINI-CARREGADEIRA', 'VEC-PC': 'CARREGADEIRA', 'VEC-EH': 'ESCAVADEIRA', 'VEC-PF': 'PERFURATRIZ',
                'VEC-EC': 'EMPILHADEIRA-2.0', 'VEC-PT': 'PT-02', 'VEC-CR': 'CAM-BITRUCK'}
    for p, codigo in prefixos.items():
        if tag.startswith(p + '-'):
            return codigo
    if tag.startswith('VEC-CS-'):
        if 'PIPA' in nome:
            return 'PIPA'
        if 'COMBOIO' in nome:
            return 'COMBOIO'
        return 'CAM-BITRUCK'
    if tag.startswith('VEC-CF-'):
        return 'CAM-RK' if ' RK' in nome else 'CAM-BITRUCK'
    if tag.startswith('VEC-CM-') and 'RODOVIARIO' in nome:
        return 'CAM-BITRUCK'
    return None


def unidade_sugerida(e: dict) -> str:
    texto = f"{e.get('nome') or ''} {e.get('centro_custo_nome') or ''}".upper()
    return 'ATM' if 'ATM' in texto else 'FCB'


def planejar(equipamentos_sga: list[dict]) -> dict:
    """Prévia: o que entra (com tipo), o que já existe, o que fica de fora e por quê."""
    tipos = {t.codigo: t for t in TipoEquipamento.objects.filter(ativo=True)}
    ja_cod = set(Equipamento.objects.exclude(sga_codigo=None).values_list('sga_codigo', flat=True))
    ja_tag = set(Equipamento.objects.values_list('tag', flat=True))
    entrar, existentes, sem_ficha, ignorados, vistos = [], [], [], [], set()
    for e in sorted(equipamentos_sga, key=lambda x: (x.get('tag') or '')):
        tag = (e.get('tag') or str(e['cod'])).strip().upper()[:30]
        linha = {'cod': e['cod'], 'tag': tag, 'descricao': e.get('descricao') or e.get('nome') or '', 'placa': e.get('placa') or '',
                 'tipo_sga': e.get('tipo_nome') or ''}
        motivo = ignorar(e)
        if motivo:
            ignorados.append({**linha, 'motivo': motivo})
            continue
        codigo = sugerir_tipo(e)
        if not codigo or codigo not in tipos:
            if e.get('abastece') or codigo:
                sem_ficha.append(linha)
            continue
        if e['cod'] in ja_cod or tag in ja_tag:
            existentes.append(linha)
            continue
        if tag in vistos:
            ignorados.append({**linha, 'motivo': 'TAG repetida no SGA'})
            continue
        vistos.add(tag)
        entrar.append({**linha, 'tipo': codigo, 'tipo_descricao': tipos[codigo].descricao, 'unidade': unidade_sugerida(e)})
    return {'entrar': entrar, 'existentes': existentes, 'sem_ficha': sem_ficha, 'ignorados': ignorados}


@transaction.atomic
def importar(equipamentos_sga: list[dict], usuario=None, periodicidade: str = 'MENSAL') -> dict:
    plano = planejar(equipamentos_sga)
    tipos = {t.codigo: t for t in TipoEquipamento.objects.all()}
    unidades, setores = {}, {}
    criados = []
    for l in plano['entrar']:
        sigla = l['unidade']
        if sigla not in unidades:
            unidades[sigla], _ = Unidade.objects.get_or_create(sigla=sigla, defaults={'nome': sigla})
            setores[sigla], _ = Setor.objects.get_or_create(unidade=unidades[sigla], codigo=SETOR_PADRAO[0],
                                                            defaults={'nome': SETOR_PADRAO[1]})
        eq = Equipamento.objects.create(
            tag=l['tag'], descricao=l['descricao'][:160], placa=(l['placa'] or '')[:10], tipo=tipos[l['tipo']],
            unidade=unidades[sigla], setor=setores[sigla], periodicidade=periodicidade, sga_codigo=l['cod'])
        servicos.registrar_vinculo(eq, usuario)
        servicos.sincronizar_programa(eq, usuario)
        criados.append(eq.tag)
    if criados:
        servicos.auditar(usuario, 'importar_sga', 'equipamento', '', f'{len(criados)} equipamentos do SGA (lote automático)',
                         tags=criados)
    plano['criados'] = criados
    return plano
