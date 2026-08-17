"""Motor de regras de comissão — executa as RegraComissao cadastradas pelo usuário.

Contexto: até aqui `views.calculos_comissoes` calculava tudo em blocos escritos à mão
(um por vendedor) e a tabela `RegraComissao` existia sem ninguém ler. Este módulo é o
avaliador que faltava.

Regra de convivência com o código legado (importante): o motor **nunca sobrescreve** um
vendedor que já foi calculado pelos blocos hardcoded. Os números desses vendedores
conferem com a planilha e as exceções deles (YARA, COFCO, licença-maternidade, rateio do
bônus global) não são representáveis por regra. Se houver colisão, a regra é ignorada e
o conflito sai em `_motor_regras_debug` para o usuário ver na tela.

Uso:
    from .motor_regras import aplicar_regras
    debug = aplicar_regras(df, resultado, metas_efetivas, periodo_chave)
"""

import re

import pandas as pd

from .models import MapeamentoMunicipio, RegraComissao, VinculoRepresentante

# Mesmas colunas que o front já consome nos lançamentos dos vendedores hardcoded.
_COLUNAS_LANCAMENTO = {
    'DATA_EMISSAO': 'data',
    'NOTA_FISCAL': 'nota_fiscal',
    'REPRESENTANTE': 'representante',
    'REPRESENTANTE_MASTER': 'representante_master',
    'CLIENTE_NOME': 'cliente',
    'CIDADE_FATURAMENTO': 'cidade',
    'ESTOQUE': 'produto',
    'GRUPO_COMERCIAL': 'grupo_comercial',
    'GRUPO_COMERCIAL_LINHA_PRODUTOS': 'linha_produtos',
    'SEGMENTO_PRODUTO': 'segmento_produto',
    'QUANTIDADE': 'quantidade',
    'QUANTIDADE_TN': 'quantidade_tn',
    'VALOR_PRODUTO': 'valor_produto',
    'VALOR_TOTAL': 'valor_total',
    'EMPRESAFILIAL': 'filial',
}

CAMPOS_REGRA = (
    'id', 'descricao', 'tipo', 'base_calculo', 'segmento_produto', 'escopo',
    'taxa', 'valor_fixo', 'multiplicador', 'valor_minimo', 'valor_maximo',
    'ordem', 'ativo', 'meta_grupo', 'base_comissoes_de',
    'filtro_filial_contem', 'filtro_cliente_contem', 'filtro_cliente_excluir',
    'filtro_grupo_comercial_contem', 'filtro_grupo_comercial_excluir',
    'filtro_cidade_sufixo',
)


def _f(valor, default=0.0):
    """Decimal/str/None → float, sem explodir."""
    try:
        if valor is None or valor == '':
            return default
        return float(valor)
    except (TypeError, ValueError):
        return default


def nome_base(nome):
    """'DANIEL M MOREIRA (SUL) - 12' → 'DANIEL M MOREIRA'.

    O ERP e as metas trazem o mesmo vendedor com sufixo de região entre parênteses ou
    com código no fim; sem normalizar, a checagem de conflito com o hardcoded falha.
    """
    s = re.sub(r'\s*\(.*?\)\s*$', '', str(nome or '').strip().upper())
    return re.sub(r'\s*-\s*\d+\s*$', '', s).strip()


def _termos(texto):
    """'YARA;COFCO' → ['YARA', 'COFCO'] (vazios descartados)."""
    return [t.strip().upper() for t in str(texto or '').split(';') if t.strip()]


# Variantes com que o grupo CB/Cal Crem aparece no ERP — as metas são cadastradas como 'CB'.
# Mesma lista usada nos blocos fixos do views.py.
CB_TERMOS = ['CB CAL', 'CAL PINTURA', 'CERRO BRANCO', 'CAL CREM', 'CB/CAL', 'ACABAMENTO']


def meta_do_grupo(metas, nome_grupo):
    """Meta cadastrada para um grupo, tolerante ao nome.

    O usuário cadastra a taxa com o nome que vê no ERP ('CERRO BRANCO') e a meta com o
    nome curto ('CB'); sem casar os dois, o potencializador nunca dispara.
    """
    if not metas or not nome_grupo:
        return 0.0
    g = str(nome_grupo).strip().upper()
    if g in metas:
        return _f(metas[g])
    if g == 'CB' or any(t in g for t in CB_TERMOS):
        if 'CB' in metas:
            return _f(metas['CB'])
    for chave, valor in metas.items():
        k = str(chave).strip().upper()
        if k and (k in g or g in k):
            return _f(valor)
    return 0.0


