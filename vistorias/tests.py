"""
Testes do módulo de vistorias — os critérios de aceite da seção 15 do escopo v2.1.

venv/bin/python manage.py test vistorias.tests --settings=db_performance.test_settings
"""
import io
import shutil
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from . import avisos, execucao, indicador, regras, servicos
from .models import (DestinatarioNotificacao, EmailVistoria, Equipamento, Evidencia, Ficha, ProgramaItem, Resposta,
                     Setor, Suspensao, TipoEquipamento, Unidade, VinculoEquipamento, Vistoria)

TMP = tempfile.mkdtemp(prefix='vist_test_')


def _foto():
    b = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 10, 10)).save(b, 'PNG')
    return SimpleUploadedFile('f.png', b.getvalue(), content_type='image/png')


def _aware(y, m, d, h=10):
    return timezone.make_aware(datetime(y, m, d, h, 0))


QUESTOES = [
    {'codigo': '1', 'grupo': 'Cabine', 'descricao': 'Vidro frontal', 'criticidade': 'MEDIA'},
    {'codigo': '2', 'grupo': 'Segurança', 'descricao': 'Freio de estacionamento', 'criticidade': 'CRITICA', 'permite_na': False},
    {'codigo': '3', 'grupo': 'Geral', 'descricao': 'Danos na pintura', 'criticidade': 'MEDIA', 'permite_abono': True},
    {'codigo': '4', 'grupo': 'Geral', 'descricao': 'Tapete do assoalho', 'criticidade': 'LEVE'},
    {'codigo': '5', 'grupo': 'Segurança', 'descricao': 'Cinto', 'criticidade': 'CRITICA'},
]


@override_settings(VISTORIAS_PRIVADO=TMP, VISTORIAS_EMAIL_SINCRONO=True)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        mail.outbox = []
        self.geo = self._user('geo', 'VistoriaGestor')
        self.aval = self._user('aval', 'VistoriaAvaliador')
        self.pcm = self._user('pcm', 'VistoriaPCM')
        self.sesmt = self._user('sesmt', 'VistoriaSESMT')
        self.ger1 = self._user('ger1', 'VistoriaGerente', email='ger1@x.com')
        self.ger2 = self._user('ger2', 'VistoriaGerente', email='ger2@x.com')
        self.un = Unidade.objects.create(sigla='FCB', nome='Fábrica')
        self.setor = Setor.objects.create(unidade=self.un, codigo='MIN', nome='Mineração')
        self.ficha = Ficha.objects.create(nome='Máquinas')
        servicos.nova_versao(self.ficha, QUESTOES)
        self.tipo = TipoEquipamento.objects.create(codigo='CAM', descricao='Caminhão', ficha=self.ficha, medicao='HORIMETRO')
        for papel, email in (('GEO', 'geo@x.com'), ('SESMT', 'sesmt@x.com'), ('PCM', 'pcm@x.com')):
            DestinatarioNotificacao.objects.create(unidade=self.un, papel=papel, email=email)

    def _user(self, nome, grupo, email=''):
        u = User.objects.create_user(nome, email or f'{nome}@x.com', 'x', first_name=nome.upper())
        u.groups.add(Group.objects.get_or_create(name=grupo)[0])
        return u

    def _eq(self, tag, per='MENSAL', gerente=None, desde=None):
        eq = Equipamento.objects.create(tag=tag, descricao=f'Equip {tag}', tipo=self.tipo, unidade=self.un, setor=self.setor,
                                        gerente=gerente or self.ger1, periodicidade=per)
        servicos.registrar_vinculo(eq, quando=desde or _aware(2025, 12, 1))
        return eq

    def _vistoria_pronta(self, eq, respostas=None, item=None):
        hoje = timezone.localdate()
        item = item or ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month)
        v = execucao.iniciar(eq, self.aval, item=item)
        execucao.salvar_identificacao(v, self.aval, {'medicao': '1200', 'acompanhante_nome': 'P. Souza',
                                                     'acompanhante_cargo': 'Operador'})
        respostas = respostas or {}
        for r in v.respostas.all():
            valor = respostas.get(r.codigo, 'C')
            execucao.responder(v, self.aval, r.codigo, valor, 'problema' if valor == 'NC' else '',
                               confirmar_critica=(valor == 'NC' and r.criticidade == 'CRITICA'))
            if valor == 'NC':
                Evidencia.objects.create(vistoria=v, resposta=r, arquivo='x.jpg')
        return v


