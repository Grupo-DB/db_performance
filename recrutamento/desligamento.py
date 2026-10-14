"""
Desligamentos: justificativa do gestor e entrevista de desligamento do funcionário.

Os dois formulários vieram do Google Forms (2025–2026) e são preenchidos pelo RH. As
perguntas ficam AQUI, numa lista só, e a tela as recebe por `GET desligamentos/perguntas/`
— trocar uma pergunta não exige mexer no front.

Quase tudo é texto livre. Para virar indicador, a IA (o mesmo Claude do módulo de
Conformidade Legal, no Microsoft Foundry) classifica as respostas abertas em categorias
fechadas — "Sim / Em parte / Não", "Positiva / Neutra / Negativa", motivo principal. A
classificação aparece na tela e pode ser corrigida pelo RH; corrigida, a IA não a
sobrescreve mais.
"""
import difflib
import json
import logging
import re
import unicodedata
from datetime import date

logger = logging.getLogger(__name__)

# ── Perguntas ─────────────────────────────────────────────────────────────
# tipo: 'texto' (resposta aberta) ou 'multipla' (opções + "Outro" livre). `classe`:
# qual classificação a IA faz desta resposta (ver CLASSES). As chaves são as do JSON
# `respostas` e não mudam — renomear a pergunta é seguro, renomear a chave não.

# Opções vistas nas respostas do Google Forms (as que aparecem marcadas junto com outras).
# "Corte de gastos" no do funcionário era digitado no "Outro" (3 grafias), mas é o motivo
# mais comum das saídas involuntárias — vira opção daqui para frente.
OPCOES_FATORES_GESTOR = ['Cortes orçamentários', 'Conduta/comportamento', 'Desempenho abaixo do esperado',
                         'Reestruturação organizacional', 'Inadequação cultural']
OPCOES_MOTIVOS_FUNCIONARIO = ['Salário', 'Benefícios', 'Falta de reconhecimento', 'Oportunidade externa',
                              'Desenvolvimento profissional', 'Gestão/Liderança', 'Ambiente de Trabalho',
                              'Corte de gastos']

