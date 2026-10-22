"""
Matriz de Requisitos Legais e Obrigações (planilha do SGI) dentro da Conformidade Legal.

* ``importar_planilha``: lê o .xlsx (aba com cabeçalho "Atividade") e cria/atualiza os itens, um por
  atividade — subir de novo atualiza o texto e não duplica.
* ``vincular_automatico``: liga cada atividade ao que já está cadastrado, de duas formas:
  1. lei citada na coluna de referência (Lei 12.305/2010, CONAMA 430/2011…) → a norma e os requisitos dela;
  2. assunto (resíduos, água, efluentes, emissões, ruído…) → requisitos cujo texto trata do mesmo assunto;
     atividade que fala em licença/condicionante → as licenças, outorgas e TACs vigentes.
  Cada ligação guarda o motivo; a que for tirada à mão fica marcada ``excluido`` e não volta.
* ``situacao``: o que a matriz chamava de "Situação / Última verificação / Pendências", calculado das
  verificações dos requisitos ligados e da validade das licenças.
* ``exportar_planilha``: a planilha de volta, com essas colunas preenchidas.
"""
import io
import re
import unicodedata
from datetime import date, timedelta

from django.db import transaction

from .models import MatrizItem, MatrizVinculo, MatrizVinculoNorma, Norma, PlanoAcao, Requisito

# Cabeçalhos aceitos (sem acento, minúsculo, começo do texto) → campo.
COLUNAS = [
    ('atividade', 'atividade'),
    ('obrigac', 'obrigacoes'),
    ('origem', 'referencias'),
    ('referenc', 'referencias'),
    ('exemplos', 'controles'),
    ('controle', 'controles'),
    ('evidenc', 'evidencias'),
    ('responsavel', 'responsavel_sugerido'),
    ('frequencia', 'frequencia'),
    ('prazo', 'frequencia'),
    ('pendenc', 'pendencias_manual'),
]
LIMITE_LINHAS = 500
TIPOS_LICENCA = ('LICENCA', 'OUTORGA', 'TAC')
DIAS_A_VENCER = 60


def _sem_acento(t: str) -> str:
    return unicodedata.normalize('NFD', t or '').encode('ascii', 'ignore').decode().lower().strip()


def _texto(v) -> str:
    if v is None:
        return ''
    t = str(v).strip()
    return '' if _sem_acento(t) in ('a preencher', '-', 'n/a') else t


