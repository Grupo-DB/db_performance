"""Regras de negócio do Comercial Agro (funções puras, testadas em tests.py)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

# 19/11/2026: "começamos com todas" — toda cotação passa pelo gestor. Com False, só a
# cotação abaixo do preço padrão vai para ele; no padrão (ou acima) é aprovada na hora.
APROVAR_TODAS = True

# Custo do dinheiro para comparar prazos: preço equivalente à vista = preço ÷ (1 + taxa)^(dias/30).
TAXA_MENSAL = 0.012

PRAZOS = (0, 30, 60, 90)
CULTURAS = ('Soja', 'Milho', 'Arroz', 'Trigo', 'Pastagem')

# Grupos de almoxarifado dos produtos agro no SGA (mesma lista das comissões / simples remessa).
GRUPOS_AGRO = (1974, 1587, 1828)

SEM_CONTATO_DIAS = 60


def _f(v) -> float | None:
    return None if v is None or v == '' else float(v)


def potencial(area_ha, dose_t_ha, ciclo_anos) -> float | None:
    """t/ano = área × dose ÷ ciclo. Ciclo 0 = não aplica (potencial zero)."""
    a, d = _f(area_ha), _f(dose_t_ha)
    if a is None or d is None or ciclo_anos is None:
        return None
    if int(ciclo_anos) == 0:
        return 0.0
    return round(a * d / int(ciclo_anos), 1)


def a_vista(preco, prazo_dias: int, taxa: float = TAXA_MENSAL) -> float:
    return round(float(preco) / (1 + taxa) ** (int(prazo_dias or 0) / 30), 2)


def desconto_pct(preco, padrao) -> float | None:
    """% abaixo do padrão (positivo = desconto; negativo = acima do padrão)."""
    p, ref = _f(preco), _f(padrao)
    if p is None or not ref:
        return None
    return round(100 * (ref - p) / ref, 1)


def desconto_efetivo(preco, prazo_dias: int, padrao) -> float | None:
    """Desconto do equivalente à vista sobre o padrão à vista."""
    if not _f(padrao):
        return None
    return desconto_pct(a_vista(preco, prazo_dias), padrao)


def precisa_aprovacao(preco, prazo_dias: int, padrao) -> bool:
    if APROVAR_TODAS or not _f(padrao):
        return True
    return a_vista(preco, prazo_dias) < float(padrao) - 0.005


def primeiro_do_mes(d: date) -> date:
    return d.replace(day=1)


def conferir(cotacao: dict, pedido: dict) -> list[dict]:
    """Compara o pedido lido do SGA com a cotação aprovada.

    `cotacao`: cliente, produto, volume_t, preco, prazo. `pedido`: o mesmo, lido do SGA
    (prazo em dias do último vencimento; volume em t dos itens do produto).
    Devolve a lista de diferenças [{campo, aprovado, lancado}] — vazia = confere.
    """
    dif = []

    def comparar(campo, a, b, tol=0.0):
        if a is None or b is None:
            if a != b:
                dif.append({'campo': campo, 'aprovado': a, 'lancado': b})
            return
        if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
            if abs(float(a) - float(b)) > tol:
                dif.append({'campo': campo, 'aprovado': float(a), 'lancado': float(b)})
        elif a != b:
            dif.append({'campo': campo, 'aprovado': a, 'lancado': b})

    comparar('cliente', cotacao.get('cliente'), pedido.get('cliente'))
    comparar('produto', cotacao.get('produto'), pedido.get('produto'))
    comparar('volume_t', cotacao.get('volume_t'), pedido.get('volume_t'), tol=0.05)
    comparar('preco', cotacao.get('preco'), pedido.get('preco'), tol=0.005)
    comparar('prazo', cotacao.get('prazo'), pedido.get('prazo'))
    return dif


def prazo_em_dias(texto: str | None) -> int | None:
    """PEDPGTOPRAZOST do SGA: "30", "15/30/45", "1" ou vazio (à vista) → dias do último vencimento."""
    if texto is None:
        return None
    partes = [p for p in str(texto).replace(' ', '').split('/') if p.strip().isdigit()]
    if not partes:
        return 0 if not str(texto).strip() else None  # vazio = à vista (482 pedidos agro em 2026, 1 parcela)
    dias = max(int(p) for p in partes)
    return 0 if dias <= 1 else dias