PERGUNTAS = {
    'GESTOR': [
        {'chave': 'fatores', 'texto': 'Quais foram os principais fatores que levaram ao desligamento do colaborador?',
         'tipo': 'multipla', 'opcoes': OPCOES_FATORES_GESTOR, 'classe': 'fator_principal'},
        {'chave': 'ciencia_melhoria', 'texto': 'O colaborador teve ciência prévia dos pontos de melhoria esperados?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'feedbacks_formais', 'texto': 'O colaborador recebeu feedbacks formais antes do desligamento?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'pdi', 'texto': 'Ele participou de um PDI (Plano de Desenvolvimento Individual)? Qual foi o resultado?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'desafios', 'texto': 'Quais foram os principais desafios enfrentados por ele?', 'tipo': 'texto'},
        {'chave': 'relacao_equipe', 'texto': 'Como era a relação do colaborador com a equipe?', 'tipo': 'texto',
         'classe': 'avaliacao'},
        {'chave': 'relacao_lideranca', 'texto': 'E com a liderança?', 'tipo': 'texto', 'classe': 'avaliacao'},
        {'chave': 'pontos_fortes', 'texto': 'Quais foram os pontos fortes do colaborador', 'tipo': 'texto'},
        {'chave': 'recolocacao_interna', 'texto': 'Havia potencial para recolocação interna? Isso foi considerado?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'o_que_diferente', 'texto': 'O que poderia ter sido feito diferente para evitar o desligamento',
         'tipo': 'texto', 'classe': 'evitavel'},
        {'chave': 'aprendizado_gestor', 'texto': 'Há algum aprendizado que você, como gestor, leva desse caso?',
         'tipo': 'texto'},
        {'chave': 'recomendacao_contratacao',
         'texto': 'Alguma recomendação para futuros processos de contratação ou integração?', 'tipo': 'texto'},
    ],
    'FUNCIONARIO': [
        {'chave': 'motivos', 'texto': 'Quais foram os principais motivos que o levaram a deixar a empresa?',
         'tipo': 'multipla', 'opcoes': OPCOES_MOTIVOS_FUNCIONARIO, 'classe': 'motivo_principal'},
        {'chave': 'mais_pesou', 'texto': 'O que mais pesou na sua decisão?', 'tipo': 'texto'},
        {'chave': 'relacao_empresa', 'texto': 'Como você avalia seu relacionamento com sua empresa?', 'tipo': 'texto',
         'classe': 'avaliacao'},
        {'chave': 'relacao_gestor', 'texto': 'Como era seu relacionamento com seu(s) gestor(es)?', 'tipo': 'texto',
         'classe': 'avaliacao'},
        {'chave': 'valorizado', 'texto': 'Sentia-se valorizado e respeitado no ambiente de trabalho?', 'tipo': 'texto',
         'classe': 'sim_nao'},
        {'chave': 'cultura_alinhada', 'texto': 'A cultura da empresa estava alinhada com seus valores pessoais?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'ser_voce_mesmo', 'texto': 'Você sentia que podia ser você mesmo no ambiente de trabalho?',
         'tipo': 'texto', 'classe': 'sim_nao'},
        {'chave': 'crescimento', 'texto': 'Houve oportunidades reais de crescimento na empresa?', 'tipo': 'texto',
         'classe': 'sim_nao'},
        {'chave': 'reconhecido', 'texto': 'Você se sentia reconhecido(a) pelo seu trabalho?', 'tipo': 'texto',
         'classe': 'sim_nao'},
        {'chave': 'comunicacao_clara', 'texto': 'A comunicação da liderança era clara e transparente?', 'tipo': 'texto',
         'classe': 'sim_nao'},
        {'chave': 'estilo_gestao', 'texto': 'Como avalia o estilo de gestão da sua liderança direta?', 'tipo': 'texto',
         'classe': 'avaliacao'},
        {'chave': 'sugestao_melhoria',
         'texto': 'O que a empresa poderia fazer para melhorar a experiência dos colaboradores?', 'tipo': 'texto'},
        {'chave': 'recomendaria', 'texto': 'Você recomendaria a empresa para outras pessoas? Por quê?', 'tipo': 'texto',
         'classe': 'sim_nao'},
        {'chave': 'mensagem_final', 'texto': 'Deseja deixar alguma mensagem final?', 'tipo': 'texto'},
    ],
}

# Categorias de cada classe de classificação (valor, rótulo).
CLASSES = {
    'sim_nao': [('SIM', 'Sim'), ('PARCIAL', 'Em parte'), ('NAO', 'Não'), ('SEM_RESPOSTA', 'Sem resposta')],
    'avaliacao': [('POSITIVA', 'Positiva'), ('NEUTRA', 'Neutra'), ('NEGATIVA', 'Negativa'),
                  ('SEM_RESPOSTA', 'Sem resposta')],
    'evitavel': [('SIM', 'Era evitável'), ('TALVEZ', 'Talvez'), ('NAO', 'Não era evitável'),
                 ('SEM_RESPOSTA', 'Sem resposta')],
    'fator_principal': [(o, o) for o in OPCOES_FATORES_GESTOR]
                       + [('Pedido do colaborador', 'Pedido do colaborador'), ('Outro', 'Outro')],
    'motivo_principal': [(o, o) for o in OPCOES_MOTIVOS_FUNCIONARIO]
                        + [('Logística/distância', 'Logística/distância'),
                           ('Motivos pessoais/família', 'Motivos pessoais/família'), ('Saúde', 'Saúde'),
                           ('Conduta/desempenho', 'Conduta/desempenho'), ('Outro', 'Outro')],
}


def perguntas_classificadas(formulario: str) -> list[dict]:
    return [p for p in PERGUNTAS[formulario] if p.get('classe')]


# ── Texto ─────────────────────────────────────────────────────────────────
def normalizar(texto: str) -> str:
    sem = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode()
    return ' '.join(sem.lower().replace('.', ' ').split())


def resposta_vazia(valor) -> bool:
    """'-', '----', '.' e afins contam como não respondido (o Google Forms exigia algo)."""
    if isinstance(valor, list):
        return not any(not resposta_vazia(v) for v in valor)
    return not re.sub(r'[\s\-_.–—]', '', str(valor or ''))


def separar_multipla(texto: str, opcoes: list[str]) -> list[str]:
    """'Salário;Falta de reconhecimento;Outro motivo' → lista, com as opções do formulário
    grafadas como no formulário (o Forms gravou "CORTE DE GASTOS" e "corte de gastos")."""
    por_chave = {normalizar(o): o for o in opcoes}
    itens = []
    for parte in (texto or '').split(';'):
        parte = parte.strip()
        if parte and not resposta_vazia(parte):
            itens.append(por_chave.get(normalizar(parte), parte))
    return itens


# ── Tempo de casa ─────────────────────────────────────────────────────────
_NUMEROS = {'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4, 'cinco': 5, 'seis': 6, 'sete': 7,
            'oito': 8, 'nove': 9, 'dez': 10, 'onze': 11, 'doze': 12}


def meses_de_texto(texto: str) -> int | None:
    """'1 ano e 3 meses' → 15; '26 dias' → 0; '2 meses e pouco' → 2. None se não der para ler."""
    t = normalizar(texto)
    for palavra, n in _NUMEROS.items():
        t = re.sub(rf'\b{palavra}\b', str(n), t)
    anos = re.search(r'(\d+(?:,\d+)?)\s*anos?', t)
    meses = re.search(r'(\d+)\s*m[eê]s(?:es)?', t)
    dias = re.search(r'(\d+)\s*dias?', t)
    if not (anos or meses or dias):
        return None
    total = 0.0
    if anos:
        total += float(anos.group(1).replace(',', '.')) * 12
        if 'e meio' in t[anos.end():anos.end() + 10]:
            total += 6
    if meses:
        total += int(meses.group(1))
    return int(total)


def meses_entre(inicio: date, fim: date) -> int:
    return max(0, (fim.year - inicio.year) * 12 + (fim.month - inicio.month) - (1 if fim.day < inicio.day else 0))


FAIXAS_TEMPO = [(3, 'Até 3 meses'), (12, '3 meses a 1 ano'), (36, '1 a 3 anos'), (60, '3 a 5 anos'),
                (None, 'Mais de 5 anos')]


def faixa_tempo(meses: int | None) -> str | None:
    if meses is None:
        return None
    for limite, rotulo in FAIXAS_TEMPO:
        if limite is None or meses < limite:
            return rotulo
    return None


# ── Colaborador pelo nome ─────────────────────────────────────────────────
def casar_colaborador(nome: str, colaboradores: list) -> tuple:
    """
    (colaborador, como) para um nome digitado. Ordem: igual (sem acento/maiúsculas);
    todas as palavras do nome digitado contidas no do cadastro, se só um casar ("Cleibe
    Aglaer" → "Cleibe Aglaer Marques Lima"); grafia parecida (≥ 0,88: "Wersley"/"Wesrley").
    Medido nas respostas antigas: 119 de 123 casaram.
    """
    alvo = normalizar(nome)
    if not alvo:
        return None, ''
    por_nome = {}
    for c in colaboradores:
        por_nome.setdefault(normalizar(c.nome), []).append(c)
    if alvo in por_nome:
        return por_nome[alvo][0], 'exato'
    palavras = alvo.split()
    contidos = [c for c in colaboradores if all(p in normalizar(c.nome).split() for p in palavras)]
    if len(contidos) == 1:
        return contidos[0], 'contido'
    parecido = difflib.get_close_matches(alvo, list(por_nome), n=1, cutoff=0.88)
    if parecido:
        return por_nome[parecido[0]][0], 'aproximado'
    return None, ''


# ── Classificação pela IA ─────────────────────────────────────────────────
SISTEMA = """Você classifica respostas de formulários de desligamento de uma empresa brasileira
(mineração de calcário, cal e argamassas). As respostas foram anotadas pelo RH, muitas vezes em 3ª
pessoa ("Acredita que sim"). Classifique cada resposta só pelo que ela diz; resposta vazia, "-" ou
sem conteúdo → SEM_RESPOSTA. "Às vezes", "mais ou menos", "alguns sim, outros não" → PARCIAL.
Para o motivo/fator principal escolha a categoria que melhor resume o que pesou mais, considerando
as opções marcadas e o texto livre."""


def _esquema(formulario: str) -> dict:
    props = {}
    for p in perguntas_classificadas(formulario):
        props[p['chave']] = {'type': 'string', 'enum': [v for v, _ in CLASSES[p['classe']]]}
    return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}


