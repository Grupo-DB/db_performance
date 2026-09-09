"""
Numeração das amostras ("cal 00.0440") — quem decide o número é o SERVIDOR.

Até 08/2026 o número vinha pronto do navegador: ao escolher o material, o front
pedia `amostra/proximo-sequencial-nome/<material>/` (um `max + 1`), montava
`cal 00.0440` e mandava esse texto no POST — minutos, às vezes DIAS depois.
Sem reserva no meio e sem `unique` no banco, o mesmo número nascia duas vezes:

* duas pessoas (ou duas abas) cadastrando o mesmo material ao mesmo tempo;
* o snapshot `amostraData` (sessionStorage / history.state) levando o número
  congelado para as telas de Ordem e Expressa, que gravavam sem reconsultar;
* `duplicata()` das telas de Ordem e Arquivo, que copiava o número junto.

Aqui o número é calculado e **reservado dentro da mesma transação do INSERT**
(`reservar_numero`, chamada por `AmostraViewSet.perform_create`). O formulário
continua exibindo uma prévia, mas ela é só prévia: vale o número que a API
devolve na resposta.

O formato e a regra de qual sequencial conta são os mesmos de antes, para não
deslocar a numeração que o laboratório já usa:

* prefixo = material normalizado (sem acento, minúsculo) — `normalize()` do
  amostra.ts;
* sequencial com 6 dígitos, quebrado em 2 + 4: 440 → `00.0440`;
* o "maior sequencial" olha todo `numero` que COMEÇA com o prefixo, então
  `cal` continua enxergando `calcario ...` e `cal hidratada ...`.

DUPLICATA E REANÁLISE
---------------------
Uma amostra criada como duplicata ou reanálise de outra NÃO consome um sequencial
novo: ela pendura um índice no número da original.

    calcario 00.0526      original
    calcario 00.0526.1    primeira duplicata/reanálise
    calcario 00.0526.2    segunda

É o que o laboratório já escrevia à mão. A consequência importante está em
`sequencial_de`: sem tratamento, 'calcario 00.0526.1' viraria o sequencial
5.261 e a próxima amostra de calcário nasceria como `calcario 52.6200`. Por isso
o sufixo é removido ANTES de ler o sequencial — a derivada é invisível para a
contagem do prefixo.

Derivada de derivada não existe: `.1.1` seria ambíguo com o formato. Pedir uma
duplicata de `calcario 00.0526.1` cria `calcario 00.0526.2`, irmã e não filha.
"""
import re
import unicodedata

from django.db import connection

# Formato de saída: 'cal' + 440 → 'cal 00.0440'.
LARGURA_SEQUENCIAL = 6
CORTE_SEQUENCIAL = 2


def normalizar_prefixo(material):
    """'Calcário', 'CALCARIO', ' cal ' → 'calcario' / 'cal'.

    Mesma normalização do `normalize()` em amostra.ts, senão o prefixo gravado
    aqui não casaria com o que a tela mostra.
    """
    if not material:
        return ''
    sem_acento = unicodedata.normalize('NFD', str(material))
    sem_acento = ''.join(c for c in sem_acento if unicodedata.category(c) != 'Mn')
    return sem_acento.lower().strip()


# 'calcario 00.0526.1' → base 'calcario 00.0526' + índice 1.
#
# Exige um ponto ANTES do sufixo (`.+\.\d+`) justamente para não confundir a
# derivada com o formato normal: 'cal 00.0440' e o legado 'Calcário 08.392' têm
# um grupo de dígitos só depois do ponto e não casam aqui.
DERIVADA_RE = re.compile(r'^(?P<base>.+\.\d+)\.(?P<indice>\d+)$')


def separar_derivada(numero):
    """'calcario 00.0526.1' → ('calcario 00.0526', 1). Não sendo derivada, (numero, None)."""
    texto = str(numero or '').strip()
    casou = DERIVADA_RE.match(texto)
    if not casou:
        return texto, None
    return casou.group('base'), int(casou.group('indice'))


def formatar_numero(prefixo, sequencial):
    """('cal', 440) → 'cal 00.0440'."""
    digitos = f'{int(sequencial):0{LARGURA_SEQUENCIAL}d}'
    return f'{prefixo} {digitos[:CORTE_SEQUENCIAL]}.{digitos[CORTE_SEQUENCIAL:]}'


def sequencial_de(numero):
    """'cal 00.0440' → 440. Devolve None para o que não for número de amostra.

    Leitura idêntica à do endpoint antigo (último trecho depois do espaço, sem
    os pontos) de propósito: assim continuam contando os números legados de
    outro formato, como 'Calcário 08.392' → 8392.

    A DERIVADA devolve o sequencial da ORIGINAL: 'calcario 00.0526.1' → 526.
    Ela não é um número novo, é a mesma amostra reanalisada, e deixá-la contar
    como 5.261 empurraria toda a numeração do prefixo para frente.
    """
    if not numero:
        return None
    base, _ = separar_derivada(numero)
    partes = str(base).strip().split(' ')
    if len(partes) < 2:
        return None
    digitos = partes[-1].replace('.', '')
    return int(digitos) if digitos.isdigit() else None


