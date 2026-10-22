"""
Programa Jovem Aprendiz — os dois formulários do RH (AVALIAÇÃO JOVEM APRENDIZ.docx, preenchido pelo
instrutor, e AUTO AVALIAÇÃO JOVEM APRENDIZ.docx, pelo jovem), com o texto exato dos documentos.

As 10 competências se correspondem uma a uma nos dois (a chave é a mesma), o que permite comparar
"como o instrutor vê" com "como o jovem se vê".
"""

ESCALAS = {
    'INSTRUTOR': {1: 'Precisa desenvolver', 2: 'Em desenvolvimento', 3: 'Atende ao esperado', 4: 'Supera o esperado'},
    'AUTO': {1: 'Preciso melhorar bastante', 2: 'Ainda estou desenvolvendo', 3: 'Consigo fazer bem', 4: 'Considero que faço muito bem'},
}

# chave: (nome e descrição na avaliação do instrutor, nome e descrição na autoavaliação)
COMPETENCIAS = [
    ('comunicacao', ('Comunicação', 'Comunica-se com clareza e respeito.'),
                    ('Comunicação', 'Consigo me comunicar de forma clara e respeitosa.')),
    ('escuta', ('Escuta e receptividade', 'Ouve orientações e aceita feedbacks.'),
               ('Escuta', 'Sei ouvir orientações e feedbacks.')),
    ('equipe', ('Trabalho em equipe', 'Coopera e respeita os colegas.'),
               ('Trabalho em equipe', 'Consigo trabalhar bem com outras pessoas.')),
    ('etica', ('Ética', 'Demonstra honestidade, respeito e responsabilidade.'),
              ('Respeito e ética', 'Tenho respeito pelas pessoas e pelo ambiente de trabalho.')),
    ('postura', ('Postura profissional', 'Apresenta comportamento adequado ao ambiente de trabalho.'),
                ('Postura profissional', 'Tenho uma postura adequada no ambiente profissional.')),
    ('pontualidade', ('Pontualidade e assiduidade', 'Demonstra compromisso com horários e atividades.'),
                     ('Pontualidade', 'Cumpro horários e compromissos.')),
    ('responsabilidade', ('Responsabilidade', 'Cumpre tarefas e assume seus compromissos.'),
                         ('Responsabilidade', 'Tenho responsabilidade com minhas tarefas.')),
    ('iniciativa', ('Iniciativa', 'Demonstra interesse em aprender e contribuir.'),
                   ('Aprendizado', 'Demonstro interesse em aprender.')),
    ('logico', ('Pensamento lógico', 'Busca compreender situações e encontrar soluções.'),
               ('Pensamento lógico', 'Procuro soluções quando encontro dificuldades.')),
    ('pertencimento', ('Senso de pertencimento', 'Demonstra interesse em fazer parte da equipe e da empresa.'),
                      ('Pertencimento', 'Sinto que faço parte da equipe e da empresa.')),
]
CHAVES = [c[0] for c in COMPETENCIAS]

PERGUNTAS = {
    'INSTRUTOR': [
        ('ponto_forte', 'Qual é o principal ponto forte demonstrado pelo jovem?'),
        ('desenvolver', 'Qual comportamento precisa ser desenvolvido ou aprimorado?'),
    ],
    'AUTO': [
        ('melhorar_comportamento', 'Qual comportamento profissional eu preciso melhorar?'),
        ('fez_diferenca', 'Em que situação percebi que meu trabalho fez diferença para alguém ou para a equipe?'),
        ('quero_melhorar', 'O que eu quero melhorar durante este projeto?'),
    ],
}

EVOLUCOES = [
    ('SIGNIFICATIVA', 'Sim, significativa'), ('MODERADA', 'Sim, moderada'),
    ('POUCA', 'Pouca evolução'), ('NAO_PERCEBIDA', 'Ainda não foi possível perceber'),
]

TITULOS = {
    'INSTRUTOR': ('Avaliação – Jovem Aprendiz', 'Preenchida pelo instrutor do projeto.'),
    'AUTO': ('Autoavaliação do Jovem Aprendiz',
             'Esta avaliação não é uma prova. Não existem respostas certas ou erradas. O objetivo é entender como você '
             'percebe seu próprio desenvolvimento e identificar o que pode melhorar.'),
}


def formulario(tipo: str) -> dict:
    """Definição para a tela montar o formulário (e o PDF) sem repetir o texto."""
    i = 0 if tipo == 'INSTRUTOR' else 1
    return {
        'tipo': tipo, 'titulo': TITULOS[tipo][0], 'instrucao': TITULOS[tipo][1],
        'escala': [{'valor': k, 'rotulo': v} for k, v in ESCALAS[tipo].items()],
        'competencias': [{'chave': c[0], 'nome': c[1 + i][0], 'descricao': c[1 + i][1]} for c in COMPETENCIAS],
        'perguntas': [{'chave': k, 'texto': t} for k, t in PERGUNTAS[tipo]],
        'evolucoes': [{'valor': v, 'rotulo': r} for v, r in EVOLUCOES] if tipo == 'INSTRUTOR' else [],
        'assinatura': 'Assinatura do avaliador' if tipo == 'INSTRUTOR' else 'Assinatura do jovem',
    }


def media(notas: dict) -> float | None:
    valores = [int(v) for v in (notas or {}).values() if v]
    return round(sum(valores) / len(valores), 2) if valores else None
