"""Indicadores sociais (o "S" do ESG) da Gestão de Pessoas.

Junta o que já existe em quatro lugares, sem tabela nova:

- perfil e diversidade: ``management.Colaborador`` ativo (Situação ativa e sem
  demissão passada — a mesma regra de ``avaliacoes/management/vinculos.py``);
- rotatividade: ERP ``CONTRATOPESSOAL`` via ``turnover.py`` (pode estar fora do ar,
  então vem em bloco próprio, com ``disponivel``);
- absenteísmo: espelho de ponto do iPonto importado (``folha_ponto.py``);
- desenvolvimento: UNIDB (horas-homem = horas-aula × participante, a mesma conta
  dos relatórios do UNIDB) e avaliações de desempenho do ano.

As faixas seguem a GRI (405-1 diversidade, 405-2 remuneração, 401 rotatividade,
404 treinamento e avaliação), que é como relatório de sustentabilidade costuma
cobrar. Campo vazio no cadastro entra como "Não informado" e é contado à parte:
indicador de diversidade que esconde o buraco do cadastro engana quem lê.
"""
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from avaliacoes.management.models import Avaliacao, Colaborador

NAO_INFORMADO = 'Não informado'

# Cargo de liderança pelo nome: o cadastro não tem nível hierárquico.
_LIDERANCA = re.compile(
    r'\b(gerente|coordenador|coordenadora|supervisor|supervisora|encarregado|encarregada|'
    r'lider|gestor|gestora|diretor|diretora|chefe)\b'
)
APRENDIZ = ('jovem aprendiz', 'aprendiz')
ESTAGIO = ('estagiario', 'estagiaria', 'estagio')

FAIXAS_IDADE = [('Até 29 anos', 0, 29), ('30 a 50 anos', 30, 50), ('Acima de 50', 51, 200)]
FAIXAS_CASA = [('Menos de 1 ano', 0, 1), ('1 a 3 anos', 1, 3), ('3 a 5 anos', 3, 5),
               ('5 a 10 anos', 5, 10), ('Mais de 10 anos', 10, 200)]
ORDEM_INSTRUCAO = ['Fundamental Incompleto', 'Fundamental Completo', 'Médio Incompleto',
                   'Médio Completo', 'Superior Incompleto', 'Superior Completo', 'Pós-Graduação']


def _sem_acento(texto):
    return unicodedata.normalize('NFD', texto or '').encode('ascii', 'ignore').decode().lower().strip()


def _pct(parte, total):
    return round(100 * parte / total, 1) if total else None


def _anos(desde, hoje):
    if not desde:
        return None
    d = desde.date() if hasattr(desde, 'date') else desde
    return hoje.year - d.year - ((hoje.month, hoje.day) < (d.month, d.day))


def _distribuicao(contagem, total, ordem=None):
    """[{rotulo, qtd, pct}] na ordem pedida (o resto por quantidade), "Não informado" por último."""
    chaves = list(contagem)
    if ordem:
        chaves.sort(key=lambda k: (k == NAO_INFORMADO, ordem.index(k) if k in ordem else len(ordem), -contagem[k]))
    else:
        chaves.sort(key=lambda k: (k == NAO_INFORMADO, -contagem[k]))
    return [{'rotulo': k, 'qtd': contagem[k], 'pct': _pct(contagem[k], total)} for k in chaves]


def _genero(c):
    g = _sem_acento(c.genero)
    if g.startswith('fem'):
        return 'Feminino'
    if g.startswith('masc'):
        return 'Masculino'
    return NAO_INFORMADO


def _texto(v):
    v = (v or '').strip()
    return v or NAO_INFORMADO


def _q_ativo():
    agora = timezone.now()
    # Filial desativada (Filial.ativa, migration 0012) sai do quadro inteiro, não só
    # da tabela por unidade: quem ainda aparece lá é cadastro a revisar.
    # Situação ativa no cadastro (05/10/2026) + sem demissão passada + filial ativa.
    return Q(situacao=True) & (Q(data_demissao__isnull=True) | Q(data_demissao__gt=agora)) & ~Q(filial__ativa=False)


def _faixa_idade(c, hoje):
    idade = _anos(c.data_nascimento, hoje)
    return next((r for r, a, b in FAIXAS_IDADE if idade is not None and a <= idade <= b), NAO_INFORMADO)


def _faixa_casa(c, hoje):
    if not c.data_admissao:
        return NAO_INFORMADO
    d = c.data_admissao.date() if hasattr(c.data_admissao, 'date') else c.data_admissao
    anos = (hoje - d).days / 365.25
    return next((r for r, a, b in FAIXAS_CASA if a <= anos < b), NAO_INFORMADO)


