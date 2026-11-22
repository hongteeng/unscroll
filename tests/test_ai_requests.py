import copy
import json
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
        bad=copy.deepcopy(ENTRY);bad['key_points']=[{'text':'An idea','quote':''}]
        prompts=[]
        responses=iter([response(bad),response(ENTRY)])
        def send(*args,**kwargs):
            prompts.append(kwargs['json']['system']);return next(responses)
        with patch('httpx.post',side_effect=send):
            self.ask()
        self.assertIn('key_points',prompts[1])
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM usage').fetchone()[0],2)

    def test_repeated_invalid_response_stops_without_raw_validation_dump(self):
        invalid=copy.deepcopy(ENTRY);invalid['key_points'][0]['quote']='private-value'*200
        with patch('httpx.post',return_value=response(invalid)) as send:
            with self.assertRaisesRegex(ValueError,'invalid structured response on every attempt') as error:self.ask()
        self.assertEqual(send.call_count,3)
        self.assertNotIn('private-value',str(error.exception))

    def test_connect_timeout_retries_with_backoff_then_preserves_safe_error(self):
        with patch('httpx.post',side_effect=httpx.ConnectTimeout('private-url')) as send,patch('unscroll.ai.time.sleep') as wait:
            with self.assertRaisesRegex(ValueError,'Could not connect to Claude') as error:self.ask()
        self.assertEqual(send.call_count,ai.ATTEMPTS)
        self.assertEqual([c.args[0] for c in wait.call_args_list],[1,2,4,8])
        self.assertNotIn('private-url',str(error.exception))

    def test_overloaded_api_is_waited_out_rather_than_failing_the_post(self):
        busy=httpx.Response(503,json={'error':'overloaded'})
        with patch('httpx.post',side_effect=[busy,busy,response(ENTRY)]) as send,patch('unscroll.ai.time.sleep') as wait:
            self.assertEqual(self.ask().title,'Test')
        self.assertEqual(send.call_count,3)
        self.assertEqual([c.args[0] for c in wait.call_args_list],[1,2])

    def test_retry_after_header_sets_the_wait(self):
        paced=httpx.Response(429,headers={'retry-after':'7'},json={'error':'slow down'})
        with patch('httpx.post',side_effect=[paced,response(ENTRY)]),patch('unscroll.ai.time.sleep') as wait:
            self.ask()
        self.assertEqual(wait.call_args_list[0].args[0],7)

    def test_persistent_overload_says_the_service_is_busy(self):
        with patch('httpx.post',return_value=httpx.Response(503,json={})) as send,patch('unscroll.ai.time.sleep'):
            with self.assertRaisesRegex(ValueError,'busy or rate-limiting') as error:self.ask()
        self.assertEqual(send.call_count,ai.ATTEMPTS)
        self.assertNotIn('api-key',str(error.exception))

    def test_a_bad_key_is_not_retried(self):
        with patch('httpx.post',return_value=httpx.Response(401,json={})) as send,patch('unscroll.ai.time.sleep'):
            with self.assertRaisesRegex(ValueError,'Check the API key'):self.ask()
        self.assertEqual(send.call_count,1)

    def test_a_lone_object_where_a_list_belongs_is_reshaped(self):
        sloppy=copy.deepcopy(ENTRY);sloppy['key_points']=ENTRY['key_points'][0]
        with patch('httpx.post',return_value=response(sloppy)) as send:
            result=self.ask()
        self.assertEqual(send.call_count,1)
        self.assertEqual(result.key_points[0].quote,'One idea')

    def test_an_index_keyed_object_where_a_list_belongs_is_reshaped(self):
        sloppy=copy.deepcopy(ENTRY);sloppy['key_points']={'1':{'text':'b','quote':'idea'},'0':{'text':'a','quote':'One'}}
        with patch('httpx.post',return_value=response(sloppy)) as send:
            result=self.ask()
        self.assertEqual(send.call_count,1)
        self.assertEqual([k.text for k in result.key_points],['a','b'])

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


class SourceFits(unittest.TestCase):
    def test_a_source_within_budget_is_untouched(self):
        source={'caption':'c','segments':[{'label':'a','text':'one'}],'warnings':[]}
        fitted,note=ai.fit_source(source)
        self.assertIs(fitted,source)
        self.assertEqual(note,'')

    def test_repeated_on_screen_text_is_collapsed_before_anything_is_dropped(self):
        body='x'*400
        source={'caption':'c','warnings':[],
                'segments':[{'label':f'On screen ~{i}s','text':body} for i in range(2000)]}
        fitted,note=ai.fit_source(source)
        self.assertEqual(len(fitted['segments']),1)
        self.assertIn('collapsed',note)
        self.assertNotIn('left out',note)

    def test_text_beyond_the_budget_is_dropped_and_declared(self):
        source={'caption':'c','warnings':[],
                'segments':[{'label':f'On screen ~{i}s','text':f'line {i} '+'y'*500} for i in range(3000)]}
        fitted,note=ai.fit_source(source)
        self.assertLess(len(json.dumps(fitted,ensure_ascii=False)),600000)
        self.assertLess(len(fitted['segments']),3000)
        self.assertIn('left out',note)
        self.assertIn(note,fitted['warnings'])

    def test_the_entry_records_what_was_left_out(self):
        source={'caption':'One idea','warnings':[],
                'segments':[{'label':f'On screen ~{i}s','text':f'line {i} '+'z'*500} for i in range(3000)]}
        with patch('httpx.post',return_value=response(ENTRY)):
            saved=ai.write(source)
        self.assertIn('left out',saved['uncertainty'])


class OverlongLists(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'UNSCROLL_HOME':self.tmp.name,'ANTHROPIC_API_KEY':'test-key'})
        self.env.start();db.init()

    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def test_more_points_than_the_cap_are_trimmed_not_rejected(self):
        many=copy.deepcopy(ENTRY)
        many['key_points']=[{'text':f'idea {i}','quote':'One idea'} for i in range(9)]
        with patch('httpx.post',return_value=response(many)) as send:
            result=ai.ask('entry','Write an entry',{'caption':'One idea'},ai.Entry)
        self.assertEqual(send.call_count,1)
        self.assertEqual(len(result.key_points),7)
        self.assertEqual(result.key_points[0].text,'idea 0')
