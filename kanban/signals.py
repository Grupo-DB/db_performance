"""
Detecta mudança de andamento numa tarefa e avisa o contato que a originou.

Fica em signal, e não nas @action do `KanbanTaskViewSet`, porque a tarefa muda de
lista por vários caminhos — `mover`, `concluir`, `reabrir`, o PATCH genérico e o
admin. Espalhar a chamada por todos eles garantiria esquecer um.

A exceção é `reordenar`, que usa `queryset.update()` e por isso não passa por
signal nenhum. Isso aqui é desejado: reordenar verticalmente dentro da mesma
lista não muda o andamento de nada e não deve gerar mensagem.
"""
import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import KanbanTask

logger = logging.getLogger(__name__)

# Marcador combinado entre o pre_save (que ainda enxerga o valor antigo) e o
# post_save (que só dispara depois de a gravação dar certo).
_ATRIBUTO_MUDANCA = '_andamento_mudou'


@receiver(pre_save, sender=KanbanTask)
def _detectar_mudanca_de_andamento(sender, instance, **kwargs):
    """
    Compara a tarefa com a versão gravada e marca se o andamento mudou.

    Precisa ser no pre_save: depois de salvar, o valor anterior já não existe em
    lugar nenhum. A consulta extra só acontece em tarefa que tem conversa de
    origem e aviso ligado — as três condições antes dela são leitura de atributo,
    sem tocar o banco, então o Kanban comum não paga nada por isto.
    """
    # Sempre reposto: a mesma instância pode ser salva mais de uma vez no mesmo
    # request, e um marcador esquecido reenviaria o aviso.
    setattr(instance, _ATRIBUTO_MUDANCA, False)

    if not instance.pk or not instance.conversa_whatsapp_id or not instance.notificar_whatsapp:
        return

    anterior = (
        KanbanTask.objects
        .filter(pk=instance.pk)
        .values('coluna_id', 'concluido_em')
        .first()
    )
    if anterior is None:
        return  # save() com pk atribuído na mão: é criação, não mudança

    # `concluir()` mexe nos dois campos de uma vez; comparar os dois e guardar um
    # único marcador é o que impede a tarefa de render duas mensagens.
    mudou_lista = anterior['coluna_id'] != instance.coluna_id
    mudou_conclusao = bool(anterior['concluido_em']) != bool(instance.concluido_em)
    if mudou_lista or mudou_conclusao:
        setattr(instance, _ATRIBUTO_MUDANCA, True)


@receiver(post_save, sender=KanbanTask)
def _avisar_contato_de_origem(sender, instance, created, **kwargs):
    if created or not getattr(instance, _ATRIBUTO_MUDANCA, False):
        return
    setattr(instance, _ATRIBUTO_MUDANCA, False)

    from whatsapp.tasks import notificar_andamento_tarefa

    tarefa_id = instance.pk
    # on_commit e não delay() direto: se a transação da view voltar atrás, o
    # cliente não pode ter sido avisado de uma mudança que não aconteceu. Também
    # evita a corrida em que o worker lê a tarefa antes de o commit terminar.
    transaction.on_commit(lambda: notificar_andamento_tarefa.delay(tarefa_id))