def classificar(formulario: str, respostas: dict) -> dict:
    """{chave: categoria} para as perguntas classificáveis. Levanta exceção se a IA falhar."""
    from conformidadeLegal import ia

    linhas = []
    for p in PERGUNTAS[formulario]:
        v = respostas.get(p['chave'])
        if isinstance(v, list):
            v = '; '.join(v)
        alvo = f" [classificar em: {', '.join(x for x, _ in CLASSES[p['classe']])}]" if p.get('classe') else ''
        linhas.append(f'- {p["chave"]}: {p["texto"]}{alvo}\n  Resposta: {v or "(vazia)"}')
    tipo = 'justificativa do GESTOR sobre o desligamento' if formulario == 'GESTOR' \
        else 'entrevista de desligamento com o FUNCIONÁRIO'
    resposta = ia._cliente().messages.create(
        model=ia.modelo(),
        max_tokens=3000,
        system=SISTEMA,
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': _esquema(formulario)}},
        messages=[{'role': 'user', 'content': f'Formulário: {tipo}.\n\n' + '\n'.join(linhas)}],
    )
    if resposta.stop_reason == 'refusal':
        raise RuntimeError('A IA recusou classificar este formulário.')
    texto = next((b.text for b in resposta.content if b.type == 'text'), '')
    dados = json.loads(texto)
    validos = {p['chave']: {v for v, _ in CLASSES[p['classe']]} for p in perguntas_classificadas(formulario)}
    return {k: v for k, v in dados.items() if k in validos and v in validos[k]}