def _serializa_regra(regra):
    """RegraComissao (model) → dict plano, o mesmo formato que a simulação recebe do front."""
    return {campo: getattr(regra, campo) for campo in CAMPOS_REGRA} | {
        'grupos': [
            {'grupo': g.grupo, 'taxa': g.taxa, 'taxa_potencializador': g.taxa_potencializador}
            for g in regra.grupos.all()
        ],
        'faixas': [
            {'pct_minimo': f.pct_minimo, 'pct_maximo': f.pct_maximo, 'taxa': f.taxa}
            for f in regra.faixas.all()
        ],
    }


def _coluna_grupo(d):
    """Texto único com as três origens de grupo do ERP, para os filtros de grupo.

    GRUPO_COMERCIAL sozinho não basta: a dolomita, por exemplo, aparece ora em
    GRUPO_COMERCIAL, ora na linha de produtos, ora só em GRUPO.
    """
    partes = [
        d[c].fillna('').astype(str)
        for c in ('GRUPO_COMERCIAL', 'GRUPO_COMERCIAL_LINHA_PRODUTOS', 'GRUPO')
        if c in d.columns
    ]
    if not partes:
        return pd.Series([''] * len(d), index=d.index)
    junto = partes[0]
    for p in partes[1:]:
        junto = junto + ' | ' + p
    return junto.str.upper()


def _contem_algum(serie, termos):
    """OR entre os termos: a linha entra se casar com qualquer um."""
    mask = pd.Series(False, index=serie.index)
    for t in termos:
        mask = mask | serie.str.contains(t, na=False, regex=False)
    return mask


def linhas_da_regra(df, regra, nome_rep, cidades_do_rep):
    """Recorte do dataframe de vendas em que a regra incide."""
    d = df

    seg = (regra.get('segmento_produto') or 'CC').upper()
    if seg == 'CC':
        d = d[d['SEGMENTO_PRODUTO'] == 'CONSTRUCAO CIVIL']
    elif seg == 'AGRO':
        d = d[d['SEGMENTO_PRODUTO'] == 'AGRONEGOCIO']

    escopo = (regra.get('escopo') or 'REPRESENTANTE').upper()
    if escopo == 'REPRESENTANTE':
        d = d[d['REPRESENTANTE'].str.contains(nome_rep, na=False, regex=False)]
    elif escopo == 'MASTER':
        d = d[
            d['REPRESENTANTE'].str.contains(nome_rep, na=False, regex=False)
            | d['REPRESENTANTE_MASTER'].str.contains(nome_rep, na=False, regex=False)
        ]
    elif escopo == 'MUNICIPIOS':
        d = d[d['CIDADE_FATURAMENTO'].isin(cidades_do_rep)] if cidades_do_rep else d.iloc[0:0]
    # 'TODAS' não filtra por vendedor (gestor / salário fixo / % sobre comissões)

    if d.empty:
        return d

    if _termos(regra.get('filtro_filial_contem')):
        d = d[_contem_algum(d['EMPRESAFILIAL'], _termos(regra['filtro_filial_contem']))]
    if _termos(regra.get('filtro_cliente_contem')):
        d = d[_contem_algum(d['CLIENTE_NOME'], _termos(regra['filtro_cliente_contem']))]
    if _termos(regra.get('filtro_cliente_excluir')):
        d = d[~_contem_algum(d['CLIENTE_NOME'], _termos(regra['filtro_cliente_excluir']))]
    if _termos(regra.get('filtro_grupo_comercial_contem')):
        d = d[_contem_algum(_coluna_grupo(d), _termos(regra['filtro_grupo_comercial_contem']))]
    if _termos(regra.get('filtro_grupo_comercial_excluir')):
        d = d[~_contem_algum(_coluna_grupo(d), _termos(regra['filtro_grupo_comercial_excluir']))]

    sufixos = _termos(regra.get('filtro_cidade_sufixo'))
    if sufixos:
        mask = pd.Series(False, index=d.index)
        for suf in sufixos:
            mask = mask | d['CIDADE_FATURAMENTO'].str.endswith(suf, na=False)
        d = d[mask]

    return d


def _monta_lancamentos(df_in):
    if df_in is None or len(df_in) == 0:
        return []
    cols = {k: v for k, v in _COLUNAS_LANCAMENTO.items() if k in df_in.columns}
    out = df_in[list(cols.keys())].rename(columns=cols).copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime('%d/%m/%Y')
    for c in ('valor_produto', 'valor_total', 'quantidade_tn'):
        if c in out.columns:
            out[c] = out[c].round(2)
    out = out.fillna('')
    return out.sort_values('data').to_dict(orient='records') if 'data' in out.columns else out.to_dict(orient='records')