# ── Assuntos: (rótulo, como a ATIVIDADE fala dele, como o REQUISITO fala dele) ──────────────
ASSUNTOS = [
    ('Resíduos', r'residu|\bmtr\b|pgrs|destinac', r'residu|\bmtr\b|pgrs|destinac|aterro|coleta seletiva|12\.?305|inventario de residu|cadri|logistica reversa'),
    ('Água e outorga', r'\bagua\b|outorga|captac', r'outorga|captac|recursos hidricos|\bpoco|9\.?433|hidrometro|vazao|uso da agua|dispensa de outorga'),
    ('Efluentes', r'efluent|lancamento', r'efluent|lancamento|\bete\b|caixa separadora|conama\s*n?o?\s*430|\bdbo\b|\bdqo\b|esgot|fossa|sumidouro'),
    ('Emissões e poeira', r'emiss|particulad|poeira|atmosfer', r'emiss|particulad|poeira|aspers|chamine|filtro de manga|fumaca|ringelmann|\bpts\b|qualidade do ar|atmosfer|umectac'),
    ('Ruído e vibração', r'ruido|vibrac|explosiv|desmonte', r'ruido|vibrac|sobrepress|detonac|desmonte|explosiv|sismogra|fogo|plano de fogo|nbr 9653|nbr 10151'),
    ('Recuperação de áreas', r'recupera|fechamento|encerramento|degradad', r'\bprad\b|recuperacao|degradad|fechamento|revegeta|plano de recupera|descomissionamento|estabilidade de talude'),
    ('Vegetação, APP e fauna', r'silvicult|florest|vegetac|\bapp\b|fauna|biodivers|plantio|corte', r'vegetac|\bapp\b|preservacao permanente|reserva legal|fauna|flora|florestal|supressao|reposicao florestal|12\.?651|plantio|silvicult|corte de arvore|eucalipto|pinus'),
    ('Combustíveis e químicos', r'combustiv|quimic|\boleo|tanque|vazament', r'combustiv|tanque|\bsasc\b|bacia de contenc|vazament|\boleo|derramament|posto de abastec|abastecimento|produtos? quimic|emergencia ambiental|kit de mitigac'),
    ('Transporte', r'transport', r'transport|\bmopp\b|\bciv\b|\bcipp\b|veiculo|transportador'),
    ('Monitoramento e relatórios', r'monitorament|relatori|reporte', r'relatori|monitorament|protocol|\braa\b|automonitorament|encaminhar ao|apresentar ao|enviar a fepam|laudo'),
    ('Lavra e mineração', r'minerac|lavra|mineradas|ceu aberto', r'\blavra|minerac|extracao mineral|\banm\b|\bdnpm\b|\bcava\b|bancada|frente de lavra|\bpae\b|plano de aproveitamento'),
    ('Britagem', r'britag|rebritag', r'britag|britador|rebritag|peneira|correia transportadora'),
    ('Calcário e cal', r'calcario|\bcal\b|beneficiad', r'calcin|\bforno|moagem|moinho|calcario|\bcal\b|hidratac|ensacad'),
    ('Manutenção e oficina', r'manutenc|oficina|maquinas e veiculos', r'oficina|manutenc|lavagem|lava-jato|caixa separadora|oleo usado|\boluc\b|lubrificante|1\.?362'),
]
# Só "licenciamento"/"condicionantes": "verificar necessidade de licença/autorização" (silvicultura) não é a LO.
LICENCA_NA_ATIVIDADE = r'licenciament|condicionant'
# "Lei 12.305/2010", "Lei nº 9.433/97", "Resolução CONAMA 430/2011", "Decreto 10.936/2022"
LEI_CITADA = re.compile(r'(?:lei|decreto|resoluc\w*|portaria|instruc\w* normativa|conama|consema)[^0-9]{0,25}?(\d{1,3}(?:\.\d{3})*)\s*/\s*(\d{2,4})')


def _texto_do_item(item: MatrizItem) -> str:
    # Só atividade e obrigações: quase toda linha cita "relatórios" e "licença" nos controles e nas
    # referências — contar essas colunas ligaria todas as atividades a tudo.
    return _sem_acento(' '.join([item.atividade, item.obrigacoes]))


def _texto_do_requisito(r: Requisito) -> str:
    return _sem_acento(' '.join([r.descricao, r.referencia, r.secao, r.norma.ementa, r.norma.identificacao]))


def _normas_citadas(texto: str) -> list[tuple[str, int]]:
    """[('12305', 2010), ('430', 2011)] — número sem ponto e ano com 4 dígitos."""
    saida = []
    for numero, ano in LEI_CITADA.findall(texto):
        a = int(ano)
        a = a + (1900 if a > 50 else 2000) if a < 100 else a
        saida.append((numero.replace('.', ''), a))
    return saida


