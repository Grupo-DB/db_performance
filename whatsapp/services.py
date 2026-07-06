"""Regras de negócio desacopladas da ingestão do webhook (fácil de trocar por NLP no futuro)."""
import logging

from .models import Fila, WhatsAppNotificacao
from . import graph_api

logger = logging.getLogger(__name__)

TENTATIVAS_MAXIMAS = 3


def _filas_ativas():
    return list(Fila.objects.filter(ativa=True).order_by('ordem', 'nome'))


def montar_texto_menu(filas=None) -> str:
    filas = filas if filas is not None else _filas_ativas()
    linhas = ["Olá! Para qual setor você deseja falar? Responda com o número:"]
    for i, fila in enumerate(filas, start=1):
        linhas.append(f"{i} - {fila.nome}")
    return "\n".join(linhas)


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

    primeira_interacao = conversa.tentativas_menu == 0 and conversa.mensagens.filter(direcao='ENTRADA').count() <= 1
    if primeira_interacao:
        graph_api.enviar_mensagem_texto(conversa.contato_telefone, montar_texto_menu(filas))
        return

    fila_encontrada = _resolver_por_opcao_ou_palavra_chave(texto, filas)

    if fila_encontrada is None:
        conversa.tentativas_menu += 1
        if conversa.tentativas_menu >= TENTATIVAS_MAXIMAS:
            fila_encontrada = Fila.objects.filter(is_padrao=True, ativa=True).first()
        else:
            conversa.save(update_fields=['tentativas_menu'])
            graph_api.enviar_mensagem_texto(conversa.contato_telefone, montar_texto_menu(filas))
            return

    conversa.fila = fila_encontrada
    conversa.estado_menu = 'EM_ATENDIMENTO'
    conversa.save(update_fields=['fila', 'estado_menu', 'tentativas_menu'])

    if fila_encontrada:
        graph_api.enviar_mensagem_texto(
            conversa.contato_telefone,
            f"Você foi direcionado ao setor {fila_encontrada.nome}. Em breve alguém vai te atender."
        )
        _notificar_membros(
            conversa, fila_encontrada, 'CONVERSA_ATRIBUIDA',
            f"Nova conversa de {conversa.contato_nome or conversa.contato_telefone}"
        )
