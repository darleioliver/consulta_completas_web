"""Testes locais sem Railway/Asaas/Google: python -m unittest teste_google_ads_dm -v"""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, Mock

import google_ads_dm as dm


class GoogleAdsTests(unittest.TestCase):
    def test_prioriza_gclid_parametro(self):
        self.assertEqual(dm.identificar_clique(
            {'gclid':'CjABCDEF123456'}, {'cz_consent':'granted','cz_ads_gclid':'CjCOOKIE456789'}),
            {'gclid':'CjABCDEF123456'})

    def test_sem_consentimento_nao_captura(self):
        self.assertEqual(dm.identificar_clique({'gclid':'CjREALCLICK123'}, {}), {})
        self.assertEqual(dm.identificar_clique({'gclid':'CjREALCLICK123'}, {'cz_consent':'denied'}), {})
        self.assertEqual(dm.identificar_clique({}, {'cz_ads_gclid':'CjCOOKIE123'}), {})

    def test_cookie_compartilhado(self):
        self.assertEqual(dm.identificar_clique({}, {'cz_consent':'granted','cz_ads_wbraid':'WBRAID1234'}),
                         {'wbraid':'WBRAID1234'})

    def test_cookie_google_tag(self):
        self.assertEqual(dm.identificar_clique({}, {'cz_consent':'granted','_gcl_aw':'GCL.1760000000.CjCLICK123456'}),
                         {'gclid':'CjCLICK123456'})

    def test_rejeita_codigo_html(self):
        self.assertEqual(dm.identificar_clique({'gclid':'<script>'}, {}), {})

    def test_evento_asaas(self):
        e=dm.payload_evento({'gclid':'CjCLICK123456','asaas_payment_id':'pay_ABC0001',
                             'valor':'299.00', 'evento_em':datetime(2026,10,8,12,0,tzinfo=timezone.utc)})
        self.assertEqual(e['transactionId'], 'pay_ABC0001')
        self.assertEqual(e['conversionValue'], 299.0)
        self.assertEqual(e['currency'],'BRL')
        self.assertEqual(e['eventSource'],'WEB')
        self.assertEqual(e['adIdentifiers'],{'gclid':'CjCLICK123456'})

    def test_sem_identificador_nao_envia(self):
        with self.assertRaises(ValueError):
            dm.payload_evento({'asaas_payment_id':'pay_X', 'valor':'29.90', 'evento_em':datetime.now(timezone.utc)})

    def test_requisicao_google(self):
        with patch.dict(os.environ,{'GOOGLE_DM_CUSTOMER_ID':'123-456-7890',
                                    'GOOGLE_DM_CONVERSION_ACTION_ID':'987654321'},clear=False):
            r=dm.montar_requisicao({'transactionId':'pay_ABC','eventTimestamp':'2026-10-08T12:00:00Z'})
        self.assertEqual(r['destinations'][0]['operatingAccount']['accountId'],'1234567890')
        self.assertEqual(r['destinations'][0]['productDestinationId'],'987654321')

    @patch.object(dm.requests,'post')
    def test_envio_mock_sem_chamar_api_real(self, post):
        token=Mock(ok=True)
        token.json.return_value={'access_token':'FAKE_TOKEN'}
        resposta=Mock(ok=True)
        resposta.json.return_value={'requestId':'pedido-google-123'}
        post.side_effect=[token,resposta]
        env={'GOOGLE_DM_ENABLED':'1','GOOGLE_DM_CUSTOMER_ID':'1234567890',
             'GOOGLE_DM_CONVERSION_ACTION_ID':'45678901',
             'GOOGLE_DM_CLIENT_ID':'fake-client','GOOGLE_DM_CLIENT_SECRET':'fake-secret',
             'GOOGLE_DM_REFRESH_TOKEN':'fake-refresh'}
        with patch.dict(os.environ,env,clear=True):
            req=dm.enviar_evento({'gclid':'CjCLICK123456','asaas_payment_id':'pay_ABC',
                                  'valor':'29.90','evento_em':datetime.now(timezone.utc)})
        self.assertEqual(req,'pedido-google-123')
        self.assertEqual(post.call_count,2)
        self.assertIn('events:ingest',post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs['json']['events'][0]['conversionValue'],29.90)

    @patch.object(dm.requests, 'post')
    def test_teste_conexao_sem_compra_marca_validate_only(self, post):
        token=Mock(ok=True)
        token.json.return_value={'access_token':'TOKEN_TESTE'}
        response=Mock(ok=True)
        response.json.return_value={'requestId':'teste'}
        post.side_effect=[token,response]
        env={'GOOGLE_DM_ENABLED':'1','GOOGLE_DM_CUSTOMER_ID':'1234567890',
             'GOOGLE_DM_CONVERSION_ACTION_ID':'45678901',
             'GOOGLE_DM_CLIENT_ID':'fake-client','GOOGLE_DM_CLIENT_SECRET':'fake-secret',
             'GOOGLE_DM_REFRESH_TOKEN':'fake-refresh'}
        with patch.dict(os.environ,env,clear=True):
            result=dm.testar_integracao_sem_compra()
        self.assertTrue(result['ok'])
        self.assertEqual(result['conversoes_registradas'],0)
        self.assertEqual(post.call_count,2)
        self.assertIs(post.call_args.kwargs['json']['validateOnly'],True)
        self.assertEqual(post.call_args.kwargs['json']['events'][0]['transactionId'],'CZ-SOMENTE-VALIDACAO')

    @patch.object(dm.requests, 'post')
    def test_teste_conexao_token_invalido_nao_tenta_api(self, post):
        token=Mock(ok=False,status_code=400)
        post.return_value=token
        env={'GOOGLE_DM_ENABLED':'1','GOOGLE_DM_CUSTOMER_ID':'1234567890',
             'GOOGLE_DM_CONVERSION_ACTION_ID':'45678901',
             'GOOGLE_DM_CLIENT_ID':'fake-client','GOOGLE_DM_CLIENT_SECRET':'fake-secret',
             'GOOGLE_DM_REFRESH_TOKEN':'fake-refresh'}
        with patch.dict(os.environ,env,clear=True):
            result=dm.testar_integracao_sem_compra()
        self.assertEqual(result['motivo'],'CREDENCIAIS_RECUSADAS')
        self.assertEqual(post.call_count,1)

    @patch.object(dm.requests, 'post')
    def test_teste_conexao_api_rejeita_sem_vazar_credenciais(self, post):
        token=Mock(ok=True)
        token.json.return_value={'access_token':'SEGREDO'}
        response=Mock(ok=False,status_code=403)
        response.json.return_value={'error':{'status':'PERMISSION_DENIED','message':'SEGREDO'}}
        post.side_effect=[token,response]
        env={'GOOGLE_DM_ENABLED':'1','GOOGLE_DM_CUSTOMER_ID':'1234567890',
             'GOOGLE_DM_CONVERSION_ACTION_ID':'45678901',
             'GOOGLE_DM_CLIENT_ID':'fake-client','GOOGLE_DM_CLIENT_SECRET':'fake-secret',
             'GOOGLE_DM_REFRESH_TOKEN':'fake-refresh'}
        with patch.dict(os.environ,env,clear=True):
            result=dm.testar_integracao_sem_compra()
        self.assertFalse(result['ok'])
        self.assertEqual(result['motivo'],'PERMISSION_DENIED')
        self.assertNotIn('SEGREDO',str(result))


if __name__=='__main__':
    unittest.main()
