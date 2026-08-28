"""Regras de negócio desacopladas da ingestão do webhook (fácil de trocar por NLP no futuro)."""
import unicodedata
import logging
import re

from django.conf import settings
from django.utils import timezone

from django.db.models import Q

from .models import ConfiguracaoAtendimento, Fila, Mensagem, WhatsAppNotificacao
from . import graph_api

logger = logging.getLogger(__name__)

# Quantas vezes o menu é mandado antes de jogar o cliente na fila padrão.
TENTATIVAS_MAXIMAS = 3

# ── Escopos de atendimento (RH x TI) ─────────────────────────────────────────
#
# Cada NÚMERO de WhatsApp é um atendimento separado, e o escopo de uma conversa
# é o número por onde ela entrou: currículo e atestado que chegam no número do
# RH não são assunto de quem atende chamado de TI, e vice-versa.
#
# Por grupo do Django (django.contrib.auth.Group):
#   RHWhatsapp    → atendente do RH: vê só as conversas do número do RH que
#                   estão COM ELE ou ainda SEM DONO (para assumir). O RH trata
#                   de atestado, salário e desligamento — assunto que não é do
#                   colega de fila.
#   TIWhatsapp    → atendente da TI: vê TODAS as conversas do número da TI. O
#                   chamado de TI é da equipe, e quem pega é quem está livre.
#   GestorWhatsapp   → gestor do RH: todas as conversas do RH.
#   GestorWhatsappTI → gestor da TI: todas as conversas da TI.
#
# `compartilhado` é o que separa os dois comportamentos: ligado, o atendimento
# inteiro é visível para a equipe daquele número.
#
# Quem não está em nenhum desses grupos continua na regra antiga (as filas de
# que participa), para ninguém ficar sem atendimento por cadastro não feito.
# `apelidos` são os nomes que o número tem no admin. O número principal chama-se
# "Atendimento" (é o rótulo que aparece na Central), não "TI" — sem o apelido o
# escopo não casaria com número nenhum.
ESCOPOS = {
    'RH': {'gestor': 'GestorWhatsapp', 'atendentes': 'RHWhatsapp',
           'apelidos': ('RH', 'Recursos Humanos'), 'compartilhado': False},
    'TI': {'gestor': 'GestorWhatsappTI', 'atendentes': 'TIWhatsapp',
           'apelidos': ('TI', 'Atendimento', 'Setor TI'), 'compartilhado': True},
}

# Mantido para o resto do código (disparo em massa, admin): gestor de QUALQUER
# escopo. Para "gestor DESTE atendimento", use `eh_gestor_de`.
GRUPO_GESTOR = 'GestorWhatsapp'
GRUPOS_GESTORES = tuple(cfg['gestor'] for cfg in ESCOPOS.values())


def _chave_escopo(texto) -> str:
    """Nome comparável: sem acento, sem espaço nas pontas, minúsculo.

    Não reaproveita o `_sem_acento` lá de baixo de propósito — aquele preserva a
    caixa (é usado no primeiro nome do atendente) e "RH" nunca casaria com "rh".
    """
    normalizado = unicodedata.normalize('NFKD', (texto or '').strip().lower())
    return ''.join(c for c in normalizado if not unicodedata.combining(c))


def numeros_do_escopo(escopo: str) -> list:
    """
    Ids de `NumeroNegocio` do escopo.

    O casamento é pelo NOME cadastrado no admin ("RH", "TI") — é o único vínculo
    que existe hoje entre grupo e número. Para um cadastro que não possa ser
    renomeado, `settings.WHATSAPP_NUMEROS_POR_ESCOPO` aceita outros nomes ou o
    próprio `phone_number_id`:

        WHATSAPP_NUMEROS_POR_ESCOPO = {'RH': ['Recursos Humanos', '1356992644155626']}

    `manage.py whatsapp_escopos` mostra como está resolvendo hoje.
    """
    from .models import NumeroNegocio

    configurados = (getattr(settings, 'WHATSAPP_NUMEROS_POR_ESCOPO', None) or {}).get(escopo) or []
    apelidos = {_chave_escopo(escopo)}
    apelidos |= {_chave_escopo(a) for a in ESCOPOS.get(escopo, {}).get('apelidos', ())}
    apelidos |= {_chave_escopo(a) for a in configurados}
    return [
        numero.id for numero in NumeroNegocio.objects.all()
        if _chave_escopo(numero.nome) in apelidos or (numero.phone_number_id or '') in configurados
    ]


