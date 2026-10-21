import io
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from . import regras
from .integracao import gerar_csv, gerar_txt, registro
from .models import BASE_CODIGO_INTEGRACAO, Abastecimento, ChaveIntegracao, Tanque

EQUIPAMENTOS = [
    {'cod': 531, 'nome': 'VEC-CF-09 - CAMINHAO FORA EST', 'placa': 'IUB-5649', 'centro_custo': 5481,
     'centro_custo_nome': 'Transporte', 'usa_km': False, 'usa_horimetro': True, 'integra': True},
    {'cod': 999, 'nome': 'SEM IDENT', 'placa': '', 'centro_custo': None, 'centro_custo_nome': '',
     'usa_km': False, 'usa_horimetro': True, 'integra': False},
]
FUNCIONARIOS = [{'cod': 194, 'nome': 'Frentista', 'integra': True}, {'cod': 300, 'nome': 'Sem ident', 'integra': False}]


def _foto(formato='PNG'):
    buf = io.BytesIO()
    Image.new('RGB', (40, 30), (200, 80, 20)).save(buf, formato)
    return SimpleUploadedFile(f'f.{formato.lower()}', buf.getvalue(), content_type=f'image/{formato.lower()}')


def _erp_falso():
    """Patches do ERP: cadastros, última leitura e estoque fixos."""
    return [
        patch('combustivel.erp.equipamentos', return_value=EQUIPAMENTOS),
        patch('combustivel.erp.funcionarios', return_value=FUNCIONARIOS),
        patch('combustivel.erp.ultima_leitura', return_value={'data': (timezone.now() - timedelta(days=1)).isoformat(),
                                                             'horimetro': 1000.0, 'km': None}),
        patch('combustivel.erp.estoque_sga', return_value={(253, 0): {'saldo': 5000.0, 'custo_medio': 6.2,
                                                                      'minimo': 0, 'maximo': 0}}),
    ]


@override_settings(COMBUSTIVEL_PRIVADO='/tmp/combustivel-testes')
class CombustivelBase(APITestCase):
    def setUp(self):
        self.patches = [p.start() for p in _erp_falso()]
        self.addCleanup(patch.stopall)
        self.gestor = self._user('gestor', 'CombustivelGestor')
        self.operador = self._user('frentista', 'CombustivelOperador')
        self.leitor = self._user('leitor', 'CombustivelLeitura')
        self.estranho = User.objects.create_user('estranho', password='x')
        self.tanque = Tanque.objects.create(nome='Tanque S-10', filial=0, produto=253, capacidade_l=Decimal('30000'))

    def _user(self, nome, grupo):
        u = User.objects.create_user(nome, password='x')
        u.groups.add(Group.objects.get_or_create(name=grupo)[0])
        return u

    def _registrar(self, user=None, **extra):
        self.client.force_authenticate(user or self.operador)
        dados = {'tanque': self.tanque.id, 'abastecido_em': timezone.now().isoformat(), 'equipamento': 531,
                 'funcionario': 194, 'litros': '120.50', 'horimetro': '1010.0', 'foto_bomba': _foto(), 'foto_painel': _foto()}
        dados.update(extra)
        return self.client.post('/combustivel/abastecimentos/', dados, format='multipart')