class Aceite1NCCritica(Base):
    def test_nc_critica_suspende_na_hora_e_manda_email_aos_4(self):
        eq = self._eq('CR-003')
        hoje = timezone.localdate()
        item = ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month)
        v = execucao.iniciar(eq, self.aval, item=item)
        with self.captureOnCommitCallbacks(execute=True):
            r, s = execucao.responder(v, self.aval, '2', 'NC', 'Veículo deslocou em rampa', confirmar_critica=True)
        self.assertIsNotNone(s)
        self.assertEqual(s.status, Suspensao.SUSPENSA)
        self.assertEqual(v.status, Vistoria.ANDAMENTO)  # antes de concluir
        # e-mail espera o adesivo; ao informar, sai
        self.assertEqual(len(mail.outbox), 0)
        with self.captureOnCommitCallbacks(execute=True):
            execucao.registrar_adesivo(s, self.aval, True)
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(set(m.to), {'ger1@x.com', 'geo@x.com', 'sesmt@x.com', 'pcm@x.com'})
        self.assertIn('[OPERAÇÃO SUSPENSA] CR-003', m.subject)
        html = m.alternatives[0][0]
        self.assertIn('ESTÁ SUSPENSA', html)
        self.assertIn('afixado pelo avaliador', html)
        # resposta travada para o avaliador
        with self.assertRaises(ValidationError):
            execucao.responder(v, self.aval, '2', 'C')

    def test_email_sai_sem_adesivo_pelo_cron(self):
        eq = self._eq('CR-004')
        v = self._vistoria_pronta.__func__  # noqa
        hoje = timezone.localdate()
        item = ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month)
        v = execucao.iniciar(eq, self.aval, item=item)
        execucao.responder(v, self.aval, '2', 'NC', 'x', confirmar_critica=True)
        EmailVistoria.objects.update(criado_em=timezone.now() - timezone.timedelta(minutes=5))
        self.assertEqual(avisos.enviar_pendentes(), 1)
        self.assertIn('ainda não confirmado', mail.outbox[0].alternatives[0][0])
        self.assertEqual(avisos.enviar_pendentes(), 0)  # não duplica

    def test_geo_cancela_nc_critica_e_avisa(self):
        eq = self._eq('CR-005')
        v = self._vistoria_pronta(eq, {'2': 'NC'})
        with self.captureOnCommitCallbacks(execute=True):
            execucao.cancelar_critica(v, self.geo, '2', 'Avaliador marcou a questão errada')
        s = eq.suspensoes.first()
        self.assertEqual(s.status, Suspensao.CANCELADA)
        self.assertTrue(any('[NC CRÍTICA CANCELADA]' in m.subject for m in mail.outbox))


class Aceite3FichaVersionada(Base):
    def test_alterar_ficha_nao_muda_vistoria_antiga(self):
        eq = self._eq('CR-001')
        v = self._vistoria_pronta(eq)
        execucao.concluir(v, self.aval)
        nova = [dict(q) for q in QUESTOES if q['codigo'] != '4']
        nova[0]['descricao'] = 'Para-brisa'
        nova[0]['criticidade'] = 'LEVE'
        ver = servicos.nova_versao(self.ficha, nova, self.geo)
        self.assertEqual(ver.numero, 2)
        self.assertFalse(ver.questoes.get(codigo='4').ativa)  # inativada, não excluída
        v.refresh_from_db()
        r1 = v.respostas.get(codigo='1')
        self.assertEqual((r1.descricao, r1.criticidade), ('Vidro frontal', 'MEDIA'))
        self.assertTrue(v.respostas.filter(codigo='4').exists())
        self.assertEqual(v.ficha_versao.numero, 1)


