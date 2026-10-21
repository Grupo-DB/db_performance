"""
Abastecimentos FALSOS para ver as telas cheias:

    python manage.py gerar_abastecimentos_teste --quantidade 30
    python manage.py gerar_abastecimentos_teste --apagar

Usam equipamentos e funcionários de verdade do SGA (para os nomes parecerem reais), fotos
desenhadas na hora e situações variadas. Todos nascem RETIDOS (alerta de bloqueio "TESTE"):
não saem em arquivo, não aparecem na API do SGA, não podem ser conferidos e não descontam do
saldo dos tanques. A observação começa com [TESTE] — é por ela que o --apagar os acha.
"""
import io
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw

from combustivel import erp
from combustivel.models import MARCA_TESTE, Abastecimento, Tanque

ALERTA_TESTE = {'codigo': 'TESTE', 'nivel': 'bloqueio', 'texto': 'Registro de teste — nunca vai para o SGA.'}


def _foto(titulo: str, valor: str, cor) -> ContentFile:
    img = Image.new('RGB', (800, 600), cor)
    d = ImageDraw.Draw(img)
    for y in range(600):  # degradê simples, para não parecer um bloco chapado
        sombra = int(60 * y / 600)
        d.line([(0, y), (800, y)], fill=tuple(max(c - sombra, 0) for c in cor))
    d.rectangle([60, 180, 740, 420], fill=(15, 23, 42), outline=(255, 255, 255), width=6)
    d.text((90, 205), titulo, fill=(148, 163, 184))
    d.text((90, 270), valor, fill=(34, 197, 94))
    d.text((90, 380), 'FOTO DE TESTE', fill=(248, 113, 113))
    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=80)
    return ContentFile(buf.getvalue(), name='teste.jpg')


class Command(BaseCommand):
    help = 'Gera (ou apaga) abastecimentos falsos, retidos, para testar as telas do Combustível.'

    def add_arguments(self, parser):
        parser.add_argument('--quantidade', type=int, default=30)
        parser.add_argument('--dias', type=int, default=15, help='Espalhar nos últimos N dias')
        parser.add_argument('--usuario', default='', help='username de quem "registrou" (padrão: primeiro superusuário)')
        parser.add_argument('--apagar', action='store_true', help='Apaga todos os abastecimentos de teste')

    def handle(self, *args, **o):
        if o['apagar']:
            qs = Abastecimento.objects.filter(observacao__startswith=MARCA_TESTE)
            for ab in qs:
                for f in (ab.foto_bomba, ab.foto_painel):
                    if f:
                        f.delete(save=False)
            n = qs.count()
            qs.delete()
            self.stdout.write(self.style.SUCCESS(f'{n} abastecimento(s) de teste apagados.'))
            return

        tanques = list(Tanque.objects.filter(ativo=True))
        if not tanques:
            raise CommandError('Cadastre pelo menos um tanque antes (Combustível → Tanques).')
        user = (User.objects.filter(username=o['usuario']).first() if o['usuario']
                else User.objects.filter(is_superuser=True).order_by('id').first())
        if not user:
            raise CommandError('Usuário não encontrado — use --usuario.')

        try:
            equipamentos = [e for e in erp.equipamentos() if e['integra'] and e['usa_horimetro']][:40]
            funcionarios = [f for f in erp.funcionarios() if f['integra']] or erp.funcionarios()[:5]
        except erp.ErpIndisponivel:
            equipamentos, funcionarios = [], []
        if not equipamentos:
            equipamentos = [{'cod': 900000 + i, 'nome': f'EQUIPAMENTO TESTE {i}', 'placa': '', 'centro_custo': None,
                             'usa_horimetro': True, 'usa_km': False} for i in range(1, 9)]
        if not funcionarios:
            funcionarios = [{'cod': 1, 'nome': 'FRENTISTA TESTE'}]

        escolhidos = random.sample(equipamentos, k=min(10, len(equipamentos)))
        horimetro = {e['cod']: random.randint(1500, 25000) for e in escolhidos}
        situacoes = ([Abastecimento.REGISTRADO] * 10 + [Abastecimento.CONFERIDO] * 4 + [Abastecimento.EXPORTADO] * 3
                     + [Abastecimento.BAIXADO] * 5 + [Abastecimento.CANCELADO])
        agora = timezone.now()
        criados = 0
        for i in range(o['quantidade']):
            eqp = random.choice(escolhidos)
            fun = random.choice(funcionarios)
            tanque = random.choice(tanques)
            quando = agora - timedelta(days=random.uniform(0, o['dias']), minutes=random.randint(0, 600))
            horimetro[eqp['cod']] += random.randint(4, 30)
            litros = Decimal(str(round(random.uniform(35, 280), 2)))
            sit = random.choice(situacoes)
            alertas = [ALERTA_TESTE]
            if random.random() < 0.2:
                alertas.append({'codigo': 'ENCERRANTE_DIVERGE', 'nivel': 'aviso', 'texto': 'Encerrante não bate com os litros (exemplo).'})
            enc_ini = Decimal(str(random.randint(100000, 900000)))
            ab = Abastecimento(
                tanque=tanque, abastecido_em=quando, equipamento=eqp['cod'], equipamento_nome=eqp['nome'],
                placa=(eqp.get('placa') or '')[:10], centro_custo=eqp.get('centro_custo'),
                funcionario=fun['cod'], funcionario_nome=fun['nome'], litros=litros,
                horimetro=Decimal(horimetro[eqp['cod']]), encerrante_inicial=enc_ini, encerrante_final=enc_ini + litros,
                observacao=f'{MARCA_TESTE}gerado para ver as telas', situacao=sit, alertas=alertas, bloqueado=True,
                registrado_por=user,
                baixa_sga=(800000 + i) if sit == Abastecimento.BAIXADO else None,
                baixado_em=quando + timedelta(hours=2) if sit == Abastecimento.BAIXADO else None,
                enviado_sga_em=quando + timedelta(hours=1) if sit in (Abastecimento.EXPORTADO, Abastecimento.BAIXADO) else None,
                motivo_cancelamento='Exemplo de cancelamento' if sit == Abastecimento.CANCELADO else '',
            )
            cor = random.choice([(14, 116, 144), (30, 64, 175), (124, 58, 237), (194, 65, 12)])
            ab.foto_bomba.save('b.jpg', _foto('VISOR DA BOMBA', f'{litros} L', cor), save=False)
            ab.foto_painel.save('p.jpg', _foto('HORIMETRO', f'{horimetro[eqp["cod"]]} h', cor), save=False)
            ab.save()
            criados += 1
        self.stdout.write(self.style.SUCCESS(
            f'{criados} abastecimento(s) de teste criados (retidos, não vão para o SGA). Apagar: --apagar'))
