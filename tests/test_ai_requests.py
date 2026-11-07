import copy
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx
from unscroll import ai, db

ENTRY={'title':'Test','key_points':[{'text':'An idea','quote':'One idea'}],
       'action_steps':[],'specifics':[],'topics':[],'thin':True,'uncertainty':'',
       'download_suggestion':False,'download_reason':''}


def response(entry):
    return httpx.Response(200,json={'content':[{'type':'tool_use','name':'record','input':entry}],
                                  'usage':{'input_tokens':10,'output_tokens':5}})


class AIRequests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'UNSCROLL_HOME':self.tmp.name,'ANTHROPIC_API_KEY':'test-key'})
        self.env.start();db.init()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def ask(self):
        return ai.ask('entry','Write an entry',{'caption':'One idea'},ai.Entry)

    def test_extra_label_triggers_one_fresh_validated_request(self):
        invalid=copy.deepcopy(ENTRY);invalid['key_points'][0]['label']='Speech'
        prompts=[]
        responses=iter([response(invalid),response(ENTRY)])
        def send(*args,**kwargs):
            prompts.append(kwargs['json']['system']);return next(responses)
        with patch('httpx.post',side_effect=send) as send:
            result=self.ask()
        self.assertEqual(send.call_count,2)
        self.assertNotIn('label',result.key_points[0].model_dump())
        self.assertIn('previous result did not match',prompts[1])
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM usage').fetchone()[0],2)

    def test_repeated_invalid_response_stops_without_raw_validation_dump(self):
        invalid=copy.deepcopy(ENTRY);invalid['key_points'][0]['label']='private-value'
        with patch('httpx.post',return_value=response(invalid)) as send:
            with self.assertRaisesRegex(ValueError,'invalid structured response twice') as error:self.ask()
        self.assertEqual(send.call_count,2)
        self.assertNotIn('private-value',str(error.exception))

    def test_connect_timeout_retries_once_then_preserves_safe_error(self):
        with patch('httpx.post',side_effect=httpx.ConnectTimeout('private-url')),patch('unscroll.ai.time.sleep') as wait:
            with self.assertRaisesRegex(ValueError,'Could not connect to Claude') as error:self.ask()
        wait.assert_called_once_with(1)
        self.assertNotIn('private-url',str(error.exception))

    def test_transient_connection_failure_recovers(self):
        with patch('httpx.post',side_effect=[httpx.ConnectTimeout('timeout'),response(ENTRY)]) as send,patch('unscroll.ai.time.sleep'):
            self.assertEqual(self.ask().title,'Test')
        self.assertEqual(send.call_count,2)

    def test_read_timeout_is_not_automatically_rebilled(self):
        with patch('httpx.post',side_effect=httpx.ReadTimeout('private-url')) as send:
            with self.assertRaisesRegex(ValueError,'did not finish responding'):self.ask()
        self.assertEqual(send.call_count,1)

    def test_schema_retry_does_not_bypass_source_evidence_checks(self):
        bad=copy.deepcopy(ENTRY);bad['key_points'][0]['quote']='Invented statement'
        with patch('httpx.post',return_value=response(bad)):
            with self.assertRaisesRegex(ValueError,'quote did not match'):ai.write({'caption':'One idea'})