def _numero_padrao_id():
    """Número que atende quem não escolheu setor — dono das conversas antigas."""
    from .models import NumeroNegocio

    padrao = NumeroNegocio.objects.filter(is_padrao=True, ativo=True).first()
    return padrao.id if padrao else None


def escopo_do_numero(numero_id) -> str:
    """'RH' / 'TI' / '' quando o número não casa com escopo nenhum."""
    numero_id = numero_id or _numero_padrao_id()
    if numero_id is None:
        return ''
    for escopo in ESCOPOS:
        if numero_id in numeros_do_escopo(escopo):
            return escopo
    return ''


def escopo_da_conversa(conversa) -> str:
    """
    'RH' / 'TI' / '' quando o número da conversa não casa com escopo nenhum.

    Conversa anterior ao 2º número não tem `numero` preenchido: ela é do
    atendimento padrão, não de todo mundo.
    """
    return escopo_do_numero(conversa.numero_id)


def escopo_compartilhado(escopo: str) -> bool:
    """TI: a equipe toda enxerga o atendimento. RH: cada um vê o que é seu."""
    return bool(ESCOPOS.get(escopo, {}).get('compartilhado'))


def escopos_do_usuario(usuario) -> dict:
    """`{'RH': 'gestor'}` / `{'TI': 'atendente'}` — vazio para quem está fora dos grupos."""
    if not usuario or not usuario.is_authenticated:
        return {}
    grupos = set(usuario.groups.values_list('name', flat=True))
    papeis = {}
    for escopo, cfg in ESCOPOS.items():
        if cfg['gestor'] in grupos:
            papeis[escopo] = 'gestor'
        elif cfg['atendentes'] in grupos:
            papeis[escopo] = 'atendente'
    return papeis


def eh_gestor(usuario) -> bool:
    """Gestor de algum atendimento (ou staff). Não diz de qual — veja `eh_gestor_de`."""
    if not usuario or not usuario.is_authenticated:
        return False
    return usuario.is_staff or usuario.groups.filter(name__in=GRUPOS_GESTORES).exists()


def eh_gestor_de(usuario, escopo: str) -> bool:
    if not usuario or not usuario.is_authenticated:
        return False
    if usuario.is_staff:
        return True
    grupo = ESCOPOS.get(escopo, {}).get('gestor')
    return bool(grupo) and usuario.groups.filter(name=grupo).exists()


def filtro_de_conversas(usuario):
    """
    `Q` do que este usuário enxerga — `None` quando enxerga tudo (staff).

    Gestor: tudo do seu número. Atendente: do seu número, o que é dele ou o que
    ainda não tem dono — senão ninguém conseguiria puxar chamado novo.
    """
    if usuario.is_staff:
        return None

    papeis = escopos_do_usuario(usuario)
    if not papeis:
        return Q(fila__membros=usuario)      # regra antiga

    padrao_id = _numero_padrao_id()
    filtro = Q(pk__in=[])                    # nada, até algum escopo somar
    for escopo, papel in papeis.items():
        numeros = numeros_do_escopo(escopo)
        if not numeros:
            # Escopo sem número casado (nome trocado no admin, cadastro novo).
            # Cai para a fila, MAS o atendente continua restrito ao que é dele ou
            # ao que não tem dono: só a separação entre setores depende do número,
            # a regra pessoal não — senão um cadastro errado devolve o atendimento
            # inteiro para todo mundo, que é o defeito que isto veio corrigir.
            logger.warning('Escopo %s do WhatsApp não casou com nenhum NumeroNegocio.', escopo)
            pela_fila = Q(fila__membros=usuario)
            if papel != 'gestor' and not escopo_compartilhado(escopo):
                pela_fila &= (Q(responsavel=usuario) | Q(responsavel__isnull=True))
            filtro |= pela_fila
            continue

        do_escopo = Q(numero_id__in=numeros)
        if padrao_id in numeros:
            do_escopo |= Q(numero__isnull=True)

        if papel == 'gestor' or escopo_compartilhado(escopo):
            filtro |= do_escopo
        else:
            filtro |= do_escopo & (Q(responsavel=usuario) | Q(responsavel__isnull=True))
    return filtro


