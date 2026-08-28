"""
Põe o código do país nos telefones já gravados sem ele.

A agenda foi importada de um `.vcf` e alimentada à mão, e boa parte dos números
ficou sem o `55`. Isso não é cosmético: a Cloud API lê os dígitos da frente como
DDI, então `51992393150` não é o DDD 51 — é o **Peru**, e a mensagem volta
`131026 Message Undeliverable` horas depois, sem ninguém entender por quê.

O código novo já não deixa entrar número assim, e o envio normaliza na saída.
Este comando é para o passivo: sem ele, cada contato antigo continua quebrado até
alguém tropeçar nele de novo.

Não faz nada sem `--aplicar`. Rodar sem a flag mostra o que mudaria.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from whatsapp.models import Contato, Conversa, DisparoDestinatario
from whatsapp.telefone import telefone_para_envio


class Command(BaseCommand):
    help = 'Acrescenta o DDI 55 aos telefones brasileiros gravados sem ele.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar', action='store_true',
            help='Grava as correções. Sem isto, só relata.',
        )

    def handle(self, *args, **opcoes):
        aplicar = opcoes['aplicar']
        if not aplicar:
            self.stdout.write(self.style.WARNING(
                'Simulação (use --aplicar para gravar).\n'))

        with transaction.atomic():
            self._corrige_conversas(aplicar)
            self._corrige_contatos(aplicar)
            self._corrige_destinatarios(aplicar)
            if not aplicar:
                transaction.set_rollback(True)

    # ── Conversas ────────────────────────────────────────────────────────────
    #
    # As mais importantes: é o `contato_telefone` da conversa que vai no campo
    # `to` do envio. Corrigir a agenda sem corrigir aqui não muda nada — foi
    # exatamente o que confundiu o RH, que editava o número e via a mensagem
    # sair no formato velho.

    def _corrige_conversas(self, aplicar):
        alterados = 0
        for conversa in Conversa.objects.all().only('id', 'contato_telefone').iterator():
            canonico = telefone_para_envio(conversa.contato_telefone)
            if canonico == conversa.contato_telefone:
                continue
            self.stdout.write(
                f'  conversa {conversa.id}: {conversa.contato_telefone} → {canonico}')
            if aplicar:
                Conversa.objects.filter(pk=conversa.pk).update(contato_telefone=canonico)
            alterados += 1
        self.stdout.write(self.style.SUCCESS(f'Conversas: {alterados}'))

    # ── Agenda ───────────────────────────────────────────────────────────────
    #
    # `Contato.telefone` é único. Se o mesmo celular já existe na forma completa,
    # normalizar o incompleto colidiria — então a linha duplicada é apontada no
    # relatório em vez de gravada. Fundir as duas exige decidir qual nome e quais
    # observações ficam, e isso é escolha de quem cuida da agenda, não do script.

    def _corrige_contatos(self, aplicar):
        alterados, colisoes = 0, []
        for contato in Contato.objects.all().only('id', 'telefone', 'nome').iterator():
            canonico = telefone_para_envio(contato.telefone)
            if canonico == contato.telefone:
                continue
            ja_existe = (Contato.objects
                         .filter(telefone=canonico)
                         .exclude(pk=contato.pk).first())
            if ja_existe:
                colisoes.append((contato, ja_existe, canonico))
                continue
            self.stdout.write(f'  contato {contato.id} ({contato.nome}): '
                              f'{contato.telefone} → {canonico}')
            if aplicar:
                Contato.objects.filter(pk=contato.pk).update(telefone=canonico)
            alterados += 1

        self.stdout.write(self.style.SUCCESS(f'Contatos: {alterados}'))
        if colisoes:
            self.stdout.write(self.style.WARNING(
                f'\n{len(colisoes)} contato(s) duplicado(s) — o mesmo celular já está '
                f'cadastrado na forma completa. Resolva à mão na agenda:'))
            for contato, existente, canonico in colisoes:
                self.stdout.write(
                    f'  {contato.telefone} ({contato.nome}) colide com '
                    f'{existente.telefone} ({existente.nome}) em {canonico}')

    # ── Destinatários de disparo ─────────────────────────────────────────────
    #
    # O telefone é copiado do contato no momento da criação do disparo, então
    # disparo antigo carrega a cópia errada. Só os que ainda não saíram importam:
    # reescrever um `ENVIADO` mudaria o registro histórico do que foi mandado.

    def _corrige_destinatarios(self, aplicar):
        alterados = 0
        pendentes = DisparoDestinatario.objects.exclude(status='ENVIADO')
        for destinatario in pendentes.only('id', 'telefone').iterator():
            canonico = telefone_para_envio(destinatario.telefone)
            if canonico == destinatario.telefone:
                continue
            self.stdout.write(
                f'  destinatário {destinatario.id}: {destinatario.telefone} → {canonico}')
            if aplicar:
                DisparoDestinatario.objects.filter(pk=destinatario.pk).update(telefone=canonico)
            alterados += 1
        self.stdout.write(self.style.SUCCESS(f'Destinatários pendentes: {alterados}'))