class Aceite4Conclusao(Base):
    def test_conclusao_bloqueada_com_pendencias(self):
        eq = self._eq('CR-001')
        hoje = timezone.localdate()
        v = execucao.iniciar(eq, self.aval, item=ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month))
        execucao.responder(v, self.aval, '1', 'NC', 'trincado')
        with self.assertRaises(ValidationError) as ctx:
            execucao.concluir(v, self.aval)
        campos = {p['campo'] for p in ctx.exception.detail['pendencias']}
        self.assertIn('q:1', campos)          # NC sem foto
        self.assertIn('q:2', campos)          # sem resposta
        self.assertIn('acompanhante_nome', campos)
        self.assertIn('medicao', campos)

    def test_na_proibido_e_medicao_menor(self):
        eq = self._eq('CR-002')
        v = self._vistoria_pronta(eq)
        execucao.concluir(v, self.aval)
        hoje = timezone.localdate()
        v2 = execucao.iniciar(eq, self.aval, extraordinaria=True, motivo='Pedido do gerente')
        self.assertEqual(v2.medicao_anterior, Decimal('1200'))
        with self.assertRaises(ValidationError):
            execucao.responder(v2, self.aval, '2', 'NA')
        execucao.salvar_identificacao(v2, self.aval, {'medicao': '1100'})
        self.assertIn('medicao', {p['campo'] for p in execucao.pendencias(v2)})


class Aceite5Abono(Base):
    def test_abono_so_em_questao_abonavel_e_resultado_final(self):
        eq = self._eq('CR-002')
        v = self._vistoria_pronta(eq, {'3': 'NC', '1': 'NC'})
        execucao.concluir(v, self.aval)
        self.assertEqual(v.resultado_inicial, 'I')
        with self.assertRaises(ValidationError):
            execucao.abonar(v, self.geo, '1', True, 'estético')      # não abonável
        execucao.abonar(v, self.geo, '3', True, 'desgaste estético')
        execucao.validar(v, self.geo)
        self.assertEqual((v.resultado_inicial, v.resultado_final), ('I', 'I'))  # 7.1 segura o I (Figura 4)

    def test_abono_tira_do_resultado_final(self):
        eq = self._eq('CR-006')
        v = self._vistoria_pronta(eq, {'3': 'NC', '4': 'NC'})
        execucao.concluir(v, self.aval)
        execucao.abonar(v, self.geo, '3', True, 'estético')
        execucao.validar(v, self.geo)
        self.assertEqual((v.resultado_inicial, v.resultado_final), ('I', 'S'))
        self.assertTrue(v.respostas.get(codigo='3').valor == 'NC')  # registro original preservado

    def test_devolucao(self):
        eq = self._eq('CR-007')
        v = self._vistoria_pronta(eq)
        execucao.concluir(v, self.aval)
        execucao.devolver(v, self.geo, 'Horímetro incorreto')
        self.assertEqual(v.status, Vistoria.ANDAMENTO)
        execucao.salvar_identificacao(v, self.aval, {'medicao': '1300'})
        execucao.concluir(v, self.aval)


class Aceite6Liberacao(Base):
    def test_liberacao_bloqueada_com_nc_sem_correcao(self):
        eq = self._eq('CR-003')
        v = self._vistoria_pronta(eq, {'2': 'NC', '5': 'NC'})
        s = eq.suspensoes.get()
        self.assertEqual(s.ncs.count(), 2)
        nc1, nc2 = list(s.ncs.all())
        Evidencia.objects.create(finalidade='CORRECAO', nc_critica=nc1, arquivo='c.jpg')
        execucao.registrar_correcao(nc1, self.pcm, 'Regulado o freio')
        with self.assertRaises(ValidationError):
            execucao.liberar(s, self.sesmt)
        s.refresh_from_db()
        self.assertEqual(s.status, Suspensao.SUSPENSA)
        Evidencia.objects.create(finalidade='CORRECAO', nc_critica=nc2, arquivo='c2.jpg')
        execucao.registrar_correcao(nc2, self.pcm, 'Cinto trocado')
        s.refresh_from_db()
        self.assertEqual(s.status, Suspensao.AGUARDANDO)
        # rejeição volta para suspensa e avisa o PCM
        with self.captureOnCommitCallbacks(execute=True):
            execucao.rejeitar_correcao(nc2, self.sesmt, 'Cinto sem certificação')
        s.refresh_from_db()
        self.assertEqual(s.status, Suspensao.SUSPENSA)
        self.assertTrue(any('pcm@x.com' in m.to and 'CORREÇÃO REJEITADA' in m.subject for m in mail.outbox))
        execucao.registrar_correcao(nc2, self.pcm, 'Cinto certificado')
        with self.captureOnCommitCallbacks(execute=True):
            execucao.liberar(s, self.sesmt, 'ok')
        s.refresh_from_db()
        self.assertEqual(s.status, Suspensao.LIBERADA)
        self.assertTrue(any('[LIBERADO]' in m.subject for m in mail.outbox))
        self.assertEqual(v.resultado_inicial or execucao.calcular_resultado(v, False), 'C')  # histórico intacto

    def test_sem_dispensa_para_suspenso(self):
        eq = self._eq('CR-008')
        self._vistoria_pronta(eq, {'2': 'NC'})
        hoje = timezone.localdate()
        prox = ProgramaItem.objects.create(equipamento=eq, ano=hoje.year + 1, mes=1)
        with self.assertRaises(ValidationError):
            servicos.dispensar(prox, self.geo, 'qualquer', confirmado=True)


