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

    def test_extra_label_is_ignored_without_a_second_request(self):
        invalid=copy.deepcopy(ENTRY);invalid['key_points'][0]['label']='Speech'
        with patch('httpx.post',return_value=response(invalid)) as send:
            result=self.ask()
        self.assertEqual(send.call_count,1)
        self.assertNotIn('label',result.key_points[0].model_dump())

    def test_list_returned_as_json_string_is_decoded(self):
        import json
        sloppy=copy.deepcopy(ENTRY);sloppy['key_points']=json.dumps(ENTRY['key_points'])
        with patch('httpx.post',return_value=response(sloppy)) as send:
            result=self.ask()
        self.assertEqual(send.call_count,1)
        self.assertEqual(result.key_points[0].quote,'One idea')

    def test_invalid_response_retries_with_the_failing_field_named(self):
        bad=copy.deepcopy(ENTRY);bad['specifics']=['x']*50
        prompts=[]
        responses=iter([response(bad),response(ENTRY)])
        def send(*args,**kwargs):
            prompts.append(kwargs['json']['system']);return next(responses)
        with patch('httpx.post',side_effect=send):
            self.ask()
        self.assertIn('specifics',prompts[1])
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM usage').fetchone()[0],2)

    def test_repeated_invalid_response_stops_without_raw_validation_dump(self):
        invalid=copy.deepcopy(ENTRY);invalid['key_points'][0]['quote']='private-value'*200
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

    def test_invented_quotes_never_reach_the_saved_entry(self):
        bad=copy.deepcopy(ENTRY);bad['key_points'][0]['quote']='Invented statement'
        with patch('httpx.post',return_value=response(bad)):
            saved=ai.write({'caption':'One idea'})
        self.assertEqual(saved['key_points'],[])
        self.assertNotIn('Invented statement',str(saved))
        self.assertIn('left out',saved['uncertainty'])