def conversas_visiveis(usuario, queryset=None):
    """Conversas que este usuário pode abrir. Use isto, nunca `Conversa.objects.all()`."""
    from .models import Conversa

    qs = Conversa.objects.all() if queryset is None else queryset
    filtro = filtro_de_conversas(usuario)
    return qs if filtro is None else qs.filter(filtro).distinct()


def pode_ver(usuario, conversa) -> bool:
    from .models import Conversa

    filtro = filtro_de_conversas(usuario)
    if filtro is None:
        return True
    return Conversa.objects.filter(filtro, pk=conversa.pk).exists()


def usuarios_para_avisar(conversa):
    """
    Quem recebe aviso desta conversa.

    Casa com quem consegue ABRI-LA: aviso para quem não pode ver vira badge que
    não abre nada. Sem responsável, avisa os atendentes do escopo que estão na
    fila; com responsável, avisa só ele. O gestor do escopo recebe sempre.
    """
    from django.contrib.auth.models import User

    escopo = escopo_da_conversa(conversa)
    if not escopo:
        # Número fora dos escopos: continua avisando a fila, como antes.
        return list(conversa.fila.membros.all()) if conversa.fila_id else []

    cfg = ESCOPOS[escopo]
    alvo = Q(groups__name=cfg['gestor'])
    if conversa.fila_id and (escopo_compartilhado(escopo) or not conversa.responsavel_id):
        # TI: o chamado é da equipe, todos são avisados. RH: só enquanto está sem
        # dono — depois de assumido o aviso é de quem assumiu.
        alvo |= Q(filas_whatsapp=conversa.fila_id, groups__name=cfg['atendentes'])
    if conversa.responsavel_id:
        alvo |= Q(pk=conversa.responsavel_id)
    return list(User.objects.filter(is_active=True).filter(alvo).distinct())


def marcar_avisos_lidos(conversa, usuario=None) -> int:

    """
    Dá baixa nos avisos pendentes de uma conversa.

    `lido` é pessoal: o badge de cada um conta o que ELE não leu, mesmo que um colega
    da mesma fila já tenha respondido. É por isso que todas as chamadas de dentro do
    atendimento passam `usuario` — a baixa coletiva (sem `usuario`) ficou disponível
    porque é o que faz sentido em manutenção/limpeza, não no fluxo do dia.

    O efeito colateral da regra pessoal: quem nunca abriu uma conversa que já foi
    encerrada continua com o aviso, e a conversa encerrada não aparece na lista de
    abertas. A saída é ver o arquivo da fila (o botão da caixa na Central) ou zerar a
    fila de uma vez em `marcar-fila-lida`.
    """
    qs = WhatsAppNotificacao.objects.filter(conversa=conversa, lido=False)
    if usuario is not None:
        qs = qs.filter(usuario_notificado=usuario)
    return qs.update(lido=True)