class PermissoesTests(CombustivelBase):
    def test_sem_grupo_nao_entra(self):
        self.client.force_authenticate(self.estranho)
        self.assertEqual(self.client.get('/combustivel/abastecimentos/').status_code, 403)
        self.assertEqual(self.client.get('/combustivel/tanques/').status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/combustivel/abastecimentos/').status_code, (401, 403))

    def test_operador_registra_mas_nao_cancela_nem_gera_arquivo(self):
        r = self._registrar()
        self.assertEqual(r.status_code, 201, r.data)
        uid = r.data['uuid']
        r = self.client.post(f'/combustivel/abastecimentos/{uid}/cancelar/', {'motivo': 'teste de cancelamento'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.post('/combustivel/lotes/', {'formato': 'CSV'}).status_code, 403)
        self.assertEqual(self.client.post('/combustivel/tanques/', {'nome': 'x', 'capacidade_l': 1}).status_code, 403)

    def test_leitura_ve_mas_nao_registra(self):
        self._registrar()
        self.client.force_authenticate(self.leitor)
        self.assertEqual(len(self.client.get('/combustivel/abastecimentos/').data), 1)
        self.assertEqual(self._registrar(user=self.leitor).status_code, 403)

    def test_operador_ve_so_os_seus(self):
        self._registrar()
        outro = self._user('frentista2', 'CombustivelOperador')
        self.client.force_authenticate(outro)
        self.assertEqual(len(self.client.get('/combustivel/abastecimentos/').data), 0)


class RegistroTests(CombustivelBase):
    def test_registro_preenche_dados_do_sga_e_ignora_os_do_aparelho(self):
        r = self._registrar(equipamento_nome='INVENTADO', placa='XXX0000', situacao='BAIXADO')
        self.assertEqual(r.status_code, 201, r.data)
        ab = Abastecimento.objects.get()
        self.assertEqual(ab.equipamento_nome, 'VEC-CF-09 - CAMINHAO FORA EST')
        self.assertEqual(ab.placa, 'IUB-5649')
        self.assertEqual(ab.situacao, Abastecimento.REGISTRADO)
        self.assertFalse(ab.bloqueado, ab.alertas)
        self.assertEqual(r.data['codigo_integracao'], BASE_CODIGO_INTEGRACAO + ab.pk)

    def test_reenvio_com_mesmo_uuid_nao_duplica(self):
        uid = str(uuid.uuid4())
        r1 = self._registrar(uuid=uid)
        r2 = self._registrar(uuid=uid)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertEqual(Abastecimento.objects.count(), 1)
        # Outro usuário com o mesmo uuid não consegue ler o registro alheio.
        outro = self._user('frentista2', 'CombustivelOperador')
        self.assertEqual(self._registrar(user=outro, uuid=uid).status_code, 409)

    def test_foto_falsa_e_recusada_e_foto_boa_vira_jpeg_sem_metadados(self):
        falsa = SimpleUploadedFile('f.jpg', b'<?php echo 1; ?>', content_type='image/jpeg')
        r = self._registrar(foto_bomba=falsa)
        self.assertEqual(r.status_code, 400)
        r = self._registrar()
        ab = Abastecimento.objects.get(uuid=r.data['uuid'])
        with ab.foto_bomba.open('rb') as f:
            img = Image.open(f)
            self.assertEqual(img.format, 'JPEG')
            self.assertFalse(img.info.get('exif'))
        self.assertNotIn('foto_bomba', r.data)  # a foto só sai pela rota protegida
        self.client.force_authenticate(self.estranho)
        self.assertEqual(self.client.get(f'/combustivel/abastecimentos/{ab.uuid}/foto/bomba/').status_code, 403)
        self.client.force_authenticate(self.gestor)
        resp = self.client.get(f'/combustivel/abastecimentos/{ab.uuid}/foto/bomba/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'image/jpeg')

    def test_horimetro_menor_e_funcionario_sem_ident_bloqueiam(self):
        r = self._registrar(horimetro='900', funcionario=300)
        codigos = {a['codigo'] for a in r.data['alertas']}
        self.assertIn('HORIMETRO_REGRESSIVO', codigos)
        self.assertIn('FUNCIONARIO_SEM_IDENT', codigos)
        self.assertTrue(r.data['bloqueado'])
        self.client.force_authenticate(self.gestor)
        r = self.client.post(f'/combustivel/abastecimentos/{r.data["uuid"]}/conferir/')
        self.assertEqual(r.status_code, 400)

    def test_cancelar_exige_motivo_e_nao_cancela_baixado(self):
        uid = self._registrar().data['uuid']
        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post(f'/combustivel/abastecimentos/{uid}/cancelar/', {'motivo': ''}).status_code, 400)
        Abastecimento.objects.filter(uuid=uid).update(situacao=Abastecimento.BAIXADO)
        self.assertEqual(self.client.post(f'/combustivel/abastecimentos/{uid}/cancelar/',
                                          {'motivo': 'lançado errado'}).status_code, 400)


class ConferenciaTests(APITestCase):
    def test_encerrante_e_duplicidade(self):
        agora = timezone.now()
        alertas = regras.conferir(
            {'litros': 100, 'encerrante_inicial': 5000, 'encerrante_final': 5080, 'abastecido_em': agora,
             'horimetro': 10, 'foto_bomba': 1, 'foto_painel': 1},
            equipamento=EQUIPAMENTOS[0], funcionario=FUNCIONARIOS[0], ultima_leitura=None, saldo_tanque=50,
            recentes=[{'abastecido_em': agora - timedelta(minutes=10), 'horimetro': 9, 'km': None}])
        codigos = {a['codigo']: a['nivel'] for a in alertas}
        self.assertEqual(codigos['ENCERRANTE_DIVERGE'], regras.AVISO)
        self.assertEqual(codigos['POSSIVEL_DUPLICIDADE'], regras.AVISO)
        self.assertEqual(codigos['ACIMA_DO_SALDO'], regras.AVISO)
        self.assertFalse(regras.bloqueia(alertas))

    def test_anomalia_pega_consumo_fora_do_padrao(self):
        base = timezone.now() - timedelta(days=30)
        leituras = []
        hr = 1000
        for i in range(12):
            hr += 10
            litros = 200 if i == 8 else 50   # 20 L/h contra 5 L/h do resto
            leituras.append({'equipamento': 531, 'horimetro': hr, 'litros': litros,
                             'data': (base + timedelta(days=i)).isoformat()})
        achados = regras.anomalias(leituras, {531: EQUIPAMENTOS[0]})
        self.assertEqual(len(achados), 1)
        self.assertEqual(achados[0]['tipo'], 'ALTO')

    def test_painel_soma_devolucao_como_negativo(self):
        baixas = [
            {'data': '2026-10-01T10:00', 'item': 253, 'litros': 100, 'custo': 600, 'equipamento': 531,
             'centro_custo': 5481, 'origem': 'BOMBA'},
            {'data': '2026-10-01T11:00', 'item': 253, 'litros': -20, 'custo': -120, 'equipamento': 531,
             'centro_custo': 5481, 'origem': 'MANUAL'},
        ]
        p = regras.painel(baixas, [], [], {531: EQUIPAMENTOS[0]})
        self.assertEqual(p['kpis']['litros'], 80)
        self.assertEqual(p['kpis']['abastecimentos'], 1)
        self.assertEqual(p['ranking'][0]['litros'], 80)


class IntegracaoTests(CombustivelBase):
    def _abastecimento(self):
        self._registrar()
        return Abastecimento.objects.get()

    def test_lote_csv_marca_enviado_e_cancelar_devolve(self):
        ab = self._abastecimento()
        self.client.force_authenticate(self.gestor)
        r = self.client.post('/combustivel/lotes/', {'formato': 'CSV'}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        ab.refresh_from_db()
        self.assertEqual(ab.situacao, Abastecimento.EXPORTADO)
        arq = self.client.get(f'/combustivel/lotes/{r.data["id"]}/arquivo/')
        conteudo = b''.join(arq.streaming_content).decode()
        self.assertTrue(conteudo.startswith('codigo;data_hora;'))
        self.assertIn(str(ab.codigo_integracao), conteudo)
        self.assertEqual(self.client.post('/combustivel/lotes/', {'formato': 'CSV'}, format='json').status_code, 400)
        self.client.post(f'/combustivel/lotes/{r.data["id"]}/cancelar/')
        ab.refresh_from_db()
        self.assertEqual(ab.situacao, Abastecimento.REGISTRADO)

    def test_txt_tem_cabecalho_detalhe_e_total(self):
        ab = self._abastecimento()
        linhas = gerar_txt([registro(ab)]).decode('latin-1').splitlines()
        self.assertEqual([l[0] for l in linhas], ['H', 'D', 'T'])
        self.assertEqual(linhas[2], 'T00000001' + '00000000120.500')
        self.assertEqual(len(gerar_csv([registro(ab)]).decode().splitlines()), 2)

    def test_api_por_chave(self):
        ab = self._abastecimento()
        self.client.force_authenticate(self.gestor)
        r = self.client.post('/combustivel/chaves/', {'nome': 'SGA', 'ips_permitidos': '172.10.27.0/24'}, format='json')
        segredo = r.data['segredo']
        self.assertNotIn('segredo', self.client.get('/combustivel/chaves/').data[0])
        self.assertNotEqual(ChaveIntegracao.objects.get().hash_segredo, segredo)
        self.client.force_authenticate(None)

        url = '/combustivel/integracao/abastecimentos/'
        ok = {'HTTP_AUTHORIZATION': f'Chave {segredo}', 'REMOTE_ADDR': '172.10.27.50'}
        r = self.client.get(url, **ok)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['abastecimentos'][0]['codigo'], ab.codigo_integracao)
        self.assertEqual(r.data['abastecimentos'][0]['item'], '10')

        # Segredo errado, IP de fora e IP forjado no X-Forwarded-For.
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f'Chave {segredo}x', REMOTE_ADDR='172.10.27.50').status_code, 401)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f'Chave {segredo}', REMOTE_ADDR='8.8.8.8').status_code, 401)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION=f'Chave {segredo}', REMOTE_ADDR='127.0.0.1',
                                         HTTP_X_FORWARDED_FOR='172.10.27.50, 8.8.8.8').status_code, 401)
        # JWT/usuário não entra na rota da integração, nem a chave nas rotas de usuário.
        self.client.force_authenticate(self.gestor)
        self.assertIn(self.client.get(url).status_code, (401, 403))
        self.client.force_authenticate(None)
        self.assertIn(self.client.get('/combustivel/abastecimentos/', **ok).status_code, (401, 403))

        r = self.client.post('/combustivel/integracao/confirmar/', [{'codigo': ab.codigo_integracao, 'baixa': 761930}],
                             format='json', **ok)
        self.assertEqual(r.data['baixados'], 1)
        ab.refresh_from_db()
        self.assertEqual((ab.situacao, ab.baixa_sga), (Abastecimento.BAIXADO, 761930))
        # Já baixado não volta na busca.
        self.assertEqual(self.client.get(url, **ok).data['quantidade'], 0)

        chave = ChaveIntegracao.objects.get()
        self.client.force_authenticate(self.gestor)
        self.client.post(f'/combustivel/chaves/{chave.id}/revogar/')
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url, **ok).status_code, 401)

    def test_bloqueado_nao_sai_na_api_nem_no_arquivo(self):
        self._registrar(funcionario=300)
        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post('/combustivel/lotes/', {'formato': 'JSON'}, format='json').status_code, 400)

    def test_conciliacao_reconhece_a_baixa_pelo_codigo(self):
        ab = self._abastecimento()
        with patch('combustivel.erp.baixas_dos_codigos',
                   return_value={ab.codigo_integracao: {'baixa': 555, 'data': None}}):
            self.client.force_authenticate(self.gestor)
            r = self.client.post('/combustivel/abastecimentos/conciliar/')
        self.assertEqual(r.data['baixados'], 1)
        ab.refresh_from_db()
        self.assertEqual(ab.situacao, Abastecimento.BAIXADO)


