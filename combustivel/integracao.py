"""
Entrega dos abastecimentos do Manager ao SGA — o mesmo conteúdo em três formatos de arquivo
e na API de leitura por chave.

Os campos seguem o que o ``SgaAbastecimento.exe`` já grava em ``INTEGRACAOABASTECIMENTO``
quando busca no CTA Plus (registro, data, posto, bomba, equipamento, funcionário, item,
placa, horímetro, velocímetro, quantidade), para a Minerion só precisar trocar a ORIGEM:

* ``codigo``       → IABCODAB (volta em BAIXAESTOQUE.BESTIAB, é como sabemos que baixou)
* ``equipamento``  → EQPCOD (o SGA casa por EQPIDENTIAB; nos 681 equipamentos identificados ele é o próprio código)
* ``funcionario``  → FUNCOD (casa por FUNIDENTIAB)
* ``item``         → PEFITEMIAB do produto (10 = S-10, 500 = S-500, 32 = ARLA); ``item_sga`` = ESTQCOD
"""
import csv
import hashlib
import io
import json
from decimal import Decimal

from django.utils import timezone

from .models import PRODUTOS

VERSAO_LAYOUT = '1.0'
EMPRESA = 1

# (campo, descrição, largura no TXT, tipo) — a ordem é a das colunas.
CAMPOS = [
    ('codigo', 'Código do abastecimento (IABCODAB)', 10, 'inteiro'),
    ('data_hora', 'Data e hora do abastecimento (AAAA-MM-DD HH:MM:SS, horário de Brasília)', 19, 'data'),
    ('empresa', 'Empresa no SGA', 3, 'inteiro'),
    ('filial', 'Filial do tanque', 3, 'inteiro'),
    ('posto', 'Posto (0 = tanque próprio)', 6, 'inteiro'),
    ('bomba', 'Identificação da bomba/tanque', 10, 'texto'),
    ('equipamento', 'Equipamento (EQPCOD / EQPIDENTIAB)', 10, 'inteiro'),
    ('funcionario', 'Quem abasteceu (FUNCOD / FUNIDENTIAB)', 10, 'inteiro'),
    ('item', 'Item na integração (PEFITEMIAB: 10, 500, 32)', 6, 'texto'),
    ('item_sga', 'Item no estoque (ESTQCOD)', 8, 'inteiro'),
    ('placa', 'Placa', 8, 'texto'),
    ('horimetro', 'Horímetro', 12, 'decimal1'),
    ('km', 'Velocímetro / km', 12, 'decimal1'),
    ('quantidade', 'Litros', 10, 'decimal3'),
    ('encerrante_inicial', 'Encerrante inicial da bomba', 14, 'decimal2'),
    ('encerrante_final', 'Encerrante final da bomba', 14, 'decimal2'),
    ('centro_custo', 'Centro de custo (CCCOD)', 8, 'inteiro'),
]


def registro(ab) -> dict:
    """Um abastecimento no layout da integração (valores já no tipo final, sem formatação)."""
    local = timezone.localtime(ab.abastecido_em)
    return {
        'codigo': ab.codigo_integracao,
        'data_hora': local.strftime('%Y-%m-%d %H:%M:%S'),
        'empresa': EMPRESA,
        'filial': ab.tanque.filial,
        'posto': 0,
        'bomba': ab.tanque.bomba_ident or str(ab.tanque_id),
        'equipamento': ab.equipamento,
        'funcionario': ab.funcionario,
        'item': PRODUTOS.get(ab.tanque.produto, {}).get('ident', ''),
        'item_sga': ab.tanque.produto,
        'placa': (ab.placa or '').replace('-', '').upper(),
        'horimetro': ab.horimetro,
        'km': ab.km,
        'quantidade': ab.litros,
        'encerrante_inicial': ab.encerrante_inicial,
        'encerrante_final': ab.encerrante_final,
        'centro_custo': ab.centro_custo,
    }