def pode_atender(usuario, conversa) -> bool:
    """
    Quem pode escrever, encerrar e abrir tarefa nesta conversa.

    Acompanha quem ENXERGA a conversa: gestor do escopo atende qualquer uma do
    seu número; atendente atende a que é dele e a que ainda não tem dono (é
    assim que ele assume). Fora dos escopos vale a regra antiga, a da fila.
    """
    if usuario.is_staff:
        return True

    escopo = escopo_da_conversa(conversa)
    papeis = escopos_do_usuario(usuario)
    if escopo and papeis:
        papel = papeis.get(escopo)
        if papel is None:
            return False                     # atendimento do outro número
        if papel == 'gestor' or escopo_compartilhado(escopo):
            return True
        return conversa.responsavel_id in (None, usuario.pk)

    if eh_gestor(usuario):
        return True
    if not (conversa.fila_id and conversa.fila.membros.filter(pk=usuario.pk).exists()):
        return False
    # Atendente dos grupos novos, com o número ainda sem escopo: vale a regra
    # pessoal, que não depende do cadastro do número.
    if papeis and not any(escopo_compartilhado(e) for e in papeis):
        return conversa.responsavel_id in (None, usuario.pk)
    return True


# ── Telefone: o mesmo celular escrito de várias formas ───────────────────────
#
# As transformações moraram aqui até o `graph_api` também precisar delas para
# normalizar o destinatário no envio. Como `services` importa `graph_api`, a ida
# de volta seria ciclo — então elas foram para `telefone.py`, que não importa
# nada do app. Continuam acessíveis como `services.x` porque é assim que o resto
# do módulo (views, tasks, testes) já as chamava.

from .telefone import (  # noqa: F401
    chave_telefone,
    outra_variante_de_envio,
    so_digitos,
    telefone_para_envio,
    variantes_telefone,
)


def filtro_telefone(telefone) -> Q:
    """`Q` que casa a conversa deste contato, escrita como estiver."""
    return Q(contato_telefone__in=variantes_telefone(telefone))


# ── Quem é avisado de mensagem nova ──────────────────────────────────────────

def membros_avisaveis(conversa) -> list:
    """
    Membros da fila que CONSEGUEM abrir esta conversa.

    O aviso de mensagem nova ia para `fila.membros.all()` inteira, sem passar
    pela visibilidade — então no RH, onde cada atendente só enxerga o que é dele
    ou o que está sem dono, a colega recebia badge de conversa que ela nem abre.
    Filtrar por `pode_ver` mantém a TI idêntica (lá o atendimento é compartilhado
    e todo membro passa) e conserta o RH sem regra nova.
    """
    if not conversa.fila_id:
        return []
    return [m for m in conversa.fila.membros.all() if pode_ver(m, conversa)]


def atendimento_pessoal_do_numero(numero_id) -> bool:
    """
    Neste número cada conversa tem dono (RH) ou é da equipe toda (TI)?

    Número fora dos escopos cai em `False`: sem cadastro, o comportamento
    continua o antigo, o compartilhado.
    """
    escopo = escopo_do_numero(numero_id)
    return bool(escopo) and not escopo_compartilhado(escopo)


def atendimento_pessoal(conversa) -> bool:
    return atendimento_pessoal_do_numero(conversa.numero_id)


def assumir_ao_responder(conversa, usuario) -> bool:
    """
    Quem responde passa a ser o responsável — só onde o atendimento é pessoal.

    No RH o atendente respondia sem clicar em "Assumir", e a conversa continuava
    com `responsavel` nulo: ficava marcada "Sem atendente" para a colega e seguia
    gerando aviso para as duas, mesmo já estando sendo atendida. Na TI nada muda
    de propósito — lá o chamado é da equipe e ninguém o toma para si ao responder.

    `UPDATE` condicional em vez de ler-e-salvar: duas respostas no mesmo instante,
    só a primeira leva.
    """
    from .models import Conversa

    if conversa.responsavel_id or not atendimento_pessoal(conversa):
        return False
    assumidas = (Conversa.objects
                 .filter(pk=conversa.pk, responsavel__isnull=True)
                 .update(responsavel=usuario))
    if assumidas:
        conversa.responsavel = usuario
    return bool(assumidas)