def vincular_automatico(itens=None) -> dict:
    """Sugere (e grava) as ligações. Não mexe nas manuais nem traz de volta as excluídas."""
    itens = list(itens if itens is not None else MatrizItem.objects.all())
    requisitos = list(Requisito.objects.select_related('norma').filter(ativo=True).exclude(aplicabilidade='NAO_APLICAVEL'))
    textos_req = {r.id: _texto_do_requisito(r) for r in requisitos}
    normas = list(Norma.objects.all())
    novos = novos_normas = 0
    with transaction.atomic():
        for item in itens:
            texto = _texto_do_item(item)
            ja = {v.requisito_id: v for v in item.vinculos.all()}
            ja_normas = {v.norma_id: v for v in item.vinculos_normas.all()}
            sugestoes: dict[int, str] = {}
            sugestoes_normas: dict[int, str] = {}
            # 1. lei citada → a norma e os requisitos dela
            for numero, ano in _normas_citadas(_sem_acento(item.referencias + ' ' + item.obrigacoes)):
                for n in normas:
                    if re.sub(r'\D', '', n.numero or '') == numero and (n.ano == ano or not n.ano):
                        sugestoes_normas.setdefault(n.id, f'Citada na matriz: {n.identificacao}'[:200])
                        for r in requisitos:
                            if r.norma_id == n.id:
                                sugestoes.setdefault(r.id, f'Requisito de {n.identificacao}'[:200])
            # 2. assunto
            for rotulo, na_atividade, no_requisito in ASSUNTOS:
                if not re.search(na_atividade, texto):
                    continue
                for r in requisitos:
                    if re.search(no_requisito, textos_req[r.id]):
                        sugestoes.setdefault(r.id, f'Assunto: {rotulo}')
            # 3. licença/condicionante → licenças e TACs; outorga → outorgas (não revogadas)
            if re.search(LICENCA_NA_ATIVIDADE, texto):
                for n in normas:
                    if n.tipo in ('LICENCA', 'TAC') and n.situacao != 'REVOGADA':
                        sugestoes_normas.setdefault(n.id, 'Licença / condicionante da empresa')
                        # "atendimento às condicionantes": as condicionantes cadastradas da licença entram também
                        if re.search(r'condicionant', texto):
                            for r in requisitos:
                                if r.norma_id == n.id:
                                    sugestoes.setdefault(r.id, f'Condicionante de {n.identificacao}'[:200])
            if re.search(r'outorga', texto):
                for n in normas:
                    if n.tipo == 'OUTORGA' and n.situacao != 'REVOGADA':
                        sugestoes_normas.setdefault(n.id, 'Outorga de uso da água')
            for rid, motivo in sugestoes.items():
                if rid not in ja:
                    MatrizVinculo.objects.create(item=item, requisito_id=rid, automatico=True, motivo=motivo)
                    novos += 1
            for nid, motivo in sugestoes_normas.items():
                if nid not in ja_normas:
                    MatrizVinculoNorma.objects.create(item=item, norma_id=nid, automatico=True, motivo=motivo)
                    novos_normas += 1
    return {'requisitos': novos, 'normas': novos_normas}


