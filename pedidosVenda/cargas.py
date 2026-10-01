"""
Painel de cargas: leitura do SGA, sem gravar nada (levantado em 01/10/2026).

A carga é montada SÓ no SGA, pelo vendas interno; o painel acompanha:

- **Pedido aguardando carga**: `PEDSIT = 0` (o único que gera nota) com saldo
  `IPEDQUANT − IPEDQUANTDESP − IPEDQUANTCANC` e sem carregamento pendente.
- **Carregamento** (aba F1 da Emissão de NF): `NOTAFISCAL` com `NFSIT = 0`. O
  `NFNUM` é NEGATIVO e é o nº do carregamento (873892 ⇒ −873892); na emissão
  vira o número da nota e `NFSIT = 1`. `NFDATA` fica 1899 até emitir — a data
  de criação é `NFDATACHEGADA`. Há centenas de `NFSIT = 0` abandonados desde
  2012, por isso a janela de dias.
- **Carga composta** (aba F2): `CARGAFRAC` agrupa carregamentos via
  `ITEMCARGAFRAC.ICARFNFCOD`. `CARFDATA` é a data prevista, `CARFSIT` 0 aberta,
  1 encerrada. Uns 45% das notas saem sem carga composta (retira, avulso).
- Pesos em toneladas na nota (`NFPESOTOT`, `NFTARA`, `NFBRUTO`); `IPEDPESOTOT`
  do pedido é em kg. Caminhão chegou = placa ou tara preenchida.
"""
from datetime import date, timedelta

from . import erp

ETAPAS = ('AGUARDANDO', 'PROGRAMADO', 'NO_PATIO', 'FATURADO')
TIPO_CARGA = {1: 'Remeter', 2: 'Retira', 3: 'Retorno'}

_CIDADE = """(SELECT CI.CIDNOME + '-' + ES.ESTUF FROM CIDADE CI JOIN ESTADO ES ON ES.ESTCOD = CI.CIDEST
              WHERE CI.CIDCOD = CASE WHEN ISNULL(E.ECLICIDADE, 0) > 0 THEN E.ECLICIDADE ELSE C.CLICIDADE END)"""


def _filtro_reps(coluna: str, repcods: list[int] | None) -> str:
    """None = sem filtro (gestão/interno); lista vazia = não vê nada."""
    if repcods is None:
        return ''
    reps = erp._inteiros(repcods) or [-1]
    return f"AND {coluna} IN ({','.join(str(r) for r in reps)})"


def _filtro_filial(coluna: str, filial: int | None) -> str:
    return '' if filial is None else f'AND {coluna} = {int(filial)}'