# ── Indicadores ───────────────────────────────────────────────────────────
ROTULO_TIPO = {'VOLUNTARIO': 'Voluntário', 'INVOLUNTARIO': 'Involuntário', 'ACORDO': 'Acordo mútuo', '': 'Não informado'}


def _contar(valores) -> list[dict]:
    c = {}
    for v in valores:
        if v:
            c[v] = c.get(v, 0) + 1
    return [{'rotulo': k, 'total': n} for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]


def indicadores(desligamentos) -> dict:
    """
    Números da aba Indicadores. `desligamentos`: lista de Desligamento com `formularios`
    pré-carregados. Percepções contam só quem respondeu (SEM_RESPOSTA fica de fora do %).
    """
    lista = list(desligamentos)
    total = len(lista)
    form = lambda d, tipo: next((f for f in d.formularios.all() if f.formulario == tipo), None)  # noqa: E731

    meses = [d.tempo_casa_meses for d in lista]
    meses_validos = [m for m in meses if m is not None]
    por_tipo = {t: sum(1 for d in lista if d.tipo == t) for t in ('VOLUNTARIO', 'INVOLUNTARIO', 'ACORDO')}

    por_mes = {}
    for d in lista:
        chave = d.data_desligamento.strftime('%Y-%m')
        linha = por_mes.setdefault(chave, {'mes': chave, 'VOLUNTARIO': 0, 'INVOLUNTARIO': 0, 'ACORDO': 0, 'total': 0})
        if d.tipo in linha:
            linha[d.tipo] += 1
        linha['total'] += 1

    com_gestor = [d for d in lista if form(d, 'GESTOR')]
    com_func = [d for d in lista if form(d, 'FUNCIONARIO')]

    def percepcoes(formulario):
        saida = []
        for p in perguntas_classificadas(formulario):
            if p['classe'] not in ('sim_nao', 'avaliacao', 'evitavel'):
                continue
            contagem = {v: 0 for v, _ in CLASSES[p['classe']] if v != 'SEM_RESPOSTA'}
            for d in lista:
                f = form(d, formulario)
                v = (f.classificacao or {}).get(p['chave']) if f else None
                if v in contagem:
                    contagem[v] += 1
            respondidas = sum(contagem.values())
            saida.append({'chave': p['chave'], 'pergunta': p['texto'], 'classe': p['classe'],
                          'respondidas': respondidas, 'contagem': contagem})
        return saida

    def marcadas(formulario, chave, opcoes):
        valores = []
        for d in lista:
            f = form(d, formulario)
            for item in (f.respostas.get(chave) or []) if f else []:
                valores.append(item if item in opcoes else 'Outro (texto livre)')
        return _contar(valores)

    def principal(formulario, chave):
        return _contar((form(d, formulario).classificacao or {}).get(chave) for d in lista if form(d, formulario))

    recomendaria = next((p for p in percepcoes('FUNCIONARIO') if p['chave'] == 'recomendaria'), None)
    divergentes = [
        {'id': d.id, 'nome': d.nome, 'data': d.data_desligamento,
         'gestor': ROTULO_TIPO.get(form(d, 'GESTOR').tipo_informado, ''),
         'funcionario': ROTULO_TIPO.get(form(d, 'FUNCIONARIO').tipo_informado, '')}
        for d in lista if form(d, 'GESTOR') and form(d, 'FUNCIONARIO')
        and form(d, 'GESTOR').tipo_informado and form(d, 'FUNCIONARIO').tipo_informado
        and form(d, 'GESTOR').tipo_informado != form(d, 'FUNCIONARIO').tipo_informado
    ]
    por_gestor = {}
    for d in lista:
        nome = (d.gestor.nome if d.gestor_id else d.gestor_nome or '').strip()
        if not nome:
            continue
        linha = por_gestor.setdefault(normalizar(nome), {'gestor': nome.title(), 'total': 0, 'VOLUNTARIO': 0,
                                                         'INVOLUNTARIO': 0, 'ACORDO': 0})
        linha['total'] += 1
        if d.tipo in linha:
            linha[d.tipo] += 1

    return {
        'total': total,
        'por_tipo': por_tipo,
        'pct_voluntario': round(100 * por_tipo['VOLUNTARIO'] / total, 1) if total else None,
        'tempo_medio_meses': round(sum(meses_validos) / len(meses_validos), 1) if meses_validos else None,
        'pct_menos_1_ano': round(100 * sum(1 for m in meses_validos if m < 12) / len(meses_validos), 1)
        if meses_validos else None,
        'cobertura': {'gestor': len(com_gestor), 'funcionario': len(com_func),
                      'ambos': sum(1 for d in lista if form(d, 'GESTOR') and form(d, 'FUNCIONARIO'))},
        'pct_recomendaria': round(100 * recomendaria['contagem']['SIM'] / recomendaria['respondidas'], 1)
        if recomendaria and recomendaria['respondidas'] else None,
        'por_mes': [por_mes[k] for k in sorted(por_mes)],
        'por_setor': _contar(d.setor.strip().upper() for d in lista)[:15],
        'por_gestor': sorted(por_gestor.values(), key=lambda x: -x['total'])[:15],
        'faixas_tempo': [{'rotulo': r, 'total': sum(1 for m in meses_validos if faixa_tempo(m) == r)}
                         for _, r in FAIXAS_TEMPO],
        'motivo_principal': principal('FUNCIONARIO', 'motivos'),
        'motivos_marcados': marcadas('FUNCIONARIO', 'motivos', OPCOES_MOTIVOS_FUNCIONARIO),
        'fator_principal': principal('GESTOR', 'fatores'),
        'fatores_marcados': marcadas('GESTOR', 'fatores', OPCOES_FATORES_GESTOR),
        'percepcoes_funcionario': percepcoes('FUNCIONARIO'),
        'percepcoes_gestor': percepcoes('GESTOR'),
        'divergencias_tipo': divergentes,
    }