def _filas_ativas(numero=None):
    """
    Filas que ESTE número oferece no menu.

    Fila com `numero` nulo é compartilhada e aparece em todos; fila de outro
    número não aparece. Sem isso os setores do número de TI entrariam no menu do
    número do Comercial, e o cliente escolheria uma fila que ninguém daquele
    setor atende.
    """
    qs = Fila.objects.filter(ativa=True)
    if numero is not None:
        qs = qs.filter(Q(numero=numero) | Q(numero__isnull=True))
    return list(qs.order_by('ordem', 'nome'))


# ── Assinatura do atendimento ────────────────────────────────────────────────
# A Cloud API entrega tudo pelo número da empresa: o cliente vê "Grupo DB" e não
# tem como saber a que setor caiu. A assinatura só chega se for junto do conteúdo.
#
# A assinatura junta PESSOA e SETOR: "Ana Paula · Grupo DB RH". Só o setor era
# impessoal; só a pessoa fazia o cliente cobrar o atendente pelo nome e estranhar
# quando outro respondia. O rótulo do setor segue editável no admin
# (ConfiguracaoAtendimento.assinatura), então trocá-lo não exige deploy.

def assinatura_do_atendimento(numero=None) -> str:
    """Assinatura configurada; vazia desliga a assinatura por completo."""
    return (ConfiguracaoAtendimento.carregar(numero).assinatura or '').strip()


# Nomes compostos são a razão de isto não ser um `split()[0]`: "ANA PAULA DILHE
# LEAL" viraria "Ana". A lista é curta de propósito — errar para menos ("José"
# no lugar de "José Carlos") passa despercebido; errar para mais, não.
_PRIMEIROS_COMPOSTOS = {
    'ana', 'maria', 'jose', 'joao', 'luiz', 'luis', 'antonio', 'carlos',
    'paulo', 'pedro', 'francisco', 'marco', 'marcos', 'jean', 'joana', 'rosa',
}
_CONECTIVOS = {'de', 'da', 'do', 'das', 'dos', 'e'}


def _sem_acento(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )


def primeiro_nome(nome: str) -> str:
    """
    "ANA PAULA DILHE LEAL" -> "Ana Paula"; "MATHEUS SOARES MEDEIROS" -> "Matheus".

    O `capitalize()` existe porque boa parte do cadastro de Colaborador está em
    caixa alta, e assinar em CAIXA ALTA parece grito dentro da conversa.
    """
    partes = [p for p in (nome or '').split() if p]
    if not partes:
        return ''
    escolhidas = [partes[0]]
    if (len(partes) >= 3
            and _sem_acento(partes[0]).lower() in _PRIMEIROS_COMPOSTOS
            and _sem_acento(partes[1]).lower() not in _CONECTIVOS):
        escolhidas.append(partes[1])
    return ' '.join(p.capitalize() for p in escolhidas)


def nome_do_atendente(user) -> str:
    """
    O nome da pessoa, nunca o login: os usernames aqui são `anapaula.leal` e
    e-mails, que não servem para o cliente ler.

    A fonte é `Colaborador.nome` porque `User.first_name` está vazio em todos os
    atendentes. Quem não tem colaborador (conta de serviço, cadastro antigo)
    devolve vazio, e a assinatura fica só com o setor.
    """
    if user is None:
        return ''
    # Reverse OneToOne sem registro levanta RelatedObjectDoesNotExist, que o
    # Django faz herdar de AttributeError justamente para o getattr funcionar.
    colaborador = getattr(user, 'colaborador', None)
    if colaborador is not None and (colaborador.nome or '').strip():
        return primeiro_nome(colaborador.nome)
    if (user.first_name or '').strip():
        return primeiro_nome(user.first_name)
    return ''


def _deve_assinar(mensagem) -> bool:
    """
    Toda fala do atendente sai assinada; a do robô, não.

    Antes assinava só a primeira do atendimento e depois de horas paradas, para
    não repetir o rótulo. Passou a assinar sempre a pedido do atendimento: numa
    conversa longa, ou retomada de outro aparelho, o cliente rolava a tela e já
    não sabia com que setor estava falando.
    """
    return mensagem.autor_id is not None  # None é bot: menu de setores, roteamento