class Aceite7Indicador(TestCase):
    def test_exemplo_11_1(self):
        e = regras.EntradaMes
        saidas = ([regras.classificar_mes(e(True, 'PROGRAMADA', programada='S'))] * 15
                  + [regras.classificar_mes(e(True, 'PROGRAMADA', programada='I'))] * 2
                  + [regras.classificar_mes(e(True, 'PROGRAMADA', programada='C'))]
                  + [regras.classificar_mes(e(True, 'PROGRAMADA'))] * 2
                  + [regras.classificar_mes(e(True, 'DISPENSADA'))])
        ind = regras.indicador_mensal(saidas)
        self.assertEqual((ind.satisfatorios, ind.considerados, ind.percentual), (15, 20, Decimal('75.00')))

    def test_suspenso_e_dispensa_e_vazio(self):
        s = regras.classificar_mes(regras.EntradaMes(True, 'DISPENSADA', suspenso=True))
        self.assertTrue(s.considerado and not s.satisfatorio)
        s = regras.classificar_mes(regras.EntradaMes(True, None, ultima_valida='S', suspenso=True))
        self.assertFalse(s.satisfatorio)
        self.assertIsNone(regras.indicador_mensal([]).percentual)  # Não aplicável
        self.assertEqual(regras.indicador_trimestral([Decimal(100), None, Decimal(50)]), Decimal('75.00'))

    def test_ciclos(self):
        self.assertEqual(regras.meses_previstos('BIMESTRAL'), [1, 3, 5, 7, 9, 11])
        self.assertEqual(regras.meses_previstos('TRIMESTRAL'), [1, 4, 7, 10])
        self.assertEqual(regras.quinto_dia_util(2026, 10), date(2026, 11, 6))