def _notas(where: str, **params) -> list[dict]:
    """Carregamentos/notas com cliente, destino, veículo e a carga composta (se houver)."""
    linhas = erp._limpar(erp._rows(f"""
        SELECT N.NFCOD cod, N.NFNUM num, N.NFSIT sit, N.NFFIL filial, N.NFPED pedido,
               N.NFDATA emitida_em, N.NFDATACHEGADA criado_em,
               CONVERT(varchar(5), N.NFDATA, 108) hora_emissao,
               N.NFCLI cliente_cod, C.CLINOME cliente, C.CLINOMEFANT fantasia, {_CIDADE} cidade,
               N.NFREP repcod, R.REPNOME vendedor,
               LTRIM(RTRIM(ISNULL(N.NFPLACA, ''))) placa, M.MOTNOME motorista, M.MOTCELULAR motorista_celular,
               T.TRANNOME transportador,
               N.NFPESOTOT peso, N.NFTARA tara, N.NFBRUTO bruto, N.NFLIMITEPESO limite_peso, N.NFTOTAL total,
               F.CARFCOD carga_cod, F.CARFDESC carga_desc, F.CARFDATA carga_data, F.CARFTPCARF carga_tipo,
               (SELECT TOP 1 ES2.ESTQNOME FROM ITEMNOTAFISCAL I2 JOIN ESTOQUE ES2 ON ES2.ESTQCOD = I2.INFESTQ
                 WHERE I2.INFNFCOD = N.NFCOD ORDER BY I2.INFQUANT DESC) produto,
               (SELECT COUNT(*) FROM ITEMNOTAFISCAL I3 WHERE I3.INFNFCOD = N.NFCOD) qtd_itens
        FROM NOTAFISCAL N
        JOIN CLIENTE C ON C.CLICOD = N.NFCLI
        LEFT JOIN ENDERECOCLIENTE E ON E.ECLICLI = N.NFCLI AND E.ECLICOD = N.NFECLI AND N.NFECLI > 0
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = N.NFREP
        LEFT JOIN MOTORISTA M ON M.MOTCOD = N.NFMOT AND N.NFMOT > 0
        LEFT JOIN TRANSPORTADOR T ON T.TRANCOD = N.NFTRAN AND N.NFTRAN > 0
        LEFT JOIN ITEMCARGAFRAC IC ON IC.ICARFNFCOD = N.NFCOD
        LEFT JOIN CARGAFRAC F ON F.CARFCOD = IC.ICARFCARF
        WHERE N.NFEMP = :emp {where}
    """, emp=erp.EMPRESA, **params))
    for l in linhas:
        l['peso'] = round(float(l['peso'] or 0), 3)
        l['tara'] = round(float(l['tara'] or 0), 3)
        l['bruto'] = round(float(l['bruto'] or 0), 3)
        l['carga_tipo'] = TIPO_CARGA.get(l['carga_tipo']) if l['carga_tipo'] else None
        # _limpar reduz datetime a data; a hora da emissão vai à parte (ordem das faturadas e TV).
        if l['sit'] != 1:
            l['hora_emissao'] = None
        if l['sit'] == 1:
            l['etapa'] = 'FATURADO'
            l['carregamento'] = None
            l['nota'] = l['num']
        else:
            l['etapa'] = 'NO_PATIO' if (l['placa'] or l['tara'] > 0) else 'PROGRAMADO'
            l['carregamento'] = abs(l['num'] or 0)
            l['nota'] = None
        # Tara pesada: líquido = bruto − tara. Sem tara, o "bruto" do carregamento é o programado.
        l['liquido'] = round(l['bruto'] - l['tara'], 3) if l['tara'] > 0 else None
    return linhas


def carregamentos_pendentes(filial=None, repcods=None, dias=45) -> list[dict]:
    return _notas(
        f"AND N.NFSIT = 0 AND N.NFNUM < 0 AND N.NFDATACHEGADA >= :desde "
        f"{_filtro_filial('N.NFFIL', filial)} {_filtro_reps('N.NFREP', repcods)}",
        desde=date.today() - timedelta(days=int(dias)),
    )


def faturados(inicio: date, fim: date, filial=None, repcods=None) -> list[dict]:
    return _notas(
        f"AND N.NFSIT = 1 AND N.NFDATA >= :ini AND N.NFDATA < :fim "
        f"{_filtro_filial('N.NFFIL', filial)} {_filtro_reps('N.NFREP', repcods)}",
        ini=inicio, fim=fim + timedelta(days=1),
    )


