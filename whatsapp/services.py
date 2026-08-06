"""Regras de negócio desacopladas da ingestão do webhook (fácil de trocar por NLP no futuro)."""
import logging

from django.utils import timezone

from .models import Fila, Mensagem, WhatsAppNotificacao
from . import graph_api

logger = logging.getLogger(__name__)

# Quantas vezes o menu é mandado antes de jogar o cliente na fila padrão.
TENTATIVAS_MAXIMAS = 3


def _filas_ativas():
    return list(Fila.objects.filter(ativa=True).order_by('ordem', 'nome'))


def montar_texto_menu(filas=None) -> str:
    filas = filas if filas is not None else _filas_ativas()
    linhas = ["Olá! Para qual setor você deseja falar? Responda com o número:"]
    for i, fila in enumerate(filas, start=1):
        linhas.append(f"{i} - {fila.nome}")
    return "\n".join(linhas)


def responder_automatico(conversa, texto: str) -> None:
    """
    Manda o texto pelo Graph e grava no histórico da conversa.

    Antes o bot chamava `graph_api.enviar_mensagem_texto` direto: o cliente
    recebia o menu, mas nada disso virava `Mensagem`. O atendente abria a central
    e via só as respostas do cliente ("1", "2"), sem a pergunta correspondente.

    `autor` fica nulo de propósito — é o que distingue a fala do bot da fala de
    um atendente, sem precisar de campo novo no modelo.
    """
    agora = timezone.now()
    mensagem = Mensagem.objects.create(
        conversa=conversa,
        direcao='SAIDA',
        tipo='TEXTO',
        texto=texto,
        autor=None,
        status_entrega='PENDENTE',
    )
    try:
        resposta = graph_api.enviar_mensagem_texto(conversa.contato_telefone, texto)
        mensagem.wa_message_id = resposta.get('messages', [{}])[0].get('id')
        mensagem.status_entrega = 'ENVIADA'
    except Exception as exc:
        # Sem o registro da falha, um menu que não saiu vira silêncio: o cliente
        # não responde e ninguém na central entende por quê.
        logger.exception('Falha ao enviar resposta automática (conversa_id=%s)', conversa.id)
        mensagem.status_entrega = 'FALHOU'
        mensagem.erro_detalhe = str(exc)
    mensagem.save(update_fields=['wa_message_id', 'status_entrega', 'erro_detalhe'])

    conversa.ultima_mensagem_em = agora
    conversa.save(update_fields=['ultima_mensagem_em'])


def _enviar_menu(conversa, filas) -> None:
    """Manda o menu e contabiliza o envio — `tentativas_menu` é o que impede o loop."""
    conversa.tentativas_menu += 1
    conversa.save(update_fields=['tentativas_menu'])
    responder_automatico(conversa, montar_texto_menu(filas))


def _notificar_membros(conversa, fila, tipo, texto_preview):
    if not fila:
        return
    notificacoes = [
        WhatsAppNotificacao(conversa=conversa, usuario_notificado=membro, tipo=tipo, mensagem=texto_preview)
        for membro in fila.membros.all()
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
    filas = _filas_ativas()

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

    responder_automatico(
        conversa,
        f"Você foi direcionado ao setor {fila_encontrada.nome}. Em breve alguém vai te atender."
    )
    _notificar_membros(
        conversa, fila_encontrada, 'CONVERSA_ATRIBUIDA',
        f"Nova conversa de {conversa.contato_nome or conversa.contato_telefone}"
    )