class TesteEDivisaoTests(CombustivelBase):
    def test_saldo_dividido_entre_tanques_do_mesmo_produto(self):
        Tanque.objects.create(nome='Tanque S-10 B', filial=0, produto=253, capacidade_l=Decimal('10000'))
        self.client.force_authenticate(self.gestor)
        t = {x['nome']: x for x in self.client.get('/combustivel/tanques/situacao/').data['tanques']}
        # 5000 L no SGA, capacidades 30000 e 10000 → 3750 e 1250.
        self.assertEqual(t['Tanque S-10']['saldo_l'], 3750)
        self.assertEqual(t['Tanque S-10 B']['saldo_l'], 1250)
        self.assertEqual(t['Tanque S-10']['tanques_no_saldo'], 2)
        self.assertFalse(t['Tanque S-10']['acima_capacidade'])

    def test_abastecimento_de_teste_nunca_sai_para_o_sga(self):
        from django.core.management import call_command
        call_command('gerar_abastecimentos_teste', quantidade=5, usuario='gestor', stdout=io.StringIO())
        self.assertEqual(Abastecimento.objects.count(), 5)
        self.assertTrue(all(a.bloqueado for a in Abastecimento.objects.all()))
        self.client.force_authenticate(self.gestor)
        self.assertEqual(self.client.post('/combustivel/lotes/', {'formato': 'CSV'}, format='json').status_code, 400)
        t = self.client.get('/combustivel/tanques/situacao/').data['tanques'][0]
        self.assertEqual(t['pendente_l'], 0)  # não desconta do saldo
        call_command('gerar_abastecimentos_teste', apagar=True, stdout=io.StringIO())
        self.assertEqual(Abastecimento.objects.count(), 0)
