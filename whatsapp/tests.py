"""
Regras de visibilidade do atendimento (RH x TI).

Roda em sqlite de memória — NÃO usar o settings de produção:

    python manage.py test whatsapp.tests --settings=db_performance.settings_teste

É teste de PERMISSÃO: um erro aqui vaza conversa de um setor para o outro, e o
sintoma (alguém enxergando o que não devia) não aparece sozinho.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from whatsapp import graph_api, services
from whatsapp.models import Conversa, Fila, NumeroNegocio, WhatsAppNotificacao


class EscoposTest(TestCase):
    def setUp(self):
        self.n_rh = NumeroNegocio.objects.create(nome='RH', phone_number_id='111')
        self.n_ti = NumeroNegocio.objects.create(nome='TI', phone_number_id='222', is_padrao=True)

        self.fila_rh = Fila.objects.create(nome='RH', numero=self.n_rh)
        self.fila_ti = Fila.objects.create(nome='Suporte', numero=self.n_ti)

        def usuario(nome, grupo, fila):
            u = User.objects.create(username=nome)
            u.groups.add(Group.objects.get_or_create(name=grupo)[0])
            fila.membros.add(u)
            return u

        self.at_rh = usuario('ana_rh', 'RHWhatsapp', self.fila_rh)
        self.at_rh2 = usuario('bia_rh', 'RHWhatsapp', self.fila_rh)
        self.at_ti = usuario('caio_ti', 'TIWhatsapp', self.fila_ti)
        self.gestor_rh = usuario('gestora_rh', 'GestorWhatsapp', self.fila_rh)
        self.gestor_ti = usuario('gestor_ti', 'GestorWhatsappTI', self.fila_ti)
        self.sem_grupo = User.objects.create(username='dora')
        self.fila_ti.membros.add(self.sem_grupo)

        self.rh_sem_dono = Conversa.objects.create(contato_telefone='551', numero=self.n_rh, fila=self.fila_rh)
        self.rh_da_ana = Conversa.objects.create(contato_telefone='552', numero=self.n_rh, fila=self.fila_rh,
                                                 responsavel=self.at_rh)
        self.rh_da_bia = Conversa.objects.create(contato_telefone='553', numero=self.n_rh, fila=self.fila_rh,
                                                 responsavel=self.at_rh2)
        self.ti_sem_dono = Conversa.objects.create(contato_telefone='554', numero=self.n_ti, fila=self.fila_ti)
        self.ti_do_caio = Conversa.objects.create(contato_telefone='555', numero=self.n_ti, fila=self.fila_ti,
                                                  responsavel=self.at_ti)
        self.antiga = Conversa.objects.create(contato_telefone='556', numero=None, fila=self.fila_ti)

    def visiveis(self, usuario):
        return set(services.conversas_visiveis(usuario).values_list('contato_telefone', flat=True))

    def test_atendente_do_rh_ve_as_suas_e_as_sem_dono(self):
        """RH é restrito: atestado e salário não são assunto do colega de fila."""
        self.assertEqual(self.visiveis(self.at_rh), {'551', '552'})
        self.assertEqual(self.visiveis(self.at_rh2), {'551', '553'})

    def test_atendente_da_ti_ve_todo_o_atendimento_da_ti(self):
        """TI é compartilhado: o chamado é da equipe, pega quem estiver livre."""
        self.assertEqual(self.visiveis(self.at_ti), {'554', '555', '556'})
        outro_ti = User.objects.create(username='edu_ti')
        outro_ti.groups.add(Group.objects.get(name='TIWhatsapp'))
        self.fila_ti.membros.add(outro_ti)
        self.assertEqual(self.visiveis(outro_ti), {'554', '555', '556'})
        self.assertTrue(services.pode_atender(outro_ti, self.ti_do_caio))

    def test_atendente_nao_ve_o_outro_atendimento(self):
        self.assertNotIn('554', self.visiveis(self.at_rh))
        self.assertNotIn('552', self.visiveis(self.at_ti))

    def test_gestor_ve_todas_do_seu_escopo_e_so_dele(self):
        self.assertEqual(self.visiveis(self.gestor_rh), {'551', '552', '553'})
        # TI é o número padrão: a conversa antiga, sem número, é dele.
        self.assertEqual(self.visiveis(self.gestor_ti), {'554', '555', '556'})

    def test_conversa_antiga_sem_numero_fica_com_o_atendimento_padrao(self):
        self.assertIn('556', self.visiveis(self.at_ti))
        self.assertNotIn('556', self.visiveis(self.at_rh))

    def test_ti_compartilhado_nao_vaza_para_o_rh(self):
        """Compartilhado é dentro do número, não entre números."""
        self.assertNotIn('552', self.visiveis(self.at_ti))
        self.assertFalse(services.pode_atender(self.at_ti, self.rh_da_ana))

    def test_quem_esta_fora_dos_grupos_segue_na_regra_das_filas(self):
        self.assertEqual(self.visiveis(self.sem_grupo), {'554', '555', '556'})

    def test_staff_ve_tudo(self):
        chefe = User.objects.create(username='root', is_staff=True)
        self.assertEqual(len(self.visiveis(chefe)), 6)

    def test_pode_atender(self):
        # atendente do RH: a dele e a sem dono; nunca a do colega nem a do outro número
        self.assertTrue(services.pode_atender(self.at_rh, self.rh_da_ana))
        self.assertTrue(services.pode_atender(self.at_rh, self.rh_sem_dono))
        self.assertFalse(services.pode_atender(self.at_rh, self.rh_da_bia))
        self.assertFalse(services.pode_atender(self.at_rh, self.ti_do_caio))
        # gestor: qualquer uma do seu escopo, nenhuma do outro
        self.assertTrue(services.pode_atender(self.gestor_rh, self.rh_da_bia))
        self.assertFalse(services.pode_atender(self.gestor_rh, self.ti_do_caio))
        self.assertTrue(services.pode_atender(self.gestor_ti, self.antiga))

    def test_aviso_do_rh_vai_so_para_quem_enxerga(self):
        sem_dono = {u.username for u in services.usuarios_para_avisar(self.rh_sem_dono)}
        self.assertEqual(sem_dono, {'ana_rh', 'bia_rh', 'gestora_rh'})
        com_dono = {u.username for u in services.usuarios_para_avisar(self.rh_da_bia)}
        self.assertEqual(com_dono, {'bia_rh', 'gestora_rh'})

    def test_aviso_da_ti_vai_para_a_equipe_mesmo_com_dono(self):
        avisados = {u.username for u in services.usuarios_para_avisar(self.ti_do_caio)}
        self.assertEqual(avisados, {'caio_ti', 'gestor_ti'})

    def test_escopo_da_conversa(self):
        self.assertEqual(services.escopo_da_conversa(self.rh_sem_dono), 'RH')
        self.assertEqual(services.escopo_da_conversa(self.antiga), 'TI')

    def test_escopo_do_apelido_do_numero(self):
        """O número principal chama-se "Atendimento" no admin, não "TI"."""
        self.n_ti.nome = 'Atendimento'
        self.n_ti.save()
        self.assertEqual(services.escopo_da_conversa(self.ti_do_caio), 'TI')
        self.assertEqual(self.visiveis(self.gestor_ti), {'554', '555', '556'})
        self.assertEqual(self.visiveis(self.at_ti), {'554', '555', '556'})
        self.assertTrue(services.escopo_compartilhado('TI'))
        self.assertFalse(services.escopo_compartilhado('RH'))

    def test_numero_sem_escopo_ainda_assim_esconde_a_do_colega(self):
        """Cadastro fora dos apelidos: o atendente cai para a fila, mas continua
        vendo só o que é dele ou o que não tem dono."""
        self.n_rh.nome = 'Nome Que Ninguem Previu'
        self.n_rh.save()
        self.assertEqual(self.visiveis(self.at_rh), {'551', '552'})
        self.assertFalse(services.pode_atender(self.at_rh, self.rh_da_bia))
        # gestor sem escopo casado volta à fila inteira, não ao atendimento todo
        self.assertEqual(self.visiveis(self.gestor_rh), {'551', '552', '553'})

    def test_aviso_de_mensagem_nova_nao_atravessa_no_rh(self):
        """
        A queixa do RH: "está notificando pra Ana as minhas conversas e vice-versa".

        A causa era `tasks._notificar_nova_mensagem` avisar `fila.membros.all()`
        crua, sem passar pela visibilidade — o único ponto do módulo que ficou de
        fora quando os escopos foram criados.
        """
        avisados = lambda c: {u.username for u in services.membros_avisaveis(c)}
        # sem dono, qualquer uma das duas pode pegar: as duas são avisadas
        self.assertEqual(avisados(self.rh_sem_dono), {'ana_rh', 'bia_rh', 'gestora_rh'})
        # com dono, o aviso é de quem está atendendo
        self.assertEqual(avisados(self.rh_da_bia), {'bia_rh', 'gestora_rh'})
        self.assertEqual(avisados(self.rh_da_ana), {'ana_rh', 'gestora_rh'})

    def test_aviso_da_ti_continua_indo_para_a_fila_inteira(self):
        """A TI não pode mudar: lá o chamado é da equipe."""
        avisados = {u.username for u in services.membros_avisaveis(self.ti_do_caio)}
        self.assertEqual(avisados, {'caio_ti', 'gestor_ti', 'dora'})

    def test_responder_assume_a_conversa_so_no_rh(self):
        self.assertTrue(services.assumir_ao_responder(self.rh_sem_dono, self.at_rh))
        self.rh_sem_dono.refresh_from_db()
        self.assertEqual(self.rh_sem_dono.responsavel_id, self.at_rh.pk)

        # já tem dono: responder não rouba de quem está atendendo
        self.assertFalse(services.assumir_ao_responder(self.rh_da_bia, self.at_rh))

        # TI é compartilhado: responder não toma o chamado para si
        self.assertFalse(services.assumir_ao_responder(self.ti_sem_dono, self.at_ti))
        self.ti_sem_dono.refresh_from_db()
        self.assertIsNone(self.ti_sem_dono.responsavel_id)


class TelefoneTest(TestCase):
    """
    O mesmo celular gravado de formas diferentes.

    A Meta devolve o `wa_id` na forma canônica dela — no Brasil, às vezes sem o
    nono dígito — enquanto a agenda veio de um .vcf com e sem o 55. Sem casar as
    variantes, a resposta do cliente a um template abria conversa NOVA.
    """

    def test_variantes_de_celular_brasileiro(self):
        esperado = {'54999998888', '5554999998888', '5499998888', '555499998888'}
        for entrada in ('+55 (54) 99999-8888', '5554999998888', '54999998888',
                        '555499998888', '5499998888'):
            self.assertEqual(set(services.variantes_telefone(entrada)), esperado, entrada)

    def test_fixo_so_varia_o_55(self):
        """54 3333-4444 é fixo. Com um 9 enfiado viraria o celular de OUTRA pessoa."""
        self.assertEqual(services.variantes_telefone('5433334444'),
                         ['5433334444', '555433334444'])
        self.assertNotIn('54933334444', services.variantes_telefone('5433334444'))

    def test_numero_estrangeiro_sai_como_veio(self):
        """Tirar dois dígitos da frente de um número de fora daria outra pessoa."""
        self.assertEqual(services.variantes_telefone('4915112345678'), ['4915112345678'])
        self.assertEqual(services.variantes_telefone('12025550123'), ['12025550123'])

    def test_chave_agrupa_as_duas_formas(self):
        self.assertEqual(services.chave_telefone('54999998888'),
                         services.chave_telefone('5499998888'))

    def test_sem_digito_nenhum(self):
        self.assertEqual(services.variantes_telefone(''), [])
        self.assertEqual(services.variantes_telefone(None), [])
        self.assertEqual(services.chave_telefone('abc'), '')


class TelefoneParaEnvioTest(TestCase):
    """
    O 131026 de agosto/2026.

    Contatos gravados sem o código do país. A Cloud API lê os dígitos da frente
    como DDI, e o DDD 51 colide com o DDI do **Peru**: `51992393150` virava um
    celular peruano bem formado, que a Meta aceitava e não conseguia entregar.
    Só apareceu em DDD 51 porque o DDD precisava colidir com um DDI existente.
    """

    def test_celular_sem_ddi_ganha_o_55(self):
        """O caso do RH: DDD 51 sem o 55 é lido como Peru."""
        self.assertEqual(services.telefone_para_envio('51992393150'), '5551992393150')
        self.assertEqual(services.telefone_para_envio('(51) 99239-3150'), '5551992393150')

    def test_ddd_55_tambem_precisa_do_ddi(self):
        """
        Este passava por acaso: `55996294108` a Meta lê como Brasil porque o DDD
        é 55, mas o que sobra tem 9 dígitos e não é número nenhum.
        """
        self.assertEqual(services.telefone_para_envio('55996294108'), '5555996294108')

    def test_numero_ja_completo_nao_muda(self):
        self.assertEqual(services.telefone_para_envio('5551992393150'), '5551992393150')
        self.assertEqual(services.telefone_para_envio('555192393150'), '555192393150')
        self.assertEqual(services.telefone_para_envio('555433334444'), '555433334444')

    def test_estrangeiro_nao_ganha_ddi(self):
        """Pôr 55 num alemão daria o telefone de outra pessoa."""
        self.assertEqual(services.telefone_para_envio('4915112345678'), '4915112345678')
        self.assertEqual(services.telefone_para_envio('12025550123'), '12025550123')

    def test_ddd_inexistente_nao_ganha_ddi(self):
        """
        20 não é DDD brasileiro. Sem a lista de DDDs reais, um número americano
        de 10 dígitos teria a mesma cara de um fixo daqui e ganharia o 55.
        """
        self.assertEqual(services.telefone_para_envio('2025550123'), '2025550123')

    def test_vazio(self):
        self.assertEqual(services.telefone_para_envio(''), '')
        self.assertEqual(services.telefone_para_envio(None), '')

    def test_outra_variante_alterna_o_nono_digito(self):
        """A forma que o retry de 131026 tenta depois da falha."""
        self.assertEqual(services.outra_variante_de_envio('5551992393150'), '555192393150')
        self.assertEqual(services.outra_variante_de_envio('555192393150'), '5551992393150')
        self.assertEqual(services.outra_variante_de_envio('51992393150'), '555192393150')

    def test_fixo_nao_tem_variante(self):
        """Enfiar um 9 num fixo produz o celular de outra pessoa."""
        self.assertEqual(services.outra_variante_de_envio('555433334444'), '')
        self.assertEqual(services.outra_variante_de_envio('4915112345678'), '')


@override_settings(WHATSAPP_API_VERSION='v21.0',
                   WHATSAPP_PHONE_NUMBER_ID='999',
                   WHATSAPP_ACCESS_TOKEN='token-de-teste')
class DestinoNormalizadoNoEnvioTest(TestCase):
    """
    O `to` que sai na requisição, não o que está gravado.

    Este é o teste que fecha o buraco: mesmo que uma conversa antiga guarde o
    número sem DDI, nenhuma requisição pode sair assim. Normalizar em cada
    chamador seria esquecer um — por isso a garantia está no `graph_api`, que é
    por onde toda saída passa.
    """

    def _to_enviado(self, funcao, *args, **kwargs):
        capturado = {}

        def falso_post(url, json=None, headers=None, timeout=None, **_):
            capturado['to'] = (json or {}).get('to')

            class Resposta:
                @staticmethod
                def raise_for_status():
                    return None

                @staticmethod
                def json():
                    return {'messages': [{'id': 'wamid.teste'}]}

            return Resposta()

        with mock.patch.object(graph_api.requests, 'post', falso_post):
            funcao(*args, **kwargs)
        return capturado['to']

    def test_texto_sai_com_ddi(self):
        self.assertEqual(
            self._to_enviado(graph_api.enviar_mensagem_texto, '51992393150', 'oi'),
            '5551992393150',
        )

    def test_template_sai_com_ddi(self):
        self.assertEqual(
            self._to_enviado(graph_api.enviar_template, '51992393150', 'abertura_rh'),
            '5551992393150',
        )


class RespostaAoTemplateTest(TestCase):
    """
    O defeito relatado pelo RH: "quando envia template e a pessoa responde abre
    uma nova conversa".

    A conversa nasce com o telefone COMO ESTÁ NA AGENDA (importada de um .vcf) e
    a resposta chega com o `wa_id` da Meta, que no Brasil às vezes vem sem o nono
    dígito. Comparando a string crua, o webhook não achava a conversa e criava
    outra — o histórico do atendimento partido em dois.
    """

    def setUp(self):
        self.numero = NumeroNegocio.objects.create(
            nome='RH', phone_number_id='111', is_padrao=True, menu_automatico=False)
        self.fila = Fila.objects.create(nome='RH', numero=self.numero)
        self.conversa = Conversa.objects.create(
            contato_telefone='5554999998888',      # como o RH digitou na agenda
            numero=self.numero, fila=self.fila, estado_menu='EM_ATENDIMENTO',
        )

    def receber(self, de: str, wa_id: str = 'wamid.1'):
        from whatsapp import tasks
        tasks._processar_mensagem_recebida(
            {'metadata': {'phone_number_id': '111'}, 'contacts': []},
            {'from': de, 'id': wa_id, 'type': 'text', 'text': {'body': 'oi'}},
        )

    def test_resposta_sem_o_nono_digito_cai_na_mesma_conversa(self):
        self.receber('555499998888')               # o wa_id que a Meta devolve
        self.assertEqual(Conversa.objects.count(), 1)
        self.assertEqual(self.conversa.mensagens.count(), 1)

    def test_telefone_converge_para_o_wa_id(self):
        """Depois de casar por variante, grava a forma da Meta: é para lá que ela
        entrega, e a próxima resposta casa direto."""
        self.receber('555499998888')
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.contato_telefone, '555499998888')

    def test_outro_cliente_continua_abrindo_conversa_propria(self):
        self.receber('5554988887777', wa_id='wamid.2')
        self.assertEqual(Conversa.objects.count(), 2)


class VoltaDepoisDeEncerradaTest(TestCase):
    """
    A queixa do RH: "a Karyna encerra, 24h depois a pessoa chama de novo e só a
    Karyna é avisada".

    Reabrir mantinha o `responsavel` de quem havia encerrado. No RH o dono é
    quem recebe o aviso e o único que enxerga a conversa, então a volta do
    cliente nascia privada de uma pessoa: as colegas não eram avisadas e nem
    conseguiam abrir para assumir.
    """

    def setUp(self):
        self.numero = NumeroNegocio.objects.create(
            nome='RH', phone_number_id='111', is_padrao=True, menu_automatico=False)
        self.fila = Fila.objects.create(nome='RH', numero=self.numero, is_padrao=True)

        def atendente(nome):
            u = User.objects.create(username=nome)
            u.groups.add(Group.objects.get_or_create(name='RHWhatsapp')[0])
            self.fila.membros.add(u)
            return u

        self.karyna = atendente('karyna')
        self.colega = atendente('outra_atendente')

        self.conversa = Conversa.objects.create(
            contato_telefone='5554999998888', numero=self.numero, fila=self.fila,
            estado_menu='EM_ATENDIMENTO', status='ENCERRADA',
            responsavel=self.karyna,
        )

    def receber(self, wa_id='wamid.1'):
        from whatsapp import tasks
        tasks._processar_mensagem_recebida(
            {'metadata': {'phone_number_id': '111'}, 'contacts': []},
            {'from': '5554999998888', 'id': wa_id, 'type': 'text', 'text': {'body': 'oi'}},
        )
        self.conversa.refresh_from_db()

    def avisados(self):
        return set(WhatsAppNotificacao.objects
                   .filter(conversa=self.conversa)
                   .values_list('usuario_notificado__username', flat=True))

    def test_reabertura_solta_o_dono_anterior(self):
        self.receber()
        self.assertEqual(self.conversa.status, 'ABERTA')
        self.assertIsNone(self.conversa.responsavel_id)

    def test_a_equipe_toda_e_avisada(self):
        self.receber()
        self.assertEqual(self.avisados(), {'karyna', 'outra_atendente'})

    def test_a_colega_consegue_abrir(self):
        self.receber()
        self.assertTrue(services.pode_ver(self.colega, self.conversa))

    def test_conversa_aberta_nao_perde_o_dono(self):
        """Só a REABERTURA solta o dono — mensagem de conversa em andamento não."""
        self.conversa.status = 'ABERTA'
        self.conversa.save(update_fields=['status'])
        self.receber()
        self.assertEqual(self.conversa.responsavel_id, self.karyna.id)
        self.assertEqual(self.avisados(), {'karyna'})

    def test_botao_reabrir_tambem_devolve_para_a_fila(self):
        """Reabertura manual na Central segue a mesma regra da volta do cliente."""
        from rest_framework.test import APIRequestFactory, force_authenticate

        from whatsapp.views import ConversaViewSet

        requisicao = APIRequestFactory().post('/')
        force_authenticate(requisicao, user=self.karyna)
        resposta = ConversaViewSet.as_view({'post': 'reabrir'})(requisicao, pk=self.conversa.pk)

        self.assertEqual(resposta.status_code, 200)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.status, 'ABERTA')
        self.assertIsNone(self.conversa.responsavel_id)
        # Quem reabriu não perde a conversa de vista ao soltar o dono.
        self.assertTrue(services.pode_ver(self.karyna, self.conversa))
