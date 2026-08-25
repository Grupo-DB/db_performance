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


def formatar_numero(prefixo, sequencial):
    """('cal', 440) → 'cal 00.0440'."""
    digitos = f'{int(sequencial):0{LARGURA_SEQUENCIAL}d}'
    return f'{prefixo} {digitos[:CORTE_SEQUENCIAL]}.{digitos[CORTE_SEQUENCIAL:]}'


def sequencial_de(numero):
    """'cal 00.0440' → 440. Devolve None para o que não for número de amostra.

    Leitura idêntica à do endpoint antigo (último trecho depois do espaço, sem
    os pontos) de propósito: assim continuam contando os números legados de
    outro formato, como 'Calcário 08.392' → 8392.
    """
    if not numero:
        return None
    partes = str(numero).strip().split(' ')
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


def reservar_numero(material, numero_informado=None):
    """Número definitivo da amostra, reservado até o fim da transação em curso.

    Tem de ser chamada dentro de `transaction.atomic()` e o INSERT precisa
    acontecer na MESMA transação — é a trava do `maior_sequencial` que impede
    dois cadastros simultâneos de saírem com o mesmo número.

    Sem material dá para derivar prefixo nenhum; nesse caso devolve o que o
    cliente mandou (o model não aceita `numero` vazio).
    """
    prefixo = normalizar_prefixo(material)
    if not prefixo:
        return numero_informado
    return formatar_numero(prefixo, maior_sequencial(prefixo, travar=True) + 1)


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
