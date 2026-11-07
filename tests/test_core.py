"""Core checks run without media model downloads, network or credentials."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unscroll import db, ingest, ai, media, search
from unscroll.worker import Worker

URL='https://www.tiktok.com/@tester/video/100001'
SOURCE={'caption':'Use a 10-minute timer. Write one idea. Repeat daily.','segments':[],'warnings':[]}
ENTRY={'title':'Daily writing','key_points':[
    {'text':'Use a timer.','quote':'10-minute timer'},
    {'text':'Write an idea.','quote':'Write one idea.'},
    {'text':'Do it daily.','quote':'Repeat daily.'}],
    'action_steps':[],'specifics':['10-minute'],'topics':['writing'],
    'thin':False,'uncertainty':'','download_suggestion':True,'download_reason':'A routine to revisit.'}


class Core(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'UNSCROLL_HOME':self.temp.name})
        self.env.start();db.init()

    def tearDown(self):
        self.env.stop();self.temp.cleanup()

    def add(self):
        ingest.add([{'url':URL}]);return '100001'

    def test_favorite_export_does_not_import_history(self):
        data={'Activity':{'Favorite Videos':{'FavoriteVideoList':[{'Date':'2026-11-04','Link':URL}]},
                          'Video Browsing History':[{'Link':URL.replace('100001','100002')}]}}
        records=ingest.parse_export(json.dumps(data))
        self.assertEqual(len(records),1);self.assertEqual(records[0]['saved_date'],'2026-11-04')

    def test_reimport_preserves_completed_work(self):
        ident=self.add();db.update(ident,source=SOURCE,entry=ENTRY,status='written',saved_date='2026-11-04')
        r=ingest.add([{'url':URL+'?track=1','caption':'Caption'}])
        p=db.post(ident);self.assertEqual(r['added'],0);self.assertEqual(p['entry'],ENTRY)
        self.assertEqual(p['source'],SOURCE);self.assertEqual(p['saved_date'],'2026-11-04')

    def test_missing_favorites_section_is_explicit(self):
        with self.assertRaises(ValueError):ingest.parse_export(json.dumps({'Likes':[{'Link':URL}]}))

    def test_text_export_keeps_save_dates(self):
        rows=ingest.parse_export('Date: 2026-11-04\nLink: '+URL+'\n\nDate: 2026-11-03\nLink: '+URL.replace('100001','100002'))
        self.assertEqual([r['saved_date'] for r in rows],['2026-11-04','2026-11-03'])

    def test_identity_ignores_creator_and_tracking(self):
        self.assertEqual(ingest.canonical(URL)[0],ingest.canonical(URL.replace('@tester','@other')+'?x=y')[0])

    def test_only_full_https_tiktok_post_links(self):
        for url in ['http://www.tiktok.com/@a/video/123','https://tiktok.com.evil.test/@a/video/123',
                    'https://www.tiktok.com:9876/@a/video/123','https://vm.tiktok.com/abc']:
            with self.subTest(url=url),self.assertRaises(ValueError):ingest.canonical(url)

    def test_carousel_type_is_preserved(self):
        self.assertEqual(ingest.canonical(URL.replace('/video/','/photo/'))[2],'carousel')

    def test_non_tiktok_image_hosts_rejected(self):
        for u in ['http://127.0.0.1/a.jpg','https://tiktokcdn.com.evil.test/a.jpg','https://localhost/a.jpg']:
            with self.assertRaises(ValueError):media.safe_image_url(u)
        self.assertTrue(media.safe_image_url('https://p16.tiktokcdn.com/a.jpg'))

    def test_quotes_and_specifics_must_match(self):
        self.assertEqual(ai.verify(ai.Entry(**ENTRY),SOURCE)['title'],'Daily writing')
        bad=ai.Entry(**ENTRY);bad.key_points[0].quote='Invented quote'
        with self.assertRaises(ValueError):ai.verify(bad,SOURCE)
        bad=ai.Entry(**ENTRY);bad.key_points[0].quote='   '
        with self.assertRaises(ValueError):ai.verify(bad,SOURCE)
        bad=ai.Entry(**ENTRY);bad.specifics=['A nonexistent book']
        with self.assertRaises(ValueError):ai.verify(bad,SOURCE)

    def test_thin_entries_can_have_zero_points(self):
        e=ai.Entry(**{**ENTRY,'key_points':[],'specifics':[],'thin':True})
        self.assertEqual(ai.verify(e,{'caption':'','segments':[]})['key_points'],[])
        e.thin=False
        with self.assertRaises(ValueError):ai.verify(e,SOURCE)

    def test_duplicate_queue_jobs_are_not_added(self):
        ident=self.add();self.assertTrue(db.enqueue('process',ident));self.assertFalse(db.enqueue('process',ident))
        self.assertTrue(db.enqueue('download',ident))

    def test_cleanup_removes_temporary_media_not_downloads(self):
        ident=self.add();folder=db.home()/'tmp'/ident;folder.mkdir(parents=True)
        (folder/'video.mp4').write_bytes(b'temporary')
        incoming=db.home()/'incoming'/ident;incoming.mkdir(parents=True)
        (incoming/'clip.mp4').write_bytes(b'uploaded')
        keep=db.home()/'downloads';keep.mkdir();(keep/'video.mp4').write_bytes(b'keep')
        db.update(ident,metadata={'local_files':[str(incoming/'clip.mp4')]})
        media.cleanup(db.post(ident),folder)
        self.assertFalse(folder.exists());self.assertFalse(incoming.exists())
        self.assertTrue((keep/'video.mp4').exists());self.assertNotIn('local_files',db.post(ident)['metadata'])

    def run_job(self,kind,fn):
        ident=self.add();db.enqueue(kind,ident);db.put_setting('paused',False)
        w=Worker();fn(w,ident)

    def test_resume_does_not_extract_or_write_completed_stages(self):
        def run(w,ident):
            db.update(ident,source=SOURCE,entry=ENTRY,status='written')
            def done(_):w.stop.set()
            with patch('unscroll.media.extract') as extract,patch('unscroll.ai.write') as write,patch('unscroll.search.index',side_effect=done):w.run()
            extract.assert_not_called();write.assert_not_called()
        self.run_job('process',run)

    def test_failed_extraction_always_cleans_media(self):
        def run(w,ident):
            def clean(*args):w.stop.set()
            with patch('unscroll.media.extract',side_effect=ValueError('Capture failed')),patch('unscroll.media.cleanup',side_effect=clean) as cleanup:w.run()
            cleanup.assert_called_once();self.assertEqual(db.post(ident)['error'],'Capture failed')
        self.run_job('process',run)

    def test_failed_ai_keeps_source_for_retry(self):
        def run(w,ident):
            db.update(ident,source=SOURCE,status='extracted')
            def fail(_):w.stop.set();raise ValueError('API unavailable')
            with patch('unscroll.ai.write',side_effect=fail),patch('unscroll.media.extract') as extract:w.run()
            extract.assert_not_called();self.assertEqual(db.post(ident)['source'],SOURCE)
        self.run_job('process',run)

    def test_connection_timeout_identifies_stage_without_leaking_details(self):
        import httpx
        def run(w,ident):
            def fail(*args):
                w.stop.set()
                raise httpx.ConnectTimeout('https://private-url/?credential=secret')
            with patch('unscroll.media.extract',side_effect=fail):w.run()
            message=db.post(ident)['error']
            self.assertIn('timed out while extracting media',message)
            self.assertNotIn('private-url',message)
            self.assertNotIn('credential',message)
        self.run_job('process',run)

    def test_search_failure_does_not_lose_entry(self):
        def run(w,ident):
            db.update(ident,source=SOURCE,status='extracted')
            def fail(_):w.stop.set();raise RuntimeError('Offline model download')
            with patch('unscroll.ai.write',return_value=ENTRY),patch('unscroll.search.index',side_effect=fail):w.run()
            self.assertEqual(db.post(ident)['entry'],ENTRY);self.assertTrue(db.setting('search_warning'))
        self.run_job('process',run)

    def test_semantic_results_never_merge_entries(self):
        a=self.add();b='100002';ingest.add([{'url':URL.replace(a,b)}])
        for ident in (a,b):db.update(ident,entry=ENTRY,status='written')
        with db.connect() as c:c.executemany('INSERT INTO vectors VALUES(?,?,?)',[(a,'a','[1,0]'),(b,'b','[0.99,0.1]')])
        with patch('unscroll.search.embed',return_value=[[1,0]]):rows,warning=search.rank([db.post(a),db.post(b)],'new phrase')
        self.assertEqual(len(rows),2);self.assertEqual(len(search.similar(a)),1)
        self.assertEqual(db.post(a)['entry'],ENTRY);self.assertEqual(db.post(b)['entry'],ENTRY)


if __name__=='__main__':unittest.main()