def maior_sequencial(prefixo, travar=False):
    """Maior sequencial já usado pelos números que começam com `prefixo`.

    Com `travar=True` as linhas do prefixo ficam presas (`SELECT ... FOR UPDATE`)
    até o fim da transação: quem estiver criando outra amostra do mesmo material
    espera aqui em vez de receber o mesmo número. Precisa estar dentro de
    `transaction.atomic()`.

    O SQLite do ambiente local não tem `FOR UPDATE` — ali a trava é ignorada
    (o banco já serializa a escrita) em vez de estourar NotSupportedError.
    """
    from .models import Amostra

    consulta = Amostra.objects.filter(numero__istartswith=prefixo)
    if travar and connection.features.has_select_for_update:
        consulta = consulta.select_for_update()

    maior = 0
    for numero in consulta.values_list('numero', flat=True):
        sequencial = sequencial_de(numero)
        if sequencial and sequencial > maior:
            maior = sequencial
    return maior


def proximo_sequencial(material):
    """Prévia para o formulário: qual sequencial sairia AGORA (sem reservar)."""
    prefixo = normalizar_prefixo(material)
    if not prefixo:
        return 1
    return maior_sequencial(prefixo) + 1


def reservar_numero(material, numero_informado=None, origem=None):
    """Número definitivo da amostra, reservado até o fim da transação em curso.

    Tem de ser chamada dentro de `transaction.atomic()` e o INSERT precisa
    acontecer na MESMA transação — é a trava do `maior_sequencial` que impede
    dois cadastros simultâneos de saírem com o mesmo número.

    Com `origem` a amostra é duplicata/reanálise: em vez de consumir um
    sequencial novo, pendura o próximo índice no número da original
    ('calcario 00.0526' → 'calcario 00.0526.1'). O material nem entra na conta,
    porque o prefixo é o da original — uma duplicata cadastrada com o material
    escrito de outro jeito continua na mesma família.

    Sem material e sem origem dá para derivar prefixo nenhum; nesse caso devolve
    o que o cliente mandou (o model não aceita `numero` vazio).
    """
    if origem is not None:
        derivado = proximo_numero_derivada(origem, travar=True)
        if derivado:
            return derivado

    prefixo = normalizar_prefixo(material)
    if not prefixo:
        return numero_informado
    return formatar_numero(prefixo, maior_sequencial(prefixo, travar=True) + 1)


def maior_indice_derivada(base, travar=False):
    """Maior índice já pendurado em `base` ('calcario 00.0526' → 2 se existe .2).

    Com `travar=True` prende as linhas da família até o fim da transação, pelo
    mesmo motivo de `maior_sequencial`: duas duplicatas pedidas ao mesmo tempo
    sairiam ambas como `.1`.

    O filtro é `istartswith` da base com o ponto — 'calcario 00.0526.' — para
    não arrastar 'calcario 00.05261' (que não é da família) nem a própria base.
    """
    from .models import Amostra

    consulta = Amostra.objects.filter(numero__istartswith=f'{base}.')
    if travar and connection.features.has_select_for_update:
        consulta = consulta.select_for_update()

    maior = 0
    for numero in consulta.values_list('numero', flat=True):
        familia, indice = separar_derivada(numero)
        if indice and chave_colacao(familia) == chave_colacao(base):
            maior = max(maior, indice)
    return maior


def numero_base_de(origem):
    """Número-tronco da família de `origem` — a própria, ou a mãe se ela for derivada.

    Duplicata de duplicata vira irmã: pedir a partir de 'calcario 00.0526.1'
    devolve 'calcario 00.0526', e o índice novo sai `.2`.
    """
    base, _ = separar_derivada(getattr(origem, 'numero', origem))
    return base


def proximo_numero_derivada(origem, travar=False):
    """Número da próxima duplicata/reanálise de `origem`: 'calcario 00.0526.3'."""
    base = numero_base_de(origem)
    if not base:
        return None
    return f'{base}.{maior_indice_derivada(base, travar=travar) + 1}'


def chave_colacao(texto):
    """Chave de comparação equivalente à collation do MySQL (sem acento, minúscula).

    O banco de produção compara texto ignorando acento e caixa, então
    'CAL 00.0440' e 'cal 00.0440' são o MESMO número para o índice único.
    """
    return ' '.join(normalizar_prefixo(texto).split())


def numeros_duplicados():
    """{numero: [ids]} de todo número repetido, para o comando de conserto.

    Agrupa em Python, e não com `values('numero').annotate(Count)`, porque a
    collation do MySQL é insensível a acento e caixa: 'CAL 00.0440' e
    'cal 00.0440' são duplicata para o índice único e precisam aparecer juntas
    aqui também.
    """
    from .models import Amostra

    por_chave = {}
    for pk, numero in Amostra.objects.values_list('id', 'numero').order_by('id'):
        chave = chave_colacao(numero)
        por_chave.setdefault(chave, []).append((pk, numero))
    return {
        registros[0][1]: [pk for pk, _ in registros]
        for chave, registros in por_chave.items()
        if chave and len(registros) > 1
    }


# Usado só pelo comando de conserto, para reaproveitar buracos na numeração.
def sequenciais_usados(prefixo):
    from .models import Amostra

    usados = set()
    for numero in Amostra.objects.filter(numero__istartswith=prefixo).values_list('numero', flat=True):
        sequencial = sequencial_de(numero)
        if sequencial:
            usados.add(sequencial)
    return usados


PREFIXO_RE = re.compile(r'^(?P<prefixo>.+?)\s+\d')


def prefixo_de(numero):
    """'cal 00.0440' → 'cal'. Devolve '' quando o número não tem o formato."""
    casou = PREFIXO_RE.match(str(numero or '').strip())
    return normalizar_prefixo(casou.group('prefixo')) if casou else ''