def _texto(valor, tipo) -> str:
    if valor is None or valor == '':
        return ''
    if tipo.startswith('decimal'):
        casas = int(tipo[-1])
        return f'{Decimal(valor):.{casas}f}'
    return str(valor)


def _json_padrao(v):
    if isinstance(v, Decimal):
        return float(v)
    raise TypeError(type(v))


def gerar_csv(registros: list[dict]) -> bytes:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=';', lineterminator='\r\n')
    escritor.writerow([c[0] for c in CAMPOS])
    for r in registros:
        escritor.writerow([_texto(r[c], tipo) for c, _, _, tipo in CAMPOS])
    return saida.getvalue().encode('utf-8')


def gerar_txt(registros: list[dict]) -> bytes:
    """
    Layout fixo: linha ``H`` (cabeçalho), uma ``D`` por abastecimento e ``T`` (total) no fim.
    Números alinhados à direita com zeros, texto à esquerda com espaços — o formato que
    sistemas Delphi costumam ler sem biblioteca.
    """
    linhas = [f'H{VERSAO_LAYOUT:<5}{timezone.localtime():%Y%m%d%H%M%S}{len(registros):08d}']
    total = Decimal('0')
    for r in registros:
        partes = ['D']
        for campo, _, largura, tipo in CAMPOS:
            valor = _texto(r[campo], tipo)
            if tipo == 'data':
                valor = valor.replace('-', '').replace(':', '').replace(' ', '')  # AAAAMMDDHHMMSS
                partes.append(f'{valor:<{largura}}')
            elif tipo == 'texto':
                partes.append(f'{valor[:largura]:<{largura}}')
            else:
                partes.append(f'{valor or "0":0>{largura}}'[-largura:])
        total += Decimal(r['quantidade'] or 0)
        linhas.append(''.join(partes))
    linhas.append(f'T{len(registros):08d}{total:015.3f}')
    return ('\r\n'.join(linhas) + '\r\n').encode('latin-1', errors='replace')


def gerar_json(registros: list[dict]) -> bytes:
    corpo = {
        'layout': VERSAO_LAYOUT,
        'gerado_em': timezone.localtime().isoformat(),
        'empresa': EMPRESA,
        'quantidade': len(registros),
        'litros': float(sum(Decimal(r['quantidade'] or 0) for r in registros)),
        'abastecimentos': registros,
    }
    return json.dumps(corpo, default=_json_padrao, ensure_ascii=False, indent=2).encode('utf-8')


GERADORES = {'CSV': (gerar_csv, 'csv', 'text/csv'), 'TXT': (gerar_txt, 'txt', 'text/plain'),
             'JSON': (gerar_json, 'json', 'application/json')}


def gerar(formato: str, registros: list[dict]) -> tuple[bytes, str, str, str]:
    """Devolve ``(conteudo, extensao, content_type, sha256)``."""
    funcao, ext, tipo = GERADORES[formato]
    conteudo = funcao(registros)
    return conteudo, ext, tipo, hashlib.sha256(conteudo).hexdigest()


def documentacao() -> dict:
    """O que a tela de integração mostra (e o que mandamos para a Minerion)."""
    return {
        'versao': VERSAO_LAYOUT,
        'campos': [{'campo': c, 'descricao': d, 'largura_txt': l, 'tipo': t} for c, d, l, t in CAMPOS],
        'api': {
            'autenticacao': 'Cabeçalho  Authorization: Chave <prefixo>.<segredo>  (HTTPS obrigatório)',
            'buscar': 'GET /combustivel/integracao/abastecimentos/?depois_de=<codigo>&limite=500',
            'confirmar': 'POST /combustivel/integracao/confirmar/  '
                         '[{"codigo": 1500000123, "baixa": 761930}] ou [{"codigo": ..., "erro": "texto"}]',
            'observacao': 'Os registros saem em ordem crescente de código. Guardar o maior código recebido e '
                          'mandar em depois_de na próxima busca. A confirmação é opcional: o Manager também '
                          'reconhece a baixa sozinho, procurando o código em BAIXAESTOQUE.BESTIAB.',
        },
    }