def assinar_para_cliente(texto: str, mensagem) -> str:
    """
    Devolve o texto como o cliente deve recebê-lo, com a assinatura do
    atendimento na frente quando for o caso.

    Aplicado só na saída para a Meta, de propósito: gravar o prefixo em
    `Mensagem.texto` duplicaria o rótulo na central, que já mostra o autor
    embaixo da bolha, e sujaria o resumo que vira tarefa no Kanban.
    """
    if not _deve_assinar(mensagem):
        return texto
    # O setor vem do número por onde a conversa entrou: com dois setores,
    # "Grupo DB TI" numa resposta do RH estaria errada.
    setor = assinatura_do_atendimento(mensagem.conversa.numero)
    pessoa = nome_do_atendente(mensagem.autor)
    nome = ' · '.join(parte for parte in (pessoa, setor) if parte)
    if not nome:
        return texto
    # Sem texto é legenda de mídia: aí a assinatura vai sozinha, sem os dois-pontos.
    return f'*{nome}:*\n{texto}' if (texto or '').strip() else f'*{nome}*'


def saudar_se_configurado(conversa) -> None:
    """
    Responde a saudação do número, quando há uma configurada.

    Chamada só no primeiro contato de um atendimento em número sem menu — é o
    equivalente, ali, ao menu de setores que o número com menu manda.

    Silenciosa por padrão: `texto_saudacao` nasce em branco, então nenhum número
    passa a falar sozinho só porque este código existe. Quem quiser saudação
    preenche o campo no admin, sem deploy.
    """
    texto = (ConfiguracaoAtendimento.carregar(conversa.numero).texto_saudacao or '').strip()
    if texto:
        responder_automatico(conversa, texto)


def montar_texto_menu(filas=None, numero=None) -> str:
    filas = filas if filas is not None else _filas_ativas(numero)
    linhas = [ConfiguracaoAtendimento.carregar(numero).texto_menu]
    for i, fila in enumerate(filas, start=1):
        linhas.append(f"{i} - {fila.nome}")
    return "\n".join(linhas)


def montar_texto_roteamento(fila, numero=None) -> str:
    """
    Confirmação de "você caiu no setor X", com o nome do setor no lugar de {setor}.

    Substituição literal em vez de `str.format`: o texto é digitado por gente no
    admin, e uma chave solta ou um `{Setor}` com maiúscula derrubariam o envio com
    KeyError — no meio de uma task do Celery, onde ninguém vê o erro. Sem o
    marcador o texto simplesmente sai como foi escrito.
    """
    modelo = ConfiguracaoAtendimento.carregar(numero).texto_roteamento
    return modelo.replace('{setor}', fila.nome)


def _registrar_saida_automatica(conversa, texto: str, envio, contexto: str, **campos) -> None:
    """
    Grava uma fala do robô no histórico e tenta entregá-la.

    O registro vem antes do envio de propósito: uma entrega que falha precisa
    deixar rastro na central, senão vira silêncio — o cliente não recebe nada e
    ninguém entende por quê.

    `envio` é a chamada ao Graph, passada como função porque o payload muda
    conforme o caminho (texto livre ou template). `autor` fica nulo em todos os
    casos — é o que distingue a fala do robô da de um atendente, sem precisar de
    campo novo no modelo.

    `ultima_mensagem_cliente_em` NÃO é tocado: só uma resposta do cliente reabre
    a janela de 24h, e nada que saia daqui conta como tal.
    """
    agora = timezone.now()
    mensagem = Mensagem.objects.create(
        conversa=conversa, direcao='SAIDA', tipo='TEXTO', texto=texto,
        autor=None, status_entrega='PENDENTE', **campos,
    )
    try:
        resposta = envio()
        mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
        mensagem.status_entrega = 'ENVIADA'
    except Exception as exc:
        logger.exception('%s (conversa_id=%s)', contexto, conversa.id)
        mensagem.status_entrega = 'FALHOU'
        mensagem.erro_detalhe = graph_api.detalhe_do_erro(exc)
    mensagem.save(update_fields=['wa_message_id', 'status_entrega', 'erro_detalhe'])

    conversa.ultima_mensagem_em = agora
    conversa.save(update_fields=['ultima_mensagem_em'])