def _aplica_piso_teto(valor, regra):
    minimo = _f(regra.get('valor_minimo'))
    maximo = _f(regra.get('valor_maximo'))
    if minimo > 0 and valor < minimo:
        valor = minimo
    if maximo > 0 and valor > maximo:
        valor = maximo
    return valor


def _meta_do_rep(metas_efetivas, periodo_chave, nome_rep, meta_grupo):
    metas = metas_efetivas.get(f"{periodo_chave}{nome_base(nome_rep)}") or metas_efetivas.get(f"{periodo_chave}{nome_rep}") or {}
    if meta_grupo:
        return meta_do_grupo(metas, meta_grupo)
    return sum(_f(v) for v in metas.values())


def avalia_regra(df, regra, nome_rep, metas_efetivas, periodo_chave, cidades_do_rep):
    """Executa UMA regra e devolve (valor_comissao, memoria_de_calculo, linhas_usadas).

    A memória é o que a tela mostra ao usuário: cada passo com base, taxa e resultado.
    """
    base_col = 'VALOR_TOTAL' if regra.get('base_calculo') == 'VALOR_TOTAL' else 'VALOR_PRODUTO'
    tipo = (regra.get('tipo') or '').upper()
    mult = _f(regra.get('multiplicador'), 1.0) or 1.0

    # FIXO e PERCENTUAL_DE_COMISSOES não dependem das notas — não recortam o dataframe,
    # senão as notas de um salário fixo entrariam na lista de lançamentos do vendedor.
    linhas = (df.iloc[0:0] if tipo in ('PERCENTUAL_DE_COMISSOES', 'FIXO')
              else linhas_da_regra(df, regra, nome_rep, cidades_do_rep))
    base = float(linhas[base_col].sum()) if len(linhas) else 0.0

    memoria = {
        'regra_id': regra.get('id'),
        'descricao': regra.get('descricao'),
        'tipo': tipo,
        'base_calculo': base_col,
        'escopo': regra.get('escopo'),
        'base': round(base, 2),
        'qtd_linhas': int(len(linhas)),
        'passos': [],
    }
    valor = 0.0

    if tipo == 'PERCENTUAL_FIXO':
        taxa = _f(regra.get('taxa'))
        valor = base * taxa
        memoria['passos'].append({
            'texto': f"{_brl(base)} × {_pct(taxa)}", 'base': round(base, 2),
            'taxa': taxa, 'valor': round(valor, 2),
        })

    elif tipo == 'FIXO':
        valor = _f(regra.get('valor_fixo'))
        memoria['passos'].append({'texto': f"valor fixo {_brl(valor)}", 'valor': round(valor, 2)})

    elif tipo == 'PERCENTUAL_POR_GRUPO':
        col_grupo = _coluna_grupo(linhas) if len(linhas) else None
        metas = metas_efetivas.get(f"{periodo_chave}{nome_base(nome_rep)}", {})
        for g in regra.get('grupos') or []:
            nome_g = str(g.get('grupo') or '').strip().upper()
            if not nome_g:
                continue
            sub = linhas[col_grupo.str.contains(nome_g, na=False, regex=False)] if col_grupo is not None else linhas
            base_g = float(sub[base_col].sum()) if len(sub) else 0.0
            taxa_g = _f(g.get('taxa'))
            valor_g = base_g * taxa_g
            meta_g = meta_do_grupo(metas, nome_g)
            bateu = meta_g > 0 and base_g >= meta_g
            pot = _f(g.get('taxa_potencializador'))
            if bateu and pot:
                valor_g += base_g * pot
            valor += valor_g
            memoria['passos'].append({
                'texto': f"{nome_g}: {_brl(base_g)} × {_pct(taxa_g + (pot if bateu and pot else 0))}"
                         + (f" (potencializador {_pct(pot)} — meta {_brl(meta_g)} batida)" if bateu and pot else ''),
                'grupo': nome_g, 'base': round(base_g, 2), 'taxa': taxa_g,
                'meta': round(meta_g, 2), 'meta_atingida': bool(bateu), 'valor': round(valor_g, 2),
            })

    elif tipo == 'ESCADA_META':
        meta = _meta_do_rep(metas_efetivas, periodo_chave, nome_rep, regra.get('meta_grupo'))
        pct = (base / meta * 100.0) if meta > 0 else 0.0
        faixa_usada, taxa = None, 0.0
        for f in sorted(regra.get('faixas') or [], key=lambda x: _f(x.get('pct_minimo'))):
            pmin = _f(f.get('pct_minimo'))
            pmax = f.get('pct_maximo')
            dentro = pct >= pmin and (pmax in (None, '') or pct <= _f(pmax))
            if dentro:
                faixa_usada, taxa = f, _f(f.get('taxa'))
        valor = base * taxa
        memoria['meta'] = round(meta, 2)
        memoria['pct_meta'] = round(pct, 2)
        memoria['passos'].append({
            'texto': (f"meta {_brl(meta)} · realizado {_brl(base)} = {_num(pct)}% → faixa "
                      f"{_num(_f(faixa_usada.get('pct_minimo')))}%–"
                      f"{('∞' if faixa_usada.get('pct_maximo') in (None, '') else _num(_f(faixa_usada.get('pct_maximo'))) + '%')}"
                      f" · {_pct(taxa)}")
            if faixa_usada else f"realizado {_brl(base)} não caiu em nenhuma faixa (meta {_brl(meta)})",
            'base': round(base, 2), 'taxa': taxa, 'valor': round(valor, 2),
            'faixa': ({'pct_minimo': _f(faixa_usada.get('pct_minimo')),
                       'pct_maximo': (None if faixa_usada.get('pct_maximo') in (None, '')
                                      else _f(faixa_usada.get('pct_maximo')))}
                      if faixa_usada else None),
        })

    elif tipo == 'PERCENTUAL_DE_COMISSOES':
        # calculado no 2º passe (precisa das comissões dos outros já prontas)
        memoria['segundo_passe'] = True

    if mult != 1.0 and valor:
        antes = valor
        valor *= mult
        memoria['passos'].append({
            'texto': f"multiplicador ×{mult:g} ({_brl(antes)} → {_brl(valor)})",
            'valor': round(valor, 2),
        })

    apos = _aplica_piso_teto(valor, regra)
    if apos != valor:
        memoria['passos'].append({
            'texto': (f"mínimo garantido {_brl(_f(regra.get('valor_minimo')))}"
                      if apos > valor else f"teto {_brl(_f(regra.get('valor_maximo')))}"),
            'valor': round(apos, 2),
        })
        valor = apos

    memoria['valor'] = round(valor, 2)
    return valor, memoria, linhas