def pedidos_aguardando(filial=None, repcods=None, dias=120) -> list[dict]:
    """Pedido ativo com saldo e sem carregamento pendente: ainda não foi programado."""
    linhas = erp._limpar(erp._rows(f"""
        WITH S AS (
            SELECT I.IPEDPED ped,
                   SUM(I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0)) saldo_qtd,
                   SUM(CASE WHEN I.IPEDQUANT > 0
                            THEN I.IPEDPESOTOT * (I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0)) / I.IPEDQUANT
                            ELSE 0 END) saldo_kg,
                   SUM(I.IPEDUNIT * (I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0))) saldo_valor,
                   SUM(I.IPEDQUANTDESP) despachado,
                   COUNT(*) itens
            FROM ITEMPEDIDO I
            WHERE I.IPEDQUANT - I.IPEDQUANTDESP - ISNULL(I.IPEDQUANTCANC, 0) > 0.001
            GROUP BY I.IPEDPED
        )
        SELECT P.PEDNUM pedido, P.PEDDATA data, P.PEDDATAPREV previsao, P.PEDFIL filial,
               P.PEDCLI cliente_cod, C.CLINOME cliente, C.CLINOMEFANT fantasia, {_CIDADE} cidade,
               P.PEDREP repcod, R.REPNOME vendedor, P.PEDPGTOFOBCIF fob_cif,
               S.saldo_kg, S.saldo_valor, S.itens, S.despachado,
               (SELECT TOP 1 ES2.ESTQNOME FROM ITEMPEDIDO I2 JOIN ESTOQUE ES2 ON ES2.ESTQCOD = I2.IPEDESTQ
                 WHERE I2.IPEDPED = P.PEDNUM AND I2.IPEDQUANT - I2.IPEDQUANTDESP - ISNULL(I2.IPEDQUANTCANC, 0) > 0.001
                 ORDER BY I2.IPEDPESOTOT DESC) produto
        FROM PEDIDO P
        JOIN S ON S.ped = P.PEDNUM
        JOIN CLIENTE C ON C.CLICOD = P.PEDCLI
        LEFT JOIN ENDERECOCLIENTE E ON E.ECLICLI = P.PEDCLI AND E.ECLICOD = P.PEDECLI AND P.PEDECLI > 0
        LEFT JOIN REPRESENTANTE R ON R.REPCOD = P.PEDREP
        WHERE P.PEDSIT = 0 AND P.PEDEMP = :emp AND P.PEDDATA >= :desde AND P.PEDDATA <= :hoje
          AND NOT EXISTS (SELECT 1 FROM NOTAFISCAL N WHERE N.NFPED = P.PEDNUM AND N.NFSIT = 0 AND N.NFNUM < 0)
          {_filtro_filial('P.PEDFIL', filial)} {_filtro_reps('P.PEDREP', repcods)}
        ORDER BY P.PEDDATA
    """, emp=erp.EMPRESA, desde=date.today() - timedelta(days=int(dias)), hoje=date.today() + timedelta(days=1)))
    hoje = date.today()
    for l in linhas:
        l['peso'] = round(float(l.pop('saldo_kg') or 0) / 1000, 3)
        l['saldo_valor'] = round(float(l['saldo_valor'] or 0), 2)
        l['parcial'] = float(l.pop('despachado') or 0) > 0
        l['etapa'] = 'AGUARDANDO'
        l['dias_esperando'] = (hoje - date.fromisoformat(l['data'])).days if l['data'] else None
    return linhas


def agrupar_cargas(notas: list[dict]) -> list[dict]:
    """Junta os carregamentos/notas da mesma carga composta; avulsos viram carga de um só."""
    cargas: dict[str, dict] = {}
    for n in notas:
        chave = f"c{n['carga_cod']}" if n['carga_cod'] else f"n{n['cod']}"
        c = cargas.get(chave)
        if c is None:
            c = cargas[chave] = {
                'chave': chave, 'cod': n['carga_cod'], 'composta': bool(n['carga_cod']),
                'descricao': n['carga_desc'] or n['cliente'], 'data': n['carga_data'] or (n['criado_em'] or '')[:10] or None,
                'tipo': n['carga_tipo'], 'filial': n['filial'], 'placa': '', 'motorista': None,
                'transportador': None, 'peso': 0.0, 'total': 0.0, 'notas': [],
            }
        c['notas'].append(n)
        c['peso'] = round(c['peso'] + n['peso'], 3)
        c['total'] = round(c['total'] + float(n['total'] or 0), 2)
        c['placa'] = c['placa'] or n['placa']
        c['motorista'] = c['motorista'] or n['motorista']
        c['transportador'] = c['transportador'] or n['transportador']
    for c in cargas.values():
        etapas = {n['etapa'] for n in c['notas']}
        # A carga anda junto com o caminhão: tudo faturado ⇒ faturada; algum pesado/placa ⇒ no pátio.
        if etapas == {'FATURADO'}:
            c['etapa'] = 'FATURADO'
        elif 'NO_PATIO' in etapas or ('FATURADO' in etapas and c['placa']):
            c['etapa'] = 'NO_PATIO'
        else:
            c['etapa'] = 'PROGRAMADO'
        c['faturadas'] = sum(1 for n in c['notas'] if n['etapa'] == 'FATURADO')
        c['clientes'] = len({n['cliente_cod'] for n in c['notas']})
    return sorted(cargas.values(), key=lambda c: (c['data'] or '9999', c['descricao'] or ''))


def painel(inicio: date, fim: date, filial=None, repcods=None, com_aguardando=True) -> dict:
    pendentes = carregamentos_pendentes(filial, repcods)
    fat = faturados(inicio, fim, filial, repcods)
    # Carga composta com parte faturada no período e parte pendente: as duas metades se juntam.
    cargas = agrupar_cargas(pendentes + fat)
    return {
        'cargas': cargas,
        'aguardando': pedidos_aguardando(filial, repcods) if com_aguardando else [],
        'inicio': inicio.isoformat(),
        'fim': fim.isoformat(),
    }