def responder_automatico(conversa, texto: str) -> None:
    """
    Manda o texto pelo Graph e grava no histórico da conversa.

    Antes o bot chamava `graph_api.enviar_mensagem_texto` direto: o cliente
    recebia o menu, mas nada disso virava `Mensagem`. O atendente abria a central
    e via só as respostas do cliente ("1", "2"), sem a pergunta correspondente.
    """
    _registrar_saida_automatica(
        conversa, texto,
        lambda: graph_api.enviar_mensagem_texto(
            conversa.contato_telefone, texto, numero=conversa.numero),
        'Falha ao enviar resposta automática',
    )


def _enviar_menu(conversa, filas) -> None:
    """Manda o menu e contabiliza o envio — `tentativas_menu` é o que impede o loop."""
    conversa.tentativas_menu += 1
    conversa.save(update_fields=['tentativas_menu'])
    responder_automatico(conversa, montar_texto_menu(filas, conversa.numero))


def _notificar_membros(conversa, fila, tipo, texto_preview):
    """Aviso vai para quem enxerga a conversa, não para a fila inteira.

    Com a separação por número, membro de fila compartilhada podia receber badge
    de conversa do outro atendimento — que ele abre e leva 404.
    """
    notificacoes = [
        WhatsAppNotificacao(conversa=conversa, usuario_notificado=usuario, tipo=tipo, mensagem=texto_preview)
        for usuario in usuarios_para_avisar(conversa)
    ]
    if notificacoes:
        WhatsAppNotificacao.objects.bulk_create(notificacoes)


def _resolver_por_opcao_ou_palavra_chave(texto: str, filas):
    texto_norm = (texto or '').strip()
    if texto_norm.isdigit():
        indice = int(texto_norm) - 1
        if 0 <= indice < len(filas):
            return filas[indice]
        return None
    texto_lower = texto_norm.lower()
    for fila in filas:
        termos = [t.strip().lower() for t in fila.palavras_chave.split(',') if t.strip()]
        if any(termo in texto_lower for termo in termos):
            return fila
    return None


def resolver_fila_por_texto(texto: str, conversa) -> None:
    """Avança a máquina de estados de roteamento de uma Conversa a partir do texto recebido do cliente."""
    filas = _filas_ativas(conversa.numero)

    if conversa.fila_id and conversa.estado_menu == 'EM_ATENDIMENTO':
        return  # já roteada, nada a fazer aqui

    # `tentativas_menu` é o único sinal de "o menu já foi mostrado nesta rodada":
    # zera na criação e na reabertura da conversa. Antes isto olhava o total de
    # mensagens de ENTRADA, que conta o histórico inteiro do telefone — numa
    # conversa reaberta já passava de 1, então o menu era pulado e a primeira
    # frase do cliente ia direto para o casamento por palavra-chave. Um "bom dia"
    # que por acaso contivesse uma palavra-chave roteava o cliente para um setor
    # que ele nunca escolheu.
    if conversa.tentativas_menu == 0:
        _enviar_menu(conversa, filas)
        return

    fila_encontrada = _resolver_por_opcao_ou_palavra_chave(texto, filas)

    if fila_encontrada is None:
        if conversa.tentativas_menu >= TENTATIVAS_MAXIMAS:
            fila_encontrada = Fila.objects.filter(is_padrao=True, ativa=True).first()
        else:
            _enviar_menu(conversa, filas)
            return

    if fila_encontrada is None:
        # Só cai aqui se esgotou as tentativas e não existe fila padrão ativa.
        # Marcar EM_ATENDIMENTO sem fila deixava a conversa num estado morto:
        # o webhook não notifica ninguém (exige fila) e o roteamento não roda de
        # novo, então o cliente ficava no vácuo sem nada aparecer na central.
        logger.warning(
            'Conversa %s esgotou as tentativas de menu e não há fila padrão ativa configurada.',
            conversa.id,
        )
        return

    conversa.fila = fila_encontrada
    conversa.estado_menu = 'EM_ATENDIMENTO'
    conversa.save(update_fields=['fila', 'estado_menu', 'tentativas_menu'])

    responder_automatico(conversa, montar_texto_roteamento(fila_encontrada, conversa.numero))
    _notificar_membros(
        conversa, fila_encontrada, 'CONVERSA_ATRIBUIDA',
        f"Nova conversa de {conversa.contato_nome or conversa.contato_telefone}"
    )