def importar_planilha(arquivo, usuario=None) -> dict:
    """Cria/atualiza os itens a partir do .xlsx. Devolve contagens e avisos (sem gravar nada se não achar o cabeçalho)."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(arquivo, read_only=True, data_only=True)
    except Exception as exc:  # zip inválido, xls antigo, arquivo corrompido
        raise ValueError('Não consegui abrir a planilha. Envie no formato .xlsx.') from exc
    for ws in wb.worksheets:
        linhas = ws.iter_rows(values_only=True)
        for cabecalho in linhas:
            nomes = [_sem_acento(str(c or '')) for c in cabecalho]
            if any(n.startswith('atividade') for n in nomes):
                break
        else:
            continue
        mapa = {}
        for i, nome in enumerate(nomes):
            for prefixo, campo in COLUNAS:
                if nome.startswith(prefixo) and campo not in mapa.values():
                    mapa[i] = campo
                    break
        criados = atualizados = 0
        existentes = {_sem_acento(i.atividade): i for i in MatrizItem.objects.all()}
        ordem = 0
        tocados = []
        with transaction.atomic():
            for linha in linhas:
                dados = {campo: _texto(linha[i]) if i < len(linha) else '' for i, campo in mapa.items()}
                if not dados.get('atividade'):
                    continue
                ordem += 1
                if ordem > LIMITE_LINHAS:
                    break
                dados['atividade'] = dados['atividade'][:200]
                for campo in ('responsavel_sugerido', 'frequencia'):
                    dados[campo] = dados.get(campo, '')[:200]
                item = existentes.get(_sem_acento(dados['atividade']))
                if item:
                    for campo, valor in dados.items():
                        if campo == 'pendencias_manual' and not valor:
                            continue   # não apaga a pendência digitada no sistema
                        setattr(item, campo, valor)
                    item.ordem = ordem
                    item.save()
                    atualizados += 1
                else:
                    item = MatrizItem.objects.create(ordem=ordem, criado_por=usuario, **dados)
                    existentes[_sem_acento(item.atividade)] = item
                    criados += 1
                tocados.append(item)
        if not tocados:
            raise ValueError('A planilha tem o cabeçalho, mas nenhuma atividade preenchida.')
        ligacoes = vincular_automatico(tocados)
        return {'aba': ws.title, 'criados': criados, 'atualizados': atualizados, 'vinculos': ligacoes}
    raise ValueError('Não achei a linha de cabeçalho com a coluna "Atividade".')


# ── Situação ─────────────────────────────────────────────────────────────────────
ROTULOS = {
    'CONFORME': 'Conforme', 'PARCIAL': 'Parcial', 'NAO_CONFORME': 'Não conforme', 'NAO_VERIFICADO': 'Não verificado',
    'NAO_MAPEADO': 'Não mapeado', 'NAO_APLICAVEL': 'Não aplicável',
}


def situacao(item: MatrizItem, hoje: date | None = None) -> dict:
    """
    Situação calculada (e a final, que respeita a manual), índice, última verificação e pendências.
    Usa os vínculos já carregados (prefetch ``vinculos__requisito__norma`` e ``vinculos_normas__norma``).
    """
    hoje = hoje or date.today()
    reqs = [v.requisito for v in item.vinculos.all() if not v.excluido and v.requisito.ativo
            and v.requisito.aplicabilidade != 'NAO_APLICAVEL']
    normas = [v.norma for v in item.vinculos_normas.all() if not v.excluido]
    contagem = {'ATENDIDO': 0, 'PARCIAL': 0, 'NAO_ATENDIDO': 0, 'NAO_AVALIADO': 0}
    vencidos = []
    pendencias = []
    for r in reqs:
        contagem[r.situacao] = contagem.get(r.situacao, 0) + 1
        if r.situacao == 'NAO_ATENDIDO':
            pendencias.append({'tipo': 'NAO_ATENDIDO', 'texto': f'Não atendido: {r}', 'requisito': r.id})
        if r.proxima_verificacao and r.proxima_verificacao < hoje:
            vencidos.append(r)
            pendencias.append({'tipo': 'VENCIDO', 'texto': f'Verificação vencida em {r.proxima_verificacao:%d/%m/%Y}: {r}', 'requisito': r.id})
    licencas = [n for n in normas if n.tipo in TIPOS_LICENCA]
    licencas_vencidas = [n for n in licencas if n.validade and n.validade < hoje]
    licencas_a_vencer = [n for n in licencas if n.validade and hoje <= n.validade <= hoje + timedelta(days=DIAS_A_VENCER)]
    for n in licencas_vencidas:
        pendencias.append({'tipo': 'LICENCA_VENCIDA', 'texto': f'{n.identificacao} vencida em {n.validade:%d/%m/%Y}', 'norma': n.id})
    for n in licencas_a_vencer:
        pendencias.append({'tipo': 'LICENCA_A_VENCER', 'texto': f'{n.identificacao} vence em {(n.validade - hoje).days} dia(s)', 'norma': n.id})
    sem_condicionantes = bool(licencas) and not reqs and re.search(r'condicionant', _texto_do_item(item))
    if sem_condicionantes:
        pendencias.append({'tipo': 'SEM_CONDICIONANTES', 'texto': 'Condicionantes da licença ainda não cadastradas como requisitos'})
    if contagem['NAO_AVALIADO']:
        pendencias.append({'tipo': 'NAO_AVALIADO', 'texto': f"{contagem['NAO_AVALIADO']} requisito(s) ainda sem verificação"})
    planos_abertos = PlanoAcao.objects.filter(requisito__in=[r.id for r in reqs], concluido_em__isnull=True).count() if reqs else 0
    if planos_abertos:
        pendencias.append({'tipo': 'PLANO', 'texto': f'{planos_abertos} plano(s) de ação em aberto'})
    if item.pendencias_manual:
        pendencias.append({'tipo': 'MANUAL', 'texto': item.pendencias_manual})

    avaliados = contagem['ATENDIDO'] + contagem['PARCIAL'] + contagem['NAO_ATENDIDO']
    if not reqs and not normas:
        auto = 'NAO_MAPEADO'
    elif contagem['NAO_ATENDIDO'] or licencas_vencidas:
        auto = 'NAO_CONFORME'
    elif not avaliados and not licencas:
        auto = 'NAO_VERIFICADO'
    elif (reqs and contagem['ATENDIDO'] == len(reqs) and not vencidos) or (not reqs and licencas and not sem_condicionantes):
        auto = 'CONFORME'
    elif sem_condicionantes:
        auto = 'PARCIAL'
    elif not avaliados:
        auto = 'NAO_VERIFICADO'
    else:
        auto = 'PARCIAL'
    final = item.situacao_manual or auto
    datas = [r.ultima_verificacao for r in reqs if r.ultima_verificacao]
    return {
        'situacao': final, 'situacao_rotulo': ROTULOS[final], 'situacao_automatica': auto,
        'situacao_automatica_rotulo': ROTULOS[auto], 'manual': bool(item.situacao_manual),
        'requisitos': len(reqs), 'contagem': contagem, 'vencidos': len(vencidos), 'avaliados': avaliados,
        'indice': round(100 * (contagem['ATENDIDO'] + 0.5 * contagem['PARCIAL']) / avaliados, 1) if avaliados else None,
        'licencas': len(licencas), 'licencas_vencidas': len(licencas_vencidas), 'licencas_a_vencer': len(licencas_a_vencer),
        'normas': len(normas), 'planos_abertos': planos_abertos,
        'ultima_verificacao': max(datas).isoformat() if datas else None,
        'pendencias': pendencias,
    }


def queryset_itens():
    return MatrizItem.objects.prefetch_related('vinculos__requisito__norma', 'vinculos_normas__norma')


def resumo(itens=None) -> dict:
    itens = list(itens if itens is not None else queryset_itens())
    sit = [situacao(i)['situacao'] for i in itens]
    contagem = {s: sit.count(s) for s in ROTULOS}
    considerados = len(itens) - contagem['NAO_APLICAVEL']
    pontos = contagem['CONFORME'] + 0.5 * contagem['PARCIAL']
    return {
        'total': len(itens), 'contagem': contagem,
        'percentual_conforme': round(100 * contagem['CONFORME'] / considerados, 1) if considerados else None,
        'indice': round(100 * pontos / considerados, 1) if considerados else None,
        'mapeados': len(itens) - contagem['NAO_MAPEADO'],
    }


# ── Exportação ───────────────────────────────────────────────────────────────────
def exportar_planilha() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    cores = {'CONFORME': 'C6EFCE', 'PARCIAL': 'FFEB9C', 'NAO_CONFORME': 'FFC7CE', 'NAO_VERIFICADO': 'DDEBF7',
             'NAO_MAPEADO': 'EDEDED', 'NAO_APLICAVEL': 'F2F2F2'}
    wb = Workbook()
    ws = wb.active
    ws.title = 'Matriz de Requisitos'
    cab = ['Atividade', 'Obrigações ambientais aplicáveis', 'Origem / referência', 'Exemplos de atendimento / controles',
           'Evidências de atendimento', 'Responsável sugerido', 'Frequência / prazo', 'Situação', 'Última verificação',
           'Pendências / ações', 'Requisitos e licenças vinculados no Manager']
    ws.append(cab)
    for c in ws[1]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F4E78')
        c.alignment = Alignment(wrap_text=True, vertical='center')
    for item in queryset_itens():
        s = situacao(item)
        vinc = [str(v.requisito) for v in item.vinculos.all() if not v.excluido] + \
               [v.norma.identificacao for v in item.vinculos_normas.all() if not v.excluido]
        ultima = s['ultima_verificacao']
        ws.append([
            item.atividade, item.obrigacoes, item.referencias, item.controles, item.evidencias, item.responsavel_sugerido,
            item.frequencia, s['situacao_rotulo'] + (' (manual)' if s['manual'] else ''),
            date.fromisoformat(ultima).strftime('%d/%m/%Y') if ultima else '',
            '\n'.join(p['texto'] for p in s['pendencias']) or 'Sem pendências', '\n'.join(vinc[:40]),
        ])
        ws.cell(row=ws.max_row, column=8).fill = PatternFill('solid', fgColor=cores[s['situacao']])
    larguras = [28, 45, 40, 45, 40, 26, 26, 16, 14, 55, 55]
    for i, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for linha in ws.iter_rows(min_row=2):
        for c in linha:
            c.alignment = Alignment(wrap_text=True, vertical='top')
    ws.freeze_panes = 'B2'
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()