def _num(valor, casas=2):
    """Número em pt-BR sem zeros à direita: 99.99 → '99,99', 100.0 → '100'."""
    txt = f"{_f(valor):.{casas}f}".rstrip('0').rstrip('.')
    return txt.replace('.', ',') or '0'


def _pct(taxa):
    return _num(_f(taxa) * 100, 4) + '%'


def _brl(valor):
    return 'R$ ' + f"{_f(valor):,.2f}".replace(',', '@').replace('.', ',').replace('@', '.')


def aplicar_regras(df, resultado, metas_efetivas, periodo_chave, regras_preview=None,
                   representante_preview=None):
    """Aplica as regras cadastradas sobre `resultado` (dict do calculos_comissoes).

    `regras_preview` + `representante_preview` permitem simular regras ainda NÃO salvas:
    as regras do banco daquele representante são substituídas pelas recebidas no POST.

    Devolve o dict de debug (também usado pela tela como memória de cálculo).
    """
    debug = {'aplicados': [], 'ignorados_por_conflito': [], 'erros': []}

    try:
        qs = (RegraComissao.objects.filter(ativo=True)
              .select_related('representante')
              .prefetch_related('grupos', 'faixas'))
        por_rep = {}
        for regra in qs:
            nome = (regra.representante.nome or '').strip().upper()
            por_rep.setdefault(nome, []).append(_serializa_regra(regra))
    except Exception as exc:  # banco sem a migration nova, por exemplo
        debug['erros'].append(f'falha ao carregar regras: {exc}')
        return debug

    if regras_preview is not None and representante_preview:
        nome_prev = str(representante_preview).strip().upper()
        por_rep[nome_prev] = [
            {**{c: r.get(c) for c in CAMPOS_REGRA},
             'grupos': r.get('grupos') or [], 'faixas': r.get('faixas') or []}
            for r in regras_preview
            if r.get('ativo', True)
        ]
        # na simulação só interessa o vendedor em questão
        por_rep = {nome_prev: por_rep[nome_prev]}

    if not por_rep:
        return debug

    # Cidades mapeadas por representante (escopo MUNICIPIOS)
    cidades_por_rep = {}
    try:
        for m in MapeamentoMunicipio.objects.select_related('representante'):
            nome = (m.representante.nome or '').strip().upper()
            cidades_por_rep.setdefault(nome, set()).add((m.cidade_estado or '').strip().upper())
    except Exception:
        pass

    # Nomes já calculados pelos blocos hardcoded — o motor não encosta neles.
    bases_existentes = {
        nome_base(k) for k, v in resultado.items()
        if not str(k).startswith('_') and isinstance(v, dict) and 'comissao' in v
    }

    pendentes_2o_passe = []

    for nome_rep, regras in sorted(por_rep.items()):
        base_nome = nome_base(nome_rep)
        if base_nome in bases_existentes and not (regras_preview is not None and representante_preview):
            debug['ignorados_por_conflito'].append({
                'representante': nome_rep,
                'motivo': 'já calculado por regra fixa no código; as regras cadastradas foram ignoradas '
                          'para não alterar valores que conferem com a planilha',
                'qtd_regras': len(regras),
            })
            continue

        cidades = cidades_por_rep.get(nome_rep) or cidades_por_rep.get(base_nome) or set()
        total, memorias, idx_linhas = 0.0, [], None

        for regra in sorted(regras, key=lambda r: (_f(r.get('ordem')), str(r.get('descricao') or ''))):
            try:
                valor, memoria, linhas = avalia_regra(
                    df, regra, base_nome, metas_efetivas, periodo_chave, cidades
                )
            except Exception as exc:
                debug['erros'].append(f"{nome_rep} · {regra.get('descricao')}: {exc}")
                continue

            if memoria.get('segundo_passe'):
                pendentes_2o_passe.append((nome_rep, base_nome, regra, memoria))
                memorias.append(memoria)
                continue

            total += valor
            memorias.append(memoria)
            if len(linhas):
                idx_linhas = linhas.index if idx_linhas is None else idx_linhas.union(linhas.index)

        resultado[nome_rep] = {
            'comissao': round(total, 2),
            'tipo': 'Regra configurada',
            'origem': 'motor_regras',
            'memoria_calculo': memorias,
            'lancamentos': _monta_lancamentos(df.loc[idx_linhas]) if idx_linhas is not None else [],
        }
        debug['aplicados'].append({
            'representante': nome_rep, 'comissao': round(total, 2), 'qtd_regras': len(regras),
        })

    # 2º passe: % sobre a comissão de outros (gestor). Roda depois de todos os vendedores.
    for nome_rep, base_nome, regra, memoria in pendentes_2o_passe:
        alvos = _termos(regra.get('base_comissoes_de'))
        if not alvos:
            try:
                alvos = [
                    nome_base(v.representante_externo.nome)
                    for v in VinculoRepresentante.objects
                        .filter(ativo=True, representante_interno__nome__icontains=base_nome)
                        .select_related('representante_externo')
                ]
            except Exception:
                alvos = []

        base_com, detalhe = 0.0, []
        for chave, dados in resultado.items():
            if str(chave).startswith('_') or not isinstance(dados, dict) or 'comissao' not in dados:
                continue
            if nome_base(chave) == base_nome:
                continue
            if alvos and not any(a in nome_base(chave) for a in alvos):
                continue
            base_com += _f(dados.get('comissao'))
            detalhe.append({'vendedor': chave, 'comissao': _f(dados.get('comissao'))})

        taxa = _f(regra.get('taxa'))
        valor = _aplica_piso_teto(base_com * taxa * (_f(regra.get('multiplicador'), 1.0) or 1.0), regra)
        memoria['base'] = round(base_com, 2)
        memoria['componentes'] = sorted(detalhe, key=lambda x: -x['comissao'])
        memoria['passos'] = [{
            'texto': f"soma das comissões de {len(detalhe)} vendedor(es) = {_brl(base_com)} × {_pct(taxa)}",
            'base': round(base_com, 2), 'taxa': taxa, 'valor': round(valor, 2),
        }]
        memoria['valor'] = round(valor, 2)
        memoria.pop('segundo_passe', None)

        alvo = resultado.get(nome_rep)
        if isinstance(alvo, dict):
            alvo['comissao'] = round(_f(alvo.get('comissao')) + valor, 2)
            for item in debug['aplicados']:
                if item['representante'] == nome_rep:
                    item['comissao'] = alvo['comissao']

    return debug
