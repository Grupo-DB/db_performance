"""Catálogo padrão, regras da campanha e leitura da planilha."""
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from .models import Peca, Pedido

# Aba VALORES do Inverno/2026. "EX" na planilha de pedidos é o XG; EX1..EX5 são os EG.
CATALOGO_PADRAO = [
    {'nome': 'Jaqueta', 'publico': '', 'grupo': Peca.UNICA, 'preco': '245.00', 'ordem': 1},
    {'nome': 'Suéter', 'publico': 'F', 'grupo': Peca.UNICA, 'preco': '166.00', 'ordem': 2,
     'precos_por_tamanho': {'EX1': 179, 'EX2': 179, 'EX3': 179, 'EX4': 187, 'EX5': 187}},
    {'nome': 'Suéter', 'publico': 'M', 'grupo': Peca.UNICA, 'preco': '174.00', 'ordem': 3,
     'precos_por_tamanho': {'EX1': 187, 'EX2': 187, 'EX3': 187, 'EX4': 195, 'EX5': 195}},
    {'nome': 'Camisa', 'publico': '', 'grupo': Peca.CAMISA, 'preco': '147.00', 'ordem': 4},
    {'nome': 'Soft', 'publico': '', 'grupo': Peca.UNICA, 'preco': '140.00', 'ordem': 5, 'tem_ziper': True},
]

REGRAS_PADRAO = (
    '- Os funcionários que recebem vão ser cobrados pelo uso obrigatório\n'
    '- Serão distribuídas 2 camisas por funcionário que ganha\n'
    '- Pra quem ganha será disponibilizado somente 1 soft ou 1 jaqueta ou 1 suéter\n'
    '- O desconto para quem compra é feito em folha\n'
    '- O funcionário pode parcelar em até 3 vezes\n'
    '- Líderes, encarregados, gerentes, executivos, diretores e conselheiros pagam pelo uniforme, descontado em folha'
)

# Quem paga pelo uniforme mesmo estando num setor que ganha (aba VALORES).
CARGOS_QUE_PAGAM = ('LIDER', 'ENCARREGAD', 'GERENTE', 'EXECUTIV', 'DIRETOR', 'CONSELHEIR')


def sem_acento(texto) -> str:
    t = unicodedata.normalize('NFD', str(texto or '')).encode('ascii', 'ignore').decode()
    return ' '.join(t.upper().split())


def criar_catalogo(campanha):
    for dados in CATALOGO_PADRAO:
        Peca.objects.get_or_create(campanha=campanha, nome=dados['nome'], publico=dados['publico'],
                                   defaults={k: v for k, v in dados.items() if k not in ('nome', 'publico')})


def peca_do_pedido(campanha, nome_peca: str, genero: str):
    """A peça do catálogo para o gênero do pedido (suéter tem uma por gênero)."""
    pecas = [p for p in campanha.pecas.all() if sem_acento(p.nome) == sem_acento(nome_peca)]
    return next((p for p in pecas if p.publico == genero), None) or next((p for p in pecas if not p.publico), None)


def alertas(pedido: Pedido) -> list[str]:
    """O que foge das regras da campanha. Avisa, não bloqueia (a planilha tinha exceções)."""
    avisos = []
    itens = list(pedido.itens.all())
    if pedido.modalidade == Pedido.GANHA:
        camisas = sum(i.quantidade for i in itens if i.peca.grupo == Peca.CAMISA)
        limite = pedido.campanha.camisas_quem_ganha
        if camisas > limite:
            avisos.append(f'Ganha no máximo {limite} camisas — pedido tem {camisas}.')
        unicas = sum(i.quantidade for i in itens if i.peca.grupo == Peca.UNICA)
        if unicas > 1:
            nomes = ', '.join(sorted({i.peca.nome.lower() for i in itens if i.peca.grupo == Peca.UNICA}))
            avisos.append(f'Quem ganha leva só 1 soft, jaqueta ou suéter — pedido tem {unicas} ({nomes}).')
        cargo = sem_acento(pedido.cargo or (pedido.colaborador.cargo.nome if pedido.colaborador_id and pedido.colaborador.cargo_id else ''))
        if any(c in cargo for c in CARGOS_QUE_PAGAM):
            avisos.append(f'Cargo "{pedido.cargo or cargo.title()}" paga o uniforme (liderança/gestão).')
    elif pedido.parcelas > pedido.campanha.parcelas_max:
        avisos.append(f'Parcela em até {pedido.campanha.parcelas_max} vezes — pedido tem {pedido.parcelas}.')
    return avisos


def valor_pedido(pedido: Pedido) -> Decimal:
    if pedido.modalidade != Pedido.COMPRA:
        return Decimal('0')
    return sum((i.valor for i in pedido.itens.all()), Decimal('0'))


# ── Planilha ────────────────────────────────────────────────────────────────

_CELULA = re.compile(r'^\s*(\d+)\s*\(\s*([A-Za-z0-9]+)\s*\)\s*$')


def ler_celula(valor) -> tuple[int, str] | None:
    """'1 (P)' → (1, 'P'); '2 (GG)'; '1(M)'; '1 (PP )'. Traço ou vazio → None."""
    m = _CELULA.match(str(valor or ''))
    return (int(m.group(1)), m.group(2).upper()) if m else None


def ler_ziper(valor) -> str:
    t = sem_acento(valor)
    return {'TODO': 'TODO', 'MEIO': 'MEIO', '1 DE CADA': 'UM_DE_CADA'}.get(t, '')


def ler_entrega(valor) -> tuple[bool, date | None, str]:
    """(entregue, data, observação): data → entregue; 'Jak levou' → entregue sem data; resto → pendente com nota."""
    if isinstance(valor, datetime):
        return True, valor.date(), ''
    if isinstance(valor, date):
        return True, valor, ''
    texto = str(valor or '').strip()
    if not texto or texto == '-':
        return False, None, ''
    try:
        return True, datetime.strptime(texto[:10], '%Y-%m-%d').date(), ''
    except ValueError:
        pass
    return ('LEVOU' in sem_acento(texto)), None, texto.capitalize() if texto.isupper() else texto
