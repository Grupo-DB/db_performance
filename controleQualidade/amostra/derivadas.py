"""
Duplicatas e reanálises fora de qualquer média ou estatística.

Uma duplicata (ou reanálise) é uma segunda medição da MESMA amostra: ela entra
no sistema para conferir um resultado, não como um novo ponto de amostragem.
Contada junto com a original, pesa duas vezes na média e estreita o desvio
artificialmente — dois números que descrevem o mesmo material viram "duas
medições concordantes".

Por isso todo cálculo estatístico do módulo (boletim semanal, relatórios
dinâmicos, médias do dashboard) parte de um queryset sem elas. Elas continuam
existindo, aparecendo nas listagens e tendo laudo próprio: o que se tira é o
peso no cálculo.

Como reconhecer:
  * `amostra_origem` preenchida — o caminho novo, de onde sai a numeração
    '.1'/'.2' (ver amostra/numeracao.py);
  * a finalidade escrita como Duplicata/Reanálise — pega as amostras anteriores
    ao campo `amostra_origem` e as que foram marcadas só pela finalidade.
"""
from django.db.models import Q

# Sem acento junto por causa do SQLite dos testes, que (ao contrário do MySQL)
# não é insensível a acento.
FINALIDADES_DERIVADAS = ('duplicata', 'reanálise', 'reanalise')


def q_derivada(prefixo: str = 'amostra__') -> Q:
    """
    Q que casa as amostras derivadas.

    `prefixo` é o caminho até a Amostra a partir do modelo do queryset:
    'amostra__' para Analise, 'analise__amostra__' para AnaliseEnsaio/
    AnaliseCalculo, '' para a própria Amostra.
    """
    condicao = Q(**{f'{prefixo}amostra_origem__isnull': False})
    for finalidade in FINALIDADES_DERIVADAS:
        condicao |= Q(**{f'{prefixo}finalidade__iexact': finalidade})
    return condicao


def sem_derivadas(queryset, prefixo: str = 'amostra__'):
    """O mesmo queryset, sem duplicatas nem reanálises."""
    return queryset.exclude(q_derivada(prefixo))


def eh_derivada(amostra) -> bool:
    """
    Versão em Python — para marcar a linha na resposta da API quando a amostra
    continua na listagem, mas fora da conta.
    """
    if amostra is None:
        return False
    if getattr(amostra, 'amostra_origem_id', None):
        return True
    finalidade = (getattr(amostra, 'finalidade', '') or '').strip().lower()
    return finalidade in FINALIDADES_DERIVADAS
