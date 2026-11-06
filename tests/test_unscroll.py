import json
import os
import tempfile
import threading
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

os.environ['UNSCROLL_TESTING']='1'
if not importlib.util.find_spec('fastapi') or not importlib.util.find_spec('httpx'):
    raise unittest.SkipTest('Install the app requirements to run FastAPI integration tests.')
from fastapi.testclient import TestClient
from unscroll import ai, db, ingest, media, search
from unscroll.server import app
from unscroll.worker import Worker

URL='https://www.tiktok.com/@tester/video/100001'
SOURCE={'caption':'Use a 10-minute timer. Write one idea. Repeat daily.',
        'segments':[],'warnings':[]}
ENTRY={'title':'A daily writing practice','key_points':[
    {'text':'Set a short timer.','quote':'10-minute timer'},
    {'text':'Focus on one idea.','quote':'Write one idea.'},
    {'text':'Repeat each day.','quote':'Repeat daily.'}],
    'action_steps':[{'text':'Write one idea daily.','quote':'Write one idea. Repeat daily.'}],
    'specifics':['10-minute'],'topics':['writing','habits'],'thin':False,'uncertainty':'',
    'download_suggestion':True,'download_reason':'A concrete routine to revisit.'}


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'UNSCROLL_HOME':self.tmp.name,'UNSCROLL_TESTING':'1'})
        self.env.start();db.init()
        self.client=TestClient(app);self.client.__enter__()
        self.token=self.client.get('/api/session').json()['token']
        self.headers={'X-Unscroll-Token':self.token}

    def tearDown(self):
        self.client.__exit__(None,None,None);self.env.stop();self.tmp.cleanup()

    def post(self,path,data=None):
        return self.client.post('/api/'+path,json=data or {},headers=self.headers)

    def add(self,url=URL):
        ingest.add([{'url':url}]);return ingest.canonical(url)[0]

    def entry(self,ident):
        db.update(ident,source=SOURCE,entry=ENTRY,status='written')

    def test_favorites_export_excludes_watch_history_and_likes(self):
        data={'Activity':{'Favorite Videos':{'FavoriteVideoList':[{'Date':'2026-11-04 10:00:00','Link':URL}]},
                          'Video Browsing History':{'VideoList':[{'Link':URL.replace('100001','100002')}]},
                          'Like List':[{'Link':URL.replace('100001','100003')}]}}
        records=ingest.parse_export(json.dumps(data))
        self.assertEqual([r['url'] for r in records],[URL])
        self.assertEqual(records[0]['saved_date'],'2026-11-04 10:00:00')

    def test_duplicate_import_preserves_entry_and_save_date(self):
        ingest.add([{'url':URL+'?tracking=1','saved_date':'2026-11-04'}]);self.entry('100001')
        r=ingest.add([{'url':URL,'caption':'A real caption'}])
        self.assertEqual(r['added'],0);p=db.post('100001')
        self.assertEqual(p['entry'],ENTRY);self.assertEqual(p['saved_date'],'2026-11-04')
        self.assertEqual(p['caption'],'A real caption')

    def test_url_validation_rejects_non_tiktok_and_short_links(self):
        for url in ['https://tiktok.com.evil.test/@a/video/123','http://www.tiktok.com/@a/video/123',
                    'https://vm.tiktok.com/short','https://www.tiktok.com:9000/@a/video/123']:
            with self.subTest(url=url),self.assertRaises(ValueError):ingest.canonical(url)

    def test_quote_and_specifics_validation(self):
        self.assertEqual(ai.verify(ai.Entry(**ENTRY),SOURCE)['title'],ENTRY['title'])
        bad=ai.Entry(**ENTRY);bad.key_points[0].quote='Use the Pomodoro method'
        with self.assertRaises(ValueError):ai.verify(bad,SOURCE)
        bad=ai.Entry(**ENTRY);bad.specifics=['Pomodoro']
        with self.assertRaises(ValueError):ai.verify(bad,SOURCE)

    def test_thin_source_never_requires_invented_points(self):
        e=ai.Entry(**{**ENTRY,'key_points':[],'action_steps':[],'specifics':[],'thin':True})
        self.assertEqual(ai.verify(e,{'caption':'','segments':[]})['key_points'],[])
        e.thin=False
        with self.assertRaises(ValueError):ai.verify(e,SOURCE)

    def test_local_token_origin_and_host_protection(self):
        self.assertEqual(self.client.get('/api/posts').status_code,401)
        self.assertEqual(self.client.get('/api/session',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/session',headers={'Host':'evil.example'}).status_code,403)
        self.assertEqual(self.post('import',{'text':URL}).status_code,200)
        self.assertEqual(self.client.post('/api/import',json={'text':URL},headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)

    def test_empty_download_selection_never_downloads_all(self):
        self.add();self.assertEqual(self.post('download',{'ids':[]}).status_code,400)
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)

    def test_queue_idempotence_and_explicit_batch_size(self):
        for n in range(100001,100026):self.add(URL.replace('100001',str(n)))
        self.assertEqual(self.post('process',{'limit':20}).json()['queued'],20)
        self.assertEqual(self.post('process',{'limit':20}).json()['queued'],0)
        self.assertEqual(db.setting('paused'),False)

    def test_category_approval_waits_for_user_and_rejects_duplicates(self):
        p=self.add();self.entry(p)
        self.assertEqual(db.tree(),[])
        invalid={'categories':[{'name':'Work','subcategories':['Career','career']}]}
        self.assertEqual(self.post('categories/approve',invalid).status_code,400)
        valid={'categories':[{'name':'Work','subcategories':['Career','Writing']}]}
        self.assertEqual(self.post('categories/approve',valid).status_code,200)
        self.assertEqual(db.post(p)['entry'],ENTRY)
        self.assertEqual(len(db.tree()[0]['children']),2)
        self.post('pause')
        self.assertEqual(self.post('categories/approve',valid).status_code,400)

    def test_merge_preserves_one_primary_and_all_entries(self):
        a=self.add();b=self.add(URL.replace('100001','100002'));self.entry(a);self.entry(b)
        self.post('categories/approve',{'categories':[{'name':'Ideas','subcategories':['Writing','Habits']}]})
        self.post('pause')
        x,y=[s['id'] for s in db.tree()[0]['children']]
        self.post(f'posts/{a}/move',{'primary_id':x,'extra_ids':[y]})
        self.post(f'posts/{b}/move',{'primary_id':y,'extra_ids':[x]})
        self.assertEqual(self.post(f'categories/{x}/merge',{'target_id':y}).status_code,200)
        with db.connect() as c:
            for ident in (a,b):
                rows=c.execute('SELECT * FROM placements WHERE post_id=?',(ident,)).fetchall()
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['is_primary'],1)
        self.assertEqual(db.post(a)['entry'],ENTRY)

    def test_parent_merge_combines_matching_leaves(self):
        self.post('categories/approve',{'categories':[{'name':'A','subcategories':['Shared','Unique']},{'name':'B','subcategories':['Shared']}]})
        self.post('pause')
        roots=db.tree();a=next(x for x in roots if x['name']=='A');b=next(x for x in roots if x['name']=='B')
        self.assertEqual(self.post(f'categories/{a["id"]}/merge',{'target_id':b['id']}).status_code,200)
        self.assertEqual({s['name'] for s in db.tree()[0]['children']},{'Shared','Unique'})

    def test_resume_reuses_source_and_entry(self):
        ident=self.add();self.entry(ident);db.enqueue('process',ident);db.put_setting('paused',False)
        worker=Worker()
        def indexed(post):worker.stop.set()
        with patch('unscroll.media.extract') as extract,patch('unscroll.ai.write') as write,patch('unscroll.search.index',side_effect=indexed):worker.run()
        extract.assert_not_called();write.assert_not_called()

    def test_extraction_failure_still_cleans_media(self):
        ident=self.add();db.enqueue('process',ident);db.put_setting('paused',False)
        worker=Worker()
        def cleanup(p,folder):worker.stop.set()
        with patch('unscroll.media.extract',side_effect=ValueError('Capture failed')),patch('unscroll.media.cleanup',side_effect=cleanup) as clean:
            worker.run()
        clean.assert_called_once();self.assertEqual(db.post(ident)['status'],'failed')

    def test_writing_failure_preserves_extraction_for_retry(self):
        ident=self.add();db.update(ident,source=SOURCE,status='extracted');db.enqueue('process',ident);db.put_setting('paused',False)
        worker=Worker()
        def failed(_):worker.stop.set();raise ValueError('API unavailable')
        with patch('unscroll.ai.write',side_effect=failed),patch('unscroll.media.extract') as extract:worker.run()
        extract.assert_not_called();self.assertEqual(db.post(ident)['source'],SOURCE)

    def test_local_media_invalidates_previous_entry_and_index(self):
        ident=self.add();self.entry(ident)
        with db.connect() as c:c.execute('INSERT INTO vectors VALUES(?,?,?)',(ident,'old','[1,0]'))
        r=self.client.post(f'/api/posts/{ident}/media',files=[('files',('clip.mp4',b'placeholder','video/mp4'))],headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertIsNone(db.post(ident)['entry'])
        self.assertIsNone(db.post(ident)['source'])
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM vectors').fetchone()[0],0)

    def test_semantic_search_and_overlap_keep_posts_separate(self):
        a=self.add();b=self.add(URL.replace('100001','100002'));self.entry(a);self.entry(b)
        with db.connect() as c:
            c.executemany('INSERT INTO vectors VALUES(?,?,?)',[(a,'a','[1,0]'),(b,'b','[0.95,0.1]')])
        with patch('unscroll.search.embed',return_value=[[1,0]]):
            rows,warning=search.rank([db.post(a),db.post(b)],'a different phrase')
        self.assertEqual(len(rows),2);self.assertEqual(len(search.similar(a)),1)
        self.assertEqual(db.post(a)['entry'],ENTRY);self.assertEqual(db.post(b)['entry'],ENTRY)

    def test_export_does_not_include_pairing_token(self):
        self.add();r=self.client.get('/api/export',headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertNotIn(self.token,r.text)

    def test_removal_preview_protects_completed_entries_and_downloads(self):
        a=self.add();b=self.add(URL.replace('100001','100002'));c=self.add(URL.replace('100001','100003'))
        self.entry(b);db.update(c,download_path='/kept/video.mp4')
        preview=self.post('imports/remove-preview',{'all_unprocessed':True}).json()
        self.assertEqual(preview['ids'],[a]);self.assertEqual(preview['count'],1)
        self.assertEqual(self.post('imports/remove',{'ids':[a,b]}).status_code,409)
        self.assertIsNotNone(db.post(a));self.assertIsNotNone(db.post(b))
        self.assertEqual(self.post('imports/remove',{'all_unprocessed':True}).status_code,400)
        self.assertEqual(self.post('imports/remove',{'ids':[]}).status_code,400)

    def test_removal_and_undo_preserve_partial_work_and_cancel_jobs(self):
        ident=self.add();db.update(ident,source=SOURCE,status='failed',error='Previous failure')
        db.enqueue('process',ident);db.enqueue('download',ident)
        self.assertEqual(self.post('imports/remove',{'ids':[ident]}).json()['removed'],1)
        self.assertIsNone(db.post(ident))
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
        self.assertEqual(self.post('imports/undo').status_code,200)
        self.assertEqual(db.post(ident)['source'],SOURCE)
        self.assertEqual(db.post(ident)['error'],'Previous failure')
        self.assertTrue(db.setting('paused'))
        with db.connect() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],2)

    def test_removal_requires_paused_queue_and_no_running_job(self):
        ident=self.add();db.enqueue('process',ident);db.put_setting('paused',False)
        self.assertEqual(self.post('imports/remove',{'ids':[ident]}).status_code,409)
        db.put_setting('paused',True)
        with db.connect() as c:c.execute("UPDATE jobs SET state='running'")
        self.assertEqual(self.post('imports/remove',{'ids':[ident]}).status_code,409)
        self.assertIsNotNone(db.post(ident))

    def test_removal_requires_authentication(self):
        ident=self.add()
        for path in ('remove-preview','remove','undo'):
            self.assertEqual(self.client.post('/api/imports/'+path,json={'ids':[ident]}).status_code,401)
        self.assertIsNotNone(db.post(ident))

    def test_undo_does_not_overwrite_reimported_posts(self):
        ident=self.add();self.post('imports/remove',{'ids':[ident]});self.add();self.entry(ident)
        self.assertEqual(self.post('imports/undo').status_code,409)
        self.assertEqual(db.post(ident)['entry'],ENTRY)

    def test_bulk_removal_only_removes_confirmed_ids(self):
        records=[{'url':URL.replace('100001',str(n))} for n in range(100001,100802)]
        ingest.add(records)
        ids=self.post('imports/remove-preview',{'all_unprocessed':True}).json()['ids']
        self.assertEqual(len(ids),801)
        extra=self.add(URL.replace('100001','900000'))
        self.assertEqual(self.post('imports/remove',{'ids':ids}).json()['removed'],801)
        self.assertIsNotNone(db.post(extra))


if __name__=='__main__':unittest.main()