# ── Aviso de andamento de tarefa do Kanban ───────────────────────────────────
# Disparado pelo signal de `kanban.KanbanTask`, não por um atendente — por isso a
# mensagem sai sem assinatura, como as demais falas do robô.

# A Meta recusa parâmetro de template com quebra de linha, tab ou espaços
# seguidos. Título de tarefa é texto digitado por gente, então passa por aqui
# antes de virar {{1}} — senão o template inteiro é rejeitado no envio.
_ESPACOS_SEGUIDOS = re.compile(r'\s+')
LIMITE_PARAMETRO_TEMPLATE = 200


def _parametro_template(texto: str) -> str:
    return _ESPACOS_SEGUIDOS.sub(' ', (texto or '').strip())[:LIMITE_PARAMETRO_TEMPLATE]


def avisar_andamento_tarefa(conversa, titulo_tarefa: str, andamento: str) -> None:
    """
    Conta ao cliente que a tarefa aberta a partir do atendimento dele mudou de estado.

    O caminho depende da janela de 24h: dentro dela vale texto livre; fora, só
    template aprovado. Uma tarefa costuma andar dias depois do atendimento, então
    o segundo caso é a regra e não a exceção — é por isso que a falta de template
    configurado é tratada aqui como situação prevista, e não como erro.
    """
    if conversa.dentro_da_janela_24h:
        responder_automatico(
            conversa,
            f'Atualização da sua solicitação:\n*{titulo_tarefa}*\nSituação: {andamento}',
        )
        return

    # O texto guardado é só o rastro para o histórico: o corpo real do template
    # mora na Meta e pode ser alterado lá sem passar por aqui.
    previa = f'[andamento] {titulo_tarefa} — {andamento}'
    nome_template = getattr(settings, 'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA', None)

    if not nome_template:
        # Gravado como falha, e não apenas logado: quem ligou o aviso na tarefa
        # precisa ver na própria conversa que o cliente não foi avisado, e por quê.
        logger.warning(
            'Tarefa mudou de andamento fora da janela de 24h e '
            'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA não está configurado (conversa_id=%s)',
            conversa.id,
        )
        Mensagem.objects.create(
            conversa=conversa, direcao='SAIDA', tipo='TEXTO', texto=previa, autor=None,
            status_entrega='FALHOU',
            erro_detalhe=(
                'Fora da janela de 24h e nenhum template configurado em '
                'WHATSAPP_TEMPLATE_ANDAMENTO_TAREFA — o cliente não foi avisado.'
            ),
        )
        return

    idioma = getattr(settings, 'WHATSAPP_TEMPLATE_IDIOMA', 'pt_BR')
    componentes = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': _parametro_template(titulo_tarefa)},
            {'type': 'text', 'text': _parametro_template(andamento)},
        ],
    }]
    _registrar_saida_automatica(
        conversa, previa,
        lambda: graph_api.enviar_template(
            conversa.contato_telefone, nome_template, idioma, componentes,
        ),
        'Falha ao enviar template de andamento de tarefa',
        template_nome=nome_template,
        payload_bruto={'template': nome_template, 'idioma': idioma, 'componentes': componentes},
    )