@override_settings(VISTORIAS_PRIVADO=TMP, VISTORIAS_EMAIL_SINCRONO=True)
class Aceite7Exemplo112(Base):
    """Figura 8 em 2026 (1º trimestre já passou): 100% / 60% / 75% e trimestral 78,33%."""

    def _feita(self, eq, item, res, quando, validar=True):
        v = Vistoria.objects.create(equipamento=eq, item=item, ficha_versao=self.ficha.versao_atual(), unidade=self.un,
                                    setor=self.setor, gerente=eq.gerente, avaliador=self.aval, iniciada_em=quando,
                                    concluida_em=quando, status='VALIDADA' if validar else 'CONCLUIDA',
                                    resultado_inicial=res, resultado_final=res if validar else '')
        return v

    def montar(self):
        A = 2026
        cr1, cr2, esc, per, cr3 = (self._eq('CR-001'), self._eq('CR-002'), self._eq('ESC-001', 'BIMESTRAL'),
                                   self._eq('PER-001', 'TRIMESTRAL'), self._eq('CR-003'))
        it = lambda eq, m, sit='PROGRAMADA': ProgramaItem.objects.create(equipamento=eq, ano=A, mes=m, situacao=sit)  # noqa
        for m, r in zip((1, 2, 3), 'SSS'):
            self._feita(cr1, it(cr1, m), r, _aware(A, m, 10))
        for m, r in zip((1, 2, 3), 'SII'):
            self._feita(cr2, it(cr2, m), r, _aware(A, m, 10))
        self._feita(esc, it(esc, 1), 'S', _aware(A, 1, 15))
        self._feita(esc, it(esc, 3), 'S', _aware(A, 3, 12))
        self._feita(per, it(per, 1), 'S', _aware(A, 1, 18))
        self._feita(cr3, it(cr3, 1), 'S', _aware(A, 1, 10))
        it(cr3, 2)                       # não realizada
        it(cr3, 3, 'DISPENSADA')
        return A

    def test_figura_8(self):
        A = self.montar()
        d = indicador.apurar_ano(A, meses=[1, 2, 3])
        p = {m: d['indicadores'][m]['percentual'] for m in (1, 2, 3)}
        self.assertEqual(p, {1: 100.0, 2: 60.0, 3: 75.0})
        self.assertEqual(d['trimestres'][1]['percentual'], 78.33)
        linha = {l['tag']: l for l in d['linhas']}
        self.assertTrue(linha['PER-001']['celulas'][3]['herdado'])
        self.assertEqual(linha['CR-003']['celulas'][2]['resultado'], 'NR')
        self.assertEqual(linha['CR-003']['celulas'][3]['resultado'], 'D')
        self.assertIn('PER-001↻ (vistoria de 2026-01-18)', d['indicadores'][3]['memoria']['satisfatorios'])

    def test_fechamento_congela_e_reabre(self):
        A = self.montar()
        for m in (1, 2, 3):
            indicador.fechar_mes(A, m, self.geo)
        indicador.fechar_trimestre(A, 1, self.geo)
        # mexer depois do fechamento não muda o mês fechado
        Vistoria.objects.filter(equipamento__tag='CR-002').update(resultado_final='S')
        d = indicador.apurar_ano(A, meses=[1, 2, 3])
        self.assertEqual(d['indicadores'][2]['percentual'], 60.0)
        with self.assertRaises(ValidationError):
            indicador.reabrir_mes(A, 2, self.geo, 'erro')  # trimestre fechado

    def test_aceite_8_troca_de_gerente(self):
        A = self.montar()
        cr2 = Equipamento.objects.get(tag='CR-002')
        cr2.gerente = self.ger2
        cr2.save()
        servicos.registrar_vinculo(cr2, quando=_aware(A, 4, 1))
        d = indicador.apurar_ano(A, {'gerente': self.ger1.pk}, meses=[1, 2, 3])
        self.assertIn('CR-002', {l['tag'] for l in d['linhas']})
        d2 = indicador.apurar_ano(A, {'gerente': self.ger2.pk}, meses=[1, 2, 3])
        self.assertNotIn('CR-002', {l['tag'] for l in d2['linhas']})

    def test_extraordinaria_nao_substitui_programada(self):
        A = self.montar()
        cr2 = Equipamento.objects.get(tag='CR-002')
        v = Vistoria.objects.create(equipamento=cr2, tipo='EXTRAORDINARIA', ficha_versao=self.ficha.versao_atual(),
                                    unidade=self.un, setor=self.setor, avaliador=self.aval, iniciada_em=_aware(A, 2, 20),
                                    concluida_em=_aware(A, 2, 20), status='VALIDADA', resultado_inicial='S', resultado_final='S')
        d = indicador.apurar_ano(A, meses=[2])
        self.assertEqual(d['indicadores'][2]['percentual'], 60.0)
        self.assertTrue(v.pk)


@override_settings(VISTORIAS_PRIVADO=TMP, VISTORIAS_EMAIL_SINCRONO=True)
class ProgramaTestes(Base):
    def test_gerar_programa_e_dispensa_bimestral(self):
        eq = self._eq('ESC-001', 'BIMESTRAL')
        n = servicos.gerar_programa(2027, self.geo, hoje=date(2026, 11, 27))
        self.assertEqual(n, 6)
        self.assertEqual(servicos.gerar_programa(2027, self.geo, hoje=date(2026, 11, 27)), 0)
        it = ProgramaItem.objects.get(equipamento=eq, ano=2027, mes=3)
        with self.assertRaises(ValidationError) as ctx:
            servicos.dispensar(it, self.geo, 'manutenção longa')
        self.assertIn('confirmar', ctx.exception.detail)
        servicos.dispensar(it, self.geo, 'manutenção longa', confirmado=True)
        self.assertEqual(it.situacao, 'DISPENSADA')

    def test_situacao_atrasada(self):
        eq = self._eq('CR-001')
        it = ProgramaItem.objects.create(equipamento=eq, ano=2026, mes=4)
        self.assertEqual(servicos.situacao_item(it, [], [], date(2026, 6, 10))['codigo'], 'A')
        self.assertEqual(servicos.situacao_item(it, [], [], date(2026, 4, 10))['codigo'], 'P')


