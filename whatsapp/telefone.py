"""
O mesmo celular escrito de várias formas.

Vive num módulo próprio, e não em `services`, porque o `graph_api` precisa dele
para normalizar o destinatário na hora de enviar — e `services` importa
`graph_api`, então a ida de volta seria import circular. Aqui não se importa
nada do app: é só string.
"""

# DDDs que existem de verdade no Brasil. A lista importa em `telefone_para_envio`:
# sem ela, um número estrangeiro de 10 dígitos (um americano, por exemplo) tem a
# mesma cara de um fixo brasileiro e ganharia um `55` na frente, virando o
# telefone de outra pessoa. Com a lista, só ganha DDI o que tem DDD de verdade.
DDDS_BRASIL = frozenset({
    '11', '12', '13', '14', '15', '16', '17', '18', '19',
    '21', '22', '24', '27', '28',
    '31', '32', '33', '34', '35', '37', '38',
    '41', '42', '43', '44', '45', '46', '47', '48', '49',
    '51', '53', '54', '55',
    '61', '62', '63', '64', '65', '66', '67', '68', '69',
    '71', '73', '74', '75', '77', '79',
    '81', '82', '83', '84', '85', '86', '87', '88', '89',
    '91', '92', '93', '94', '95', '96', '97', '98', '99',
})

DDI_BRASIL = '55'


def so_digitos(telefone) -> str:
    return ''.join(c for c in str(telefone or '') if c.isdigit())


def _tem_forma_nacional(nacional: str) -> bool:
    """Este número, sem DDI, parece um telefone brasileiro completo?"""
    ddd, assinante = nacional[:2], nacional[2:]
    if ddd not in DDDS_BRASIL:
        return False
    if len(assinante) == 9 and assinante[0] == '9' and '6' <= assinante[1] <= '9':
        return True                                   # celular atual
    if len(assinante) == 8 and '2' <= assinante[0] <= '9':
        return True                                   # fixo, ou celular antigo
    return False


def telefone_para_envio(telefone) -> str:
    """
    A forma que vai no campo `to` da Cloud API: dígitos com DDI.

    Existe por causa de um defeito caro. A agenda tinha contatos gravados SEM o
    código do país — `51992393150` em vez de `5551992393150`. A Cloud API não
    adivinha país: ela lê os dígitos da frente como DDI, e **51 é o Peru**. Pior,
    `992393150` tem nove dígitos começando em 9, que é celular peruano válido —
    então a Meta aceita o POST, tenta entregar no Peru, não acha conta e devolve
    `131026 Message Undeliverable`. A falha é assíncrona e muda: o atendente só
    via "falhou" e reenviava.

    Isso explica por que só apareceu em DDD 51: o DDD tinha que colidir com um
    DDI existente para o número virar outro país. DDD 55 sem o `55` na frente é
    lido como Brasil e passa por acaso.

    O que esta função faz é UMA coisa: garantir o DDI. Ela não põe nem tira o
    nono dígito — isso é decisão do `variantes_telefone`, e só depois de uma
    entrega falhar, quando já se sabe que a forma gravada não serve. Trocar o
    nono dígito por conta própria no caminho normal mudaria o destinatário de
    mensagens que hoje funcionam.

    Número que não tem forma brasileira sai como entrou: um alemão ou um
    americano com DDI próprio não pode ganhar `55` na frente.
    """
    digitos = so_digitos(telefone)
    if not digitos:
        return ''

    # Já tem DDI do Brasil e o resto tem cara de telefone daqui: nada a fazer.
    if (digitos.startswith(DDI_BRASIL)
            and len(digitos) in (12, 13)
            and _tem_forma_nacional(digitos[2:])):
        return digitos

    if len(digitos) in (10, 11) and _tem_forma_nacional(digitos):
        return DDI_BRASIL + digitos

    return digitos


def variantes_telefone(telefone) -> list:
    """
    Todas as formas com que ESTE telefone pode estar gravado no banco.

    Duas transformações, e só elas: pôr/tirar o `55` e pôr/tirar o nono dígito.

    O nono dígito só entra em CELULAR — assinante de 8 dígitos começando em 6..9.
    Fixo começa em 2..5, e enfiar um 9 num fixo produziria o número de OUTRA
    PESSOA: 54 3333-4444 (fixo) viraria 54 9 3333-4444, que existe e é de outro
    alguém. Casar a conversa errada é bem pior que abrir uma conversa a mais,
    então na dúvida não se expande — é por isso que número que não tem forma
    brasileira (DDD ou assinante fora do padrão) sai daqui como entrou.
    """
    digitos = so_digitos(telefone)
    if not digitos:
        return []

    nacional = digitos[2:] if digitos.startswith('55') and len(digitos) in (12, 13) else digitos
    ddd, assinante = nacional[:2], nacional[2:]
    if not ('11' <= ddd <= '99'):
        return [digitos]

    if len(assinante) == 9 and assinante[0] == '9' and '6' <= assinante[1] <= '9':
        curtas = {nacional, ddd + assinante[1:]}          # celular, sem o nono
    elif len(assinante) == 8 and '6' <= assinante[0] <= '9':
        curtas = {nacional, ddd + '9' + assinante}        # celular antigo, com o nono
    elif len(assinante) == 8 and '2' <= assinante[0] <= '5':
        curtas = {nacional}                               # fixo: só o 55 varia
    else:
        return [digitos]

    formas = {digitos}
    for forma in curtas:
        formas.add(forma)
        formas.add('55' + forma)
    return sorted(formas)


def outra_variante_de_envio(telefone) -> str:
    """
    A forma alternativa para retentar uma entrega que falhou.

    Só existe para celular: é o mesmo número com o nono dígito posto (se faltava)
    ou tirado (se havia), sempre com DDI. Devolve `''` quando não há alternativa
    — fixo, estrangeiro, ou número que não casa com nenhum padrão.

    Não serve para o envio normal, e sim para o retry depois de `131026`: aí já
    se sabe que a forma gravada NÃO entrega, então tentar a outra não custa
    entrega nenhuma.
    """
    atual = telefone_para_envio(telefone)
    if not atual.startswith(DDI_BRASIL) or len(atual) not in (12, 13):
        return ''

    nacional = atual[2:]
    ddd, assinante = nacional[:2], nacional[2:]
    if ddd not in DDDS_BRASIL:
        return ''

    if len(assinante) == 9 and assinante[0] == '9' and '6' <= assinante[1] <= '9':
        return DDI_BRASIL + ddd + assinante[1:]           # tira o nono
    if len(assinante) == 8 and '6' <= assinante[0] <= '9':
        return DDI_BRASIL + ddd + '9' + assinante         # põe o nono
    return ''                                             # fixo não tem variante


def chave_telefone(telefone) -> str:
    """
    Uma forma só por celular, para agrupar (agenda, contagens).

    É a mais longa das variantes — com o 55 e com o nono dígito. Não serve para
    ENVIAR (para isso vale `telefone_para_envio`), só para dizer "estes dois
    registros são a mesma pessoa".
    """
    formas = variantes_telefone(telefone)
    return max(formas, key=len) if formas else ''