def _raca(c):
    return NAO_INFORMADO if _sem_acento(c.raca) in ('', 'nao informado') else c.raca.strip()


def _lider(c):
    return bool(c.cargo_id and _LIDERANCA.search(_sem_acento(c.cargo.nome)))


def perfil(hoje):
    ativos = list(
        Colaborador.objects.filter(_q_ativo()).select_related('cargo', 'filial', 'empresa')
    )
    total = len(ativos)

    generos = Counter(_genero(c) for c in ativos)
    mulheres = generos.get('Feminino', 0)

    lideres = [c for c in ativos if _lider(c)]
    mulheres_lideranca = sum(1 for c in lideres if _genero(c) == 'Feminino')

    idades = Counter(_faixa_idade(c, hoje) for c in ativos)

    casa, anos_casa = Counter(), []
    for c in ativos:
        if not c.data_admissao:
            casa[NAO_INFORMADO] += 1
            continue
        d = c.data_admissao.date() if hasattr(c.data_admissao, 'date') else c.data_admissao
        anos = (hoje - d).days / 365.25
        anos_casa.append(anos)
        casa[next(r for r, a, b in FAIXAS_CASA if a <= anos < b)] += 1

    contratos = Counter(_texto(c.tipocontrato) for c in ativos)
    aprendizes = sum(1 for c in ativos if _sem_acento(c.tipocontrato) in APRENDIZ)
    estagiarios = sum(1 for c in ativos if _sem_acento(c.tipocontrato) in ESTAGIO)

    # Por unidade: headcount e participação feminina (onde a diversidade está ou não).
    por_unidade = defaultdict(Counter)
    for c in ativos:
        unidade = c.filial.nome if c.filial_id else NAO_INFORMADO
        por_unidade[unidade]['total'] += 1
        por_unidade[unidade][_genero(c)] += 1
    unidades = sorted(
        (
            {'unidade': u, 'total': v['total'], 'mulheres': v['Feminino'], 'homens': v['Masculino'],
             'pct_mulheres': _pct(v['Feminino'], v['total'])}
            for u, v in por_unidade.items()
        ),
        key=lambda x: -x['total'],
    )

    campos = {
        'genero': sum(1 for c in ativos if _genero(c) == NAO_INFORMADO),
        'raca': sum(1 for c in ativos if not (c.raca or '').strip() or _sem_acento(c.raca) == 'nao informado'),
        'nascimento': sum(1 for c in ativos if not c.data_nascimento),
        'instrucao': sum(1 for c in ativos if not (c.instrucao or '').strip()),
        'admissao': sum(1 for c in ativos if not c.data_admissao),
        'salario': sum(1 for c in ativos if not c.salario),
    }

    return ativos, {
        'headcount': total,
        'mulheres': mulheres,
        'pct_mulheres': _pct(mulheres, total),
        'lideranca': len(lideres),
        'mulheres_lideranca': mulheres_lideranca,
        'pct_mulheres_lideranca': _pct(mulheres_lideranca, len(lideres)),
        'aprendizes': aprendizes,
        'pct_aprendizes': _pct(aprendizes, total),
        'estagiarios': estagiarios,
        'tempo_casa_medio': round(sum(anos_casa) / len(anos_casa), 1) if anos_casa else None,
        'genero': _distribuicao(generos, total, ['Feminino', 'Masculino']),
        'raca': _distribuicao(Counter(_raca(c) for c in ativos), total),
        'idade': _distribuicao(idades, total, [r for r, _, _ in FAIXAS_IDADE]),
        'tempo_casa': _distribuicao(casa, total, [r for r, _, _ in FAIXAS_CASA]),
        'instrucao': _distribuicao(Counter(_texto(c.instrucao) for c in ativos), total, ORDEM_INSTRUCAO),
        'contrato': _distribuicao(contratos, total),
        'unidades': unidades,
        'cadastro_incompleto': {k: {'qtd': v, 'pct': _pct(v, total)} for k, v in campos.items()},
    }


# Grupo com menos gente que isso não mostra média: com 1 ou 2 pessoas a "média" é o
# salário de alguém identificável.
MINIMO_GRUPO_SALARIO = 3


