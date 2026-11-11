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
    def test_plan_appears_in_chat_and_only_a_clear_approval_moves_things(self):
        from unscroll.server import app
        self.add(15); self.add(16)
        entry={'title':'T','key_points':[],'topics':[]}
        for i in ('15','16'): db.update(i,entry=entry,status='written')
        client=TestClient(app,base_url='http://127.0.0.1:8765')
        h={'X-Unscroll-Token':client.get('/api/session').json()['token']}
        say=lambda m,act,keep=(): client.post('/api/categories/chat',json={'message':m},headers=h)
        plan_calls=[ai.Blueprint(categories=['Communication']),ai.Assignments(items=[ai.Assigned(id='15',category='Communication'),ai.Assigned(id='16',category='Communication')])]
        with patch.object(ai,'converse',return_value='Communication would suit these.'):
            with patch.object(ai,'intent',return_value=ai.Intent(action='talk')):
                view=say('what could these be?','talk').json()
            self.assertEqual(db.tree(),[]); self.assertEqual(view['pending'],[])
            with patch.object(ai,'intent',return_value=ai.Intent(action='build')), patch.object(ai,'ask',side_effect=plan_calls):
                view=say('propose it','build').json()
            self.assertEqual(db.tree(),[])                       # a plan is not a change
            self.assertEqual(len(view['pending'][0]['items']),2); self.assertIn('Nothing has changed yet',view['history'][-1]['text'])
            # "Keep here" on one video, then a typed approval of the rest.
            view=client.post('/api/categories/chat/drop',json={'id':'16'},headers=h).json()
            self.assertEqual(len(view['pending'][0]['items']),1)
            db.put_setting('chat_pending',[{'kind':'move','name':'Communication','source':'','entry_ids':['15','16']}])
            with patch.object(ai,'intent',return_value=ai.Intent(action='approve',keep_ids=['16'])):
                say('16 stays, the rest are approved','approve')
        self.assertEqual(db.tree()[0]['name'],'Communication'); self.assertEqual(db.tree()[0]['count'],1)
        self.assertEqual(db.post('16')['status'],'written')
    def test_approve_without_a_plan_on_screen_does_nothing(self):
        from unscroll.server import app
        self.add(17); db.update('17',entry={'title':'T','key_points':[],'topics':[]},status='written')
        client=TestClient(app,base_url='http://127.0.0.1:8765')
        h={'X-Unscroll-Token':client.get('/api/session').json()['token']}
        with patch.object(ai,'converse',return_value='Sure.'), patch.object(ai,'intent',return_value=ai.Intent(action='approve')):
            client.post('/api/categories/chat',json={'message':'ok build now'},headers=h)
        self.assertEqual(db.tree(),[])

    def test_approved_plan_moves_are_reported(self):
        from unscroll.server import app
        entry={'title':'Speaking drill','key_points':[],'topics':[]}
        a=self.add(21,['Business']); b=self.add(22,['Business'])
        for i in ('21','22'): db.update(i,entry=entry,status='written')
        ai.place(db.post('21')); ai.place(db.post('22'))
        db.put_setting('chat_pending',[{'kind':'move','name':'Communication','source':'','entry_ids':['21','22']}])
        client=TestClient(app,base_url='http://127.0.0.1:8765')
        h={'X-Unscroll-Token':client.get('/api/session').json()['token']}
        view=client.post('/api/categories/chat/apply',json={},headers=h).json()
        names={c['name']:c['count'] for c in db.tree()}
        self.assertEqual(names.get('Communication'),2)
        report=view['history'][-1]['text']
        self.assertIn('Speaking drill — Business → Communication',report)

    def test_unapproved_move_is_listed_with_current_category_in_preview(self):
        from unscroll.server import chat_view
        self.add(23,['Business']); db.update('23',entry={'title':'Sales tips','key_points':[],'topics':[]},status='written')
        ai.place(db.post('23'))
        db.put_setting('chat_pending',[{'kind':'move','name':'Communication','source':'','entry_ids':['23']}])
        item=chat_view()['pending'][0]['items'][0]
        self.assertEqual((item['title'],item['from']),('Sales tips','Business'))

    def test_user_can_move_selected_cards_to_a_category(self):
        from unscroll.server import app
        for n in (31,32): self.add(n,['Business']); db.update(str(n),entry={'title':'T','key_points':[],'topics':[]},status='written'); ai.place(db.post(str(n)))
        client=TestClient(app,base_url='http://127.0.0.1:8765')
        h={'X-Unscroll-Token':client.get('/api/session').json()['token']}
        r=client.post('/api/posts/move-many',json={'ids':['31','32'],'name':'Communication'},headers=h).json()
        self.assertEqual(r['moved'],2)
        counts={c['name']:c['count'] for c in db.tree()}
        self.assertEqual(counts['Communication'],2); self.assertEqual(counts['Business'],0)
        bad=client.post('/api/posts/move-many',json={'ids':['31'],'category_id':9999},headers=h)
        self.assertGreaterEqual(bad.status_code,400)


if __name__=='__main__': unittest.main()
