import hashlib
import json
import math
import re
import threading
from . import db

LOCK=threading.Lock()


def content(post):
    e=post.get('entry') or {}
    return ' '.join([e.get('title',''), ' '.join(e.get('topics',[])),
        ' '.join(p['text'] for p in e.get('key_points',[])),post.get('caption','')])


def embed(texts):
    from fastembed import TextEmbedding
    # ONNX inference, CPU only. No text is sent to an embedding service.
    with LOCK:
        model=TextEmbedding(model_name='BAAI/bge-small-en-v1.5',threads=2,cache_dir=str(db.home()/'models'))
        return [v.tolist() for v in model.embed(texts,batch_size=4)]


def index(post):
    text=content(post)
    h=hashlib.sha256(text.encode()).hexdigest()
    with db.connect() as c:
        row=c.execute('SELECT content_hash FROM vectors WHERE post_id=?',(post['id'],)).fetchone()
    if row and row[0]==h: return
    vector=embed([text])[0]
    with db.connect() as c:
        c.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)',(post['id'],h,json.dumps(vector)))


def cosine(a,b):
    if len(a)!=len(b): return 0
    return sum(x*y for x,y in zip(a,b))/max(1e-12,math.sqrt(sum(x*x for x in a)*sum(y*y for y in b)))


def rank(posts,query):
    words=set(re.findall(r'\w+',query.lower()))
    vectors={}
    with db.connect() as c:
        vectors={r[0]:json.loads(r[1]) for r in c.execute('SELECT post_id,embedding FROM vectors')}
    warning=''
    qvec=None
    if vectors:
        try: qvec=embed(['Represent this sentence for searching relevant passages: '+query])[0]
        except Exception: warning='Semantic search is temporarily unavailable; showing keyword matches.'
    else: warning='Semantic index is not ready; showing keyword matches. Use Rebuild search after processing.'
    scored=[]
    for p in posts:
        terms=set(re.findall(r'\w+',content(p).lower()))
        lex=len(words&terms)/max(1,len(words))
        semantic=cosine(qvec,vectors[p['id']]) if qvec is not None and p['id'] in vectors else 0
        score=.75*semantic+.25*lex
        if lex>0 or semantic>.45: scored.append((score,p))
    scored.sort(key=lambda x:x[0],reverse=True)
    return [p for _,p in scored],warning


def similar(post_id):
    with db.connect() as c:
        rows={r[0]:json.loads(r[1]) for r in c.execute('SELECT post_id,embedding FROM vectors')}
    if post_id not in rows: return []
    scores=[(cosine(rows[post_id],v),i) for i,v in rows.items() if i!=post_id]
    scores.sort(reverse=True)
    result=[]
    for score,i in scores[:5]:
        if score<.80: continue
        p=db.post(i)
        if p and p['entry']:
            result.append({'id':i,'title':p['entry']['title'],'score':round(score,3),
                           'note':'Possible topic overlap; entries are kept separate.'})
    return result