def _mediana(v):
    v = sorted(v)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def salario_por_perfil(ativos, hoje):
    """Salário médio e mediano por gênero, raça, idade, escolaridade, casa, contrato, unidade e liderança."""
    dimensoes = {
        'genero': ('Gênero', lambda c: _genero(c), ['Feminino', 'Masculino']),
        'raca': ('Raça / cor', _raca, None),
        'idade': ('Faixa etária', lambda c: _faixa_idade(c, hoje), [r for r, _, _ in FAIXAS_IDADE]),
        'instrucao': ('Escolaridade', lambda c: _texto(c.instrucao), ORDEM_INSTRUCAO),
        'tempo_casa': ('Tempo de casa', lambda c: _faixa_casa(c, hoje), [r for r, _, _ in FAIXAS_CASA]),
        'contrato': ('Tipo de contrato', lambda c: _texto(c.tipocontrato), None),
        'unidade': ('Unidade', lambda c: c.filial.nome if c.filial_id else NAO_INFORMADO, None),
        'lideranca': ('Liderança', lambda c: 'Liderança' if _lider(c) else 'Demais cargos', ['Liderança', 'Demais cargos']),
    }
    com_salario = [c for c in ativos if c.salario]
    resultado = []
    for chave, (rotulo, classificar, ordem) in dimensoes.items():
        grupos = defaultdict(list)
        for c in com_salario:
            grupos[classificar(c)].append(float(c.salario))
        nomes = list(grupos)
        if ordem:
            nomes.sort(key=lambda k: (k == NAO_INFORMADO, ordem.index(k) if k in ordem else len(ordem), -len(grupos[k])))
        else:
            nomes.sort(key=lambda k: (k == NAO_INFORMADO, -(sum(grupos[k]) / len(grupos[k]))))
        linhas = []
        for nome in nomes:
            v = grupos[nome]
            pequeno = len(v) < MINIMO_GRUPO_SALARIO
            linhas.append({
                'rotulo': nome,
                'qtd': len(v),
                'media': None if pequeno else round(sum(v) / len(v), 2),
                'mediana': None if pequeno else round(_mediana(v), 2),
                'oculto': pequeno,
            })
        resultado.append({'chave': chave, 'rotulo': rotulo, 'grupos': linhas})
    return {
        'pessoas_consideradas': len(com_salario),
        'media_geral': round(sum(float(c.salario) for c in com_salario) / len(com_salario), 2) if com_salario else None,
        'minimo_grupo': MINIMO_GRUPO_SALARIO,
        'dimensoes': resultado,
    }


def equidade_salarial(ativos):
    """
    Razão salário médio mulheres ÷ homens (GRI 405-2).

    A razão geral mistura cargos diferentes (há mais homens na operação, por exemplo);
    a "por cargo" compara só dentro de cargos que têm os dois gêneros e pondera pelo
    número de pessoas do cargo — é a leitura que mede diferença de pagamento.
    """
    com_salario = [c for c in ativos if c.salario and _genero(c) != NAO_INFORMADO]
    por_genero = defaultdict(list)
    por_cargo = defaultdict(lambda: defaultdict(list))
    for c in com_salario:
        por_genero[_genero(c)].append(float(c.salario))
        if c.cargo_id:
            por_cargo[c.cargo.nome][_genero(c)].append(float(c.salario))

    def media(v):
        return sum(v) / len(v) if v else None

    mf, mm = media(por_genero['Feminino']), media(por_genero['Masculino'])
    soma_pesos = soma_razoes = 0
    cargos = []
    for nome, g in por_cargo.items():
        if g['Feminino'] and g['Masculino']:
            razao = media(g['Feminino']) / media(g['Masculino'])
            peso = len(g['Feminino']) + len(g['Masculino'])
            soma_razoes += razao * peso
            soma_pesos += peso
            cargos.append({'cargo': nome, 'mulheres': len(g['Feminino']), 'homens': len(g['Masculino']),
                           'razao': round(razao, 3)})
    cargos.sort(key=lambda x: x['razao'])
    return {
        'pessoas_consideradas': len(com_salario),
        'razao_geral': round(mf / mm, 3) if mf and mm else None,
        'razao_por_cargo': round(soma_razoes / soma_pesos, 3) if soma_pesos else None,
        'cargos_comparados': len(cargos),
        # Os cargos com maior diferença primeiro: é onde o RH precisa olhar.
        'cargos': cargos[:15],
    }


