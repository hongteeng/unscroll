import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from unscroll import db, ingest, ai


class CollectionAndChat(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'UNSCROLL_HOME':self.temp.name,'UNSCROLL_TESTING':'1'})
        self.env.start();db.init()
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def add(self,n,collections=None):
        item={'url':f'https://www.tiktok.com/@a/video/{n}'}
        if collections: item['collections']=collections
        ingest.add([item]); return db.post(str(n))
    def test_collection_name_becomes_default_category(self):
        p=self.add(11,['Business'])
        self.assertEqual(ai.collection_name(p),'Business')
        ai.place(p)
        tree=db.tree()
        self.assertEqual([c['name'] for c in tree],['Business'])
        self.assertEqual(db.post('11')['status'],'categorised')
    def test_second_post_reuses_category_case_insensitively(self):
        ai.place(self.add(12,['Business'])); ai.place(self.add(13,['business']))
        self.assertEqual(len(db.tree()),1); self.assertEqual(db.tree()[0]['count'],2)
    def test_no_collection_means_no_default(self):
        self.assertEqual(ai.collection_name(self.add(14)),'')
    def test_chat_proposal_applies_only_after_approval(self):
        from unscroll.server import app
        self.add(15); self.add(16)
        entry={'title':'T','key_points':[],'topics':[]}
        for i in ('15','16'): db.update(i,entry=entry,status='written')
        reply=ai.ChatResult(reply='Moving both.',changes=[ai.Change(kind='move',name='Communication',entry_ids=['15','16'])])
        with patch.object(ai,'ask',return_value=reply):
            client=TestClient(app,base_url='http://127.0.0.1:8765')
            token=client.get('/api/session').json()['token']; h={'X-Unscroll-Token':token}
            view=client.post('/api/categories/chat',json={'message':'put these in Communication'},headers=h).json()
        self.assertEqual(db.tree(),[])
        self.assertIn('Communication',view['pending'][0]['label'])
        done=client.post('/api/categories/chat/apply',json={},headers=h).json()
        self.assertEqual(done['pending'],[])
        self.assertEqual(db.tree()[0]['name'],'Communication'); self.assertEqual(db.tree()[0]['count'],2)


if __name__=='__main__': unittest.main()