@override_settings(VISTORIAS_PRIVADO=TMP, VISTORIAS_EMAIL_SINCRONO=True)
class ApiTestes(Base):
    def test_fluxo_pela_api(self):
        eq = self._eq('CR-010')
        hoje = timezone.localdate()
        ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month)
        c = APIClient()
        c.force_authenticate(self.aval)
        minhas = c.get('/vistorias/minhas/').json()
        self.assertEqual(minhas['pendentes'][0]['tag'], 'CR-010')
        uuid = '0b0f0c1e-1111-4a4a-9b9b-123456789abc'
        r = c.post('/vistorias/vistorias/', {'equipamento': eq.pk, 'uuid': uuid}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(c.post('/vistorias/vistorias/', {'equipamento': eq.pk, 'uuid': uuid}, format='json').json()['uuid'], uuid)
        base = f'/vistorias/vistorias/{uuid}/'
        c.patch(base + 'identificacao/', {'medicao': 10, 'acompanhante_nome': 'A', 'acompanhante_cargo': 'Op'}, format='json')
        for q in QUESTOES:
            c.post(base + 'responder/', {'codigo': q['codigo'], 'valor': 'C'}, format='json')
        c.post(base + 'responder/', {'codigo': '4', 'valor': 'NC', 'descricao': 'solto'}, format='json')
        ev = c.post(base + 'evidencias/', {'codigo': '4', 'arquivo': _foto(), 'uuid': 'aaaaaaaa-1111-4a4a-9b9b-123456789abc'},
                    format='multipart')
        self.assertEqual(ev.status_code, 201, ev.content)
        r = c.post(base + 'concluir/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['resultado_inicial'], 'S')
        # arquivo só sai pela API e para quem pode ver
        self.assertEqual(c.get(ev.json()['url']).status_code, 200)
        # gerente 2 não vê o equipamento do gerente 1
        c2 = APIClient()
        c2.force_authenticate(self.ger2)
        self.assertEqual(c2.get(ev.json()['url']).status_code, 404)
        self.assertEqual(c2.get('/vistorias/equipamentos/').json(), [])
        # avaliador não valida
        self.assertEqual(c.post(base + 'validar/').status_code, 403)
        g = APIClient()
        g.force_authenticate(self.geo)
        self.assertEqual(g.post(base + 'validar/').status_code, 200)
        painel = g.get('/vistorias/painel/').json()
        self.assertEqual(painel['programa']['realizadas'], 1)
        prog = g.get('/vistorias/programa/').json()
        self.assertEqual(prog['linhas'][0]['meses'][str(hoje.month)]['codigo'], 'R')

    def test_sem_perfil_nao_entra(self):
        u = User.objects.create_user('nada', 'n@x.com', 'x')
        c = APIClient()
        c.force_authenticate(u)
        self.assertEqual(c.get('/vistorias/painel/').status_code, 403)
        self.assertEqual(c.get('/vistorias/equipamentos/').status_code, 403)

    def test_suspenso_no_mapa_e_na_lista(self):
        eq = self._eq('CR-003')
        self._vistoria_pronta(eq, {'2': 'NC'})
        g = APIClient()
        g.force_authenticate(self.geo)
        self.assertEqual(g.get('/vistorias/programa/').json()['suspensos'][0]['tag'], 'CR-003')
        self.assertEqual(g.get('/vistorias/painel/').json()['situacao']['suspensos'], 1)
        a = APIClient()
        a.force_authenticate(self.aval)
        self.assertEqual(a.get('/vistorias/minhas/').json()['suspensos'][0]['tag'], 'CR-003')

    def test_carga_das_fichas(self):
        from django.core.management import call_command
        call_command('carregar_fichas_vistoria', stdout=io.StringIO())
        f = Ficha.objects.get(nome='Máquinas e caminhões')
        self.assertEqual(f.versao_atual().questoes.count(), 41)
        self.assertEqual(TipoEquipamento.objects.filter(ficha=f).count(), 7)
        self.assertTrue(f.versao_atual().questoes.get(descricao='Danos na pintura').permite_abono)


@override_settings(VISTORIAS_PRIVADO=TMP, VISTORIAS_EMAIL_SINCRONO=True)
class ImagensESgaTestes(Base):
    def test_carga_traz_desenhos_e_marcacao_valida(self):
        from django.core.management import call_command
        from .models import ImagemTipo
        call_command('carregar_fichas_vistoria', stdout=io.StringIO())
        call_command('carregar_fichas_vistoria', stdout=io.StringIO())   # não duplica
        carreg = TipoEquipamento.objects.get(codigo='CARREGADEIRA')
        self.assertEqual(carreg.imagens.count(), 3)
        self.assertEqual(ImagemTipo.objects.filter(tipo__codigo='PICADOR').count(), 0)
        eq = Equipamento.objects.create(tag='VEC-PC-03', descricao='Pá', tipo=carreg, unidade=self.un, setor=self.setor)
        servicos.registrar_vinculo(eq)
        hoje = timezone.localdate()
        v = execucao.iniciar(eq, self.aval, item=ProgramaItem.objects.create(equipamento=eq, ano=hoje.year, mes=hoje.month))
        img = carreg.imagens.first()
        execucao.salvar_identificacao(v, self.aval, {'marcacoes': [{'imagem': img.pk, 'x': 0.5, 'y': 0.25, 'nota': 'amassado'}]})
        self.assertEqual(v.marcacoes[0]['nota'], 'amassado')
        outra = TipoEquipamento.objects.get(codigo='PIPA').imagens.first()
        with self.assertRaises(ValidationError):
            execucao.salvar_identificacao(v, self.aval, {'marcacoes': [{'imagem': outra.pk, 'x': 0.5, 'y': 0.5}]})
        with self.assertRaises(ValidationError):
            execucao.salvar_identificacao(v, self.aval, {'marcacoes': [{'imagem': img.pk, 'x': 1.5, 'y': 0.5}]})
        c = APIClient()
        c.force_authenticate(self.aval)
        self.assertEqual(c.get(f'/vistorias/imagens/{img.pk}/arquivo/').status_code, 200)
        self.assertEqual(len(c.get(f'/vistorias/vistorias/{v.uuid}/').json()['imagens_avarias']), 3)

    def test_mapeamento_sga(self):
        from django.core.management import call_command
        from . import sga
        call_command('carregar_fichas_vistoria', stdout=io.StringIO())
        lista = [
            {'cod': 1, 'tag': 'VEC-PC-03', 'nome': 'VEC-PC-03 - PA CARREGADEIRA KOMATSU', 'descricao': 'PA CARREGADEIRA', 'abastece': True},
            {'cod': 2, 'tag': 'VEC-PC-07', 'nome': 'VEC-PC-07 - PA', 'centro_custo_nome': 'ATM-VEC-PC-07', 'abastece': True},
            {'cod': 3, 'tag': 'VEC-CF-06', 'nome': 'VEC-CF-06 - CAMINHAO FORA EST RK 430', 'abastece': True},
            {'cod': 4, 'tag': 'VEC-CS-07', 'nome': 'VEC-CS-07 - CAMINHAO DE SUPORTE PIPA', 'abastece': True},
            {'cod': 5, 'tag': 'VEC-PC-LIMPEZA', 'nome': 'VEC-PC-LIMPEZA', 'abastece': True},
            {'cod': 6, 'tag': 'VEC-VA-30', 'nome': 'VEC-VA-30 - AMAROK', 'abastece': True},
            {'cod': 7, 'tag': 'VEC-EC-05', 'nome': 'VEC-EC-05 - EMPILHADEIRA', 'abastece': True},
        ]
        r = sga.importar(lista, self.geo)
        tipos = {l['tag']: (l['tipo'], l['unidade']) for l in r['entrar']}
        self.assertEqual(tipos['VEC-PC-07'], ('CARREGADEIRA', 'ATM'))
        self.assertEqual(tipos['VEC-CF-06'][0], 'CAM-RK')
        self.assertEqual(tipos['VEC-CS-07'][0], 'PIPA')
        self.assertEqual(tipos['VEC-EC-05'][0], 'EMPILHADEIRA-2.0')
        self.assertEqual([l['tag'] for l in r['sem_ficha']], ['VEC-VA-30'])
        self.assertEqual(r['ignorados'][0]['tag'], 'VEC-PC-LIMPEZA')
        self.assertEqual(Equipamento.objects.get(tag='VEC-PC-03').setor.nome, 'A definir')
        self.assertTrue(ProgramaItem.objects.filter(equipamento__tag='VEC-PC-03').exists())
        self.assertEqual(len(sga.importar(lista, self.geo)['criados']), 0)   # idempotente