def desenvolvimento(ativos, ano):
    """Horas de treinamento (UNIDB) e cobertura da avaliação de desempenho no ano (GRI 404)."""
    from unidb.models import Matricula

    total = len(ativos)
    ativos_ids = {c.pk for c in ativos}
    genero_de = {c.pk: _genero(c) for c in ativos}
    headcount_genero = Counter(genero_de.values())

    matriculas = (
        Matricula.objects
        .exclude(situacao='DESISTENTE')
        .filter(Q(turma__data_inicial__year=ano) | Q(turma__data_inicial__isnull=True, turma__data_final__year=ano))
        .select_related('turma', 'aluno')
    )
    horas_total = 0.0
    horas_genero = Counter()
    treinados = set()
    participacoes = 0
    # O vínculo Aluno.colaborador quase nunca foi preenchido na importação da planilha:
    # sem o nome como reserva, "% do quadro treinado" saía 0 com horas lançadas.
    por_nome = {}
    for c in ativos:
        por_nome.setdefault(' '.join(_sem_acento(c.nome).split()), c.pk)

    for m in matriculas:
        horas = float(m.turma.horas_aula or 0)
        horas_total += horas
        participacoes += 1
        col = m.aluno.colaborador_id
        if col not in ativos_ids:
            col = por_nome.get(' '.join(_sem_acento(m.aluno.nome).split()))
        if col in ativos_ids:
            treinados.add(col)
            horas_genero[genero_de[col]] += horas

    avaliados = set(
        Avaliacao.objects.filter(create_at__year=ano, avaliado_id__in=ativos_ids)
        .values_list('avaliado_id', flat=True)
    )
    avaliados_genero = Counter(genero_de[i] for i in avaliados)

    return {
        'ano': ano,
        'horas_total': round(horas_total, 1),
        'participacoes': participacoes,
        'horas_por_colaborador': round(horas_total / total, 1) if total else None,
        'horas_por_genero': {
            g: round(horas_genero[g] / headcount_genero[g], 1) if headcount_genero[g] else None
            for g in ('Feminino', 'Masculino')
        },
        'colaboradores_treinados': len(treinados),
        'pct_treinados': _pct(len(treinados), total),
        'colaboradores_avaliados': len(avaliados),
        'pct_avaliados': _pct(len(avaliados), total),
        'pct_avaliados_genero': {
            g: _pct(avaliados_genero[g], headcount_genero[g]) for g in ('Feminino', 'Masculino')
        },
    }


def rotatividade(ano):
    """Turnover do ERP. Fica em cache por 30 min: a consulta ao SQL Server é a parte lenta."""
    chave = f'indicadores_sociais_turnover_{ano}_{date.today().isoformat()}'
    dados = cache.get(chave)
    if dados is None:
        from .turnover import apurar_ano, carregar_contratos
        try:
            contratos = carregar_contratos()
        except Exception as erro:  # ERP fora do ar não pode derrubar a dash inteira
            return {'disponivel': False, 'motivo': f'Não foi possível consultar o ERP: {erro}'}
        anos = [apurar_ano(contratos, a) for a in (ano - 1, ano)]
        dados = {
            'disponivel': True,
            'fonte': 'ERP · CONTRATOPESSOAL (empregados CLT)',
            'anos': [
                {k: a[k] for k in ('ano', 'admissoes', 'desligamentos', 'efetivo_medio',
                                   'turnover', 'turnover_desligamento', 'media_mensal')}
                for a in anos
            ],
            'meses': [{'mes': m['rotulo'], 'turnover': m['turnover'], 'admissoes': m['admissoes'],
                       'desligamentos': m['desligamentos']} for m in anos[-1]['meses']],
        }
        cache.set(chave, dados, 60 * 30)
    return dados


def absenteismo():
    from .folha_ponto import apurar_do_banco
    try:
        a = apurar_do_banco()
    except Exception as erro:
        return {'disponivel': False, 'motivo': str(erro)}
    if not a.get('disponivel'):
        return {'disponivel': False, 'motivo': a.get('motivo') or 'Nenhuma competência importada.'}
    return {
        'disponivel': True,
        'indice': a.get('indice'),
        'rotulo': a.get('indice_principal_rotulo'),
        'periodo': a.get('periodo'),
        'competencias': [{'rotulo': c.get('rotulo'), 'indice': c.get('indice')} for c in a.get('competencias', [])],
    }


def apurar(ano=None):
    hoje = timezone.localdate()
    ano = ano or hoje.year
    ativos, dados_perfil = perfil(hoje)
    return {
        'gerado_em': timezone.now().isoformat(),
        'ano': ano,
        'perfil': dados_perfil,
        'equidade': equidade_salarial(ativos),
        'salario_por_perfil': salario_por_perfil(ativos, hoje),
        'desenvolvimento': desenvolvimento(ativos, ano),
        'rotatividade': rotatividade(ano),
        'absenteismo': absenteismo(),
    }
