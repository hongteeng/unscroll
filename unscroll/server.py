import json
import os
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from . import db, ingest, search
from .ai import Proposal
from .worker import Worker
from .security import check_request

ROOT=Path(__file__).resolve().parent
os.umask(0o077)
load_dotenv(ROOT.parent/'.env')
for key,value in list(os.environ.items()):
    if key.startswith('SIFT_'): os.environ.setdefault('UNSCROLL_'+key[5:],value)


@asynccontextmanager
async def lifespan(app):
    import fcntl
    lock=(db.home()/'app.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Unscroll is already running. Open http://127.0.0.1:8765') from None
    db.init()
    # Explicitly resume after relaunch; jobs and completed stages remain persisted.
    db.put_setting('paused',True)
    worker=Worker()
    if os.environ.get('UNSCROLL_TESTING')!='1': worker.start()
    app.state.worker=worker
    try: yield
    finally:
        if worker.thread.is_alive(): worker.close()
        lock.close()


app=FastAPI(title='Unscroll',lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_only(request:Request,call_next):
    denied=check_request(request.headers.get('host',''),request.headers.get('origin'),
        request.headers.get('sec-fetch-site'),request.url.path,
        request.headers.get('x-unscroll-token',''),db.setting('token',''),os.environ.get('UNSCROLL_TESTING')=='1')
    if denied:return JSONResponse({'detail':denied[1]},status_code=denied[0])
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'"
    return response


@app.exception_handler(ValueError)
async def bad_input(request,exc):
    return JSONResponse({'detail':str(exc)},status_code=400)


def get_post(ident):
    p=db.post(ident)
    if not p: raise HTTPException(404,'Post not found')
    return p


def idle():
    with db.connect() as c:
        if c.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
            raise HTTPException(409,'Pause processing and wait for the current job to finish before making this change.')
        if not db.setting('paused',True) and c.execute("SELECT 1 FROM jobs WHERE state='queued'").fetchone():
            raise HTTPException(409,'Pause the queue before making this change. Queued work will be preserved.')


class ImportRequest(BaseModel):
    text:str=Field(max_length=30000000)


class CaptureRequest(BaseModel):
    posts:list[dict]=Field(max_length=2000)


class QueueRequest(BaseModel):
    ids:list[str]=Field(default_factory=list,max_length=20000)
    limit:int=Field(default=20,ge=1,le=20000)


class MoveRequest(BaseModel):
    primary_id:int
    extra_ids:list[int]=Field(default_factory=list,max_length=30)


class RemoveImportsRequest(BaseModel):
    ids:list[str]=Field(default_factory=list,max_length=20000)
    all_unprocessed:bool=False
    include_processed:bool=False


def removable_imports(c, body):
    if body.include_processed and (body.all_unprocessed or not body.ids):
        raise ValueError('Removing processed posts requires an explicit selection.')
    rows=c.execute('SELECT id FROM posts' if body.include_processed else "SELECT id FROM posts WHERE entry IS NULL AND download_path=''").fetchall()
    selected=set(body.ids)
    return [r['id'] for r in rows if body.all_unprocessed or r['id'] in selected]


def require_paused(c):
    # Serialize with the worker's BEGIN IMMEDIATE before checking queue state.
    paused=c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
    if not paused or not json.loads(paused[0]) or c.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone():
        raise HTTPException(409,'Pause processing and wait for the current post to finish, then try again.')


@app.post('/api/imports/remove-preview')
def remove_preview(body:RemoveImportsRequest):
    with db.connect() as c:
        ids=removable_imports(c,body)
    return {'ids':ids,'count':len(ids)}


@app.post('/api/imports/remove')
def remove_imports(body:RemoveImportsRequest):
    if body.all_unprocessed or not body.ids:
        raise ValueError('Preview and confirm an explicit selection before removing imports.')
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        require_paused(c)
        ids=removable_imports(c,body)
        if set(ids)!=set(body.ids):
            raise HTTPException(409,'Some posts changed or have completed entries or downloads. Review your selection again.')
        # Save complete records for Undo; leave attached and downloaded files untouched.
        archive={table:[] for table in ('posts','jobs','vectors','placements')}
        for ident in ids:
            for table in archive:
                column='id' if table=='posts' else 'post_id'
                archive[table].extend(dict(r) for r in c.execute(f'SELECT * FROM {table} WHERE {column}=?',(ident,)))
        batch=secrets.token_hex(16)
        c.execute('INSERT INTO removed_imports VALUES(?,?,?)',(batch,json.dumps(archive),time.time()))
        c.executemany('DELETE FROM jobs WHERE post_id=?',[(ident,) for ident in ids])
        c.executemany('DELETE FROM posts WHERE id=?',[(ident,) for ident in ids])
    return {'removed':len(ids),'message':f'Removed {len(ids)} posts from your library. Downloaded files were kept. You can undo this in Settings.'}


@app.post('/api/imports/undo')
def undo_remove_imports():
    with db.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        require_paused(c)
        row=c.execute('SELECT * FROM removed_imports ORDER BY created DESC LIMIT 1').fetchone()
        if not row: raise ValueError('There is no removal to undo.')
        archive=json.loads(row['payload'])
        if any(c.execute('SELECT 1 FROM posts WHERE id=?',(p['id'],)).fetchone() for p in archive['posts']):
            raise HTTPException(409,'Some removed posts were imported again. Undo cannot replace them.')
        for table in ('posts','jobs','vectors','placements'):
            for record in archive[table]:
                if table=='jobs':
                    record.pop('id',None)  # IDs may have been reused since removal.
                if table=='placements' and not c.execute('SELECT 1 FROM categories WHERE id=?',(record['category_id'],)).fetchone():
                    continue
                columns=list(record)
                c.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",list(record.values()))
        c.execute('DELETE FROM removed_imports WHERE id=?',(row['id'],))
    return {'message':f"Restored {len(archive['posts'])} posts. Processing remains paused."}


@app.get('/api/session')
def session():
    return {'token':db.setting('token'),'api_ready':bool(os.environ.get('ANTHROPIC_API_KEY')),
            'model':os.environ.get('UNSCROLL_CLAUDE_MODEL','claude-haiku-5-5'),
            'tools':{k:bool(shutil.which(k)) for k in ('ffmpeg','ffprobe','tesseract')},
            'download_dir':os.environ.get('UNSCROLL_DOWNLOAD_DIR',str(Path.home()/'Downloads'/'Unscroll'))}


@app.post('/api/import')
def import_text(body:ImportRequest):
    return ingest.add(ingest.parse_export(body.text))


@app.post('/api/capture')
def capture(body:CaptureRequest):
    result=ingest.add(body.posts)
    db.put_setting('last_capture',time.time())
    return result


@app.get('/api/state')
def state():
    with db.connect() as c:
        counts={r[0]:r[1] for r in c.execute('SELECT status,COUNT(*) FROM posts GROUP BY status')}
        counts['total']=c.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
        counts['ready']=c.execute('SELECT COUNT(*) FROM posts WHERE entry IS NOT NULL').fetchone()[0]
        counts['reviewed']=c.execute('SELECT COUNT(*) FROM posts WHERE reviewed=1').fetchone()[0]
        jobs=[dict(r) for r in c.execute("SELECT j.*,p.caption FROM jobs j LEFT JOIN posts p ON p.id=j.post_id WHERE j.state IN ('queued','running','failed') ORDER BY j.id DESC LIMIT 100")]
        usage=dict(c.execute('SELECT COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens FROM usage').fetchone())
        job_counts={r[0]:r[1] for r in c.execute('SELECT state,COUNT(*) FROM jobs GROUP BY state')}
        creators=[r[0] for r in c.execute("SELECT DISTINCT creator FROM posts WHERE creator!='' ORDER BY creator")]
    return {'counts':counts,'job_counts':job_counts,'jobs':jobs,'paused':db.setting('paused',True),
            'tree':db.tree(),'proposal':db.setting('proposal'),'usage':usage,'creators':creators,
            'search_warning':db.setting('search_warning',''),'last_capture':db.setting('last_capture')}


def hook_of(source):
    """Opening hook of a post: first spoken line, else first on-screen or slide text. Never the caption."""
    segs=[x for x in (source or {}).get('segments') or [] if (x.get('text') or '').strip()]
    pick=next((x for x in segs if x['label'].startswith('Speech')),None) or (segs[0] if segs else None)
    if not pick: return ''
    text=' '.join(pick['text'].split())
    if len(text)>140: text=text[:140].rsplit(' ',1)[0]+'…'
    return text


@app.get('/api/posts')
def posts(q:str='',category:int=0,creator:str='',kind:str='',status:str='',after:str='',before:str=''):
    with db.connect() as c:
        rows=[db.unpack(r) for r in c.execute('SELECT * FROM posts ORDER BY created DESC,id')]
        links={}
        for r in c.execute('SELECT * FROM placements'): links.setdefault(r['post_id'],[]).append(dict(r))
    if category:
        valid={category}|{s['id'] for r in db.tree() if r['id']==category for s in r['children']}
        rows=[p for p in rows if any(l['category_id'] in valid for l in links.get(p['id'],[]))]
    if creator: rows=[p for p in rows if p['creator']==creator]
    if kind: rows=[p for p in rows if p['kind']==kind]
    if status=='ready': rows=[p for p in rows if p['entry']]
    elif status=='unplaced': rows=[p for p in rows if p['entry'] and not links.get(p['id'])]
    elif status=='suggested': rows=[p for p in rows if p['entry'] and p['entry']['download_suggestion']]
    elif status=='failed': rows=[p for p in rows if p['status']=='failed' or p['download_error']]
    if after: rows=[p for p in rows if p['saved_date'] and p['saved_date'][:10]>=after]
    if before: rows=[p for p in rows if p['saved_date'] and p['saved_date'][:10]<=before]
    warning=''
    if q.strip(): rows,warning=search.rank(rows,q.strip())
    for p in rows:
        p['hook']=hook_of(p.get('source'))
        p.pop('source',None)
        p.pop('metadata',None)
        p['placements']=links.get(p['id'],[])
    return {'posts':rows,'warning':warning}


@app.get('/api/posts/{ident}')
def detail(ident:str):
    p=get_post(ident)
    p['hook']=hook_of(p.get('source'))
    p['overlap']=search.similar(ident)
    with db.connect() as c: p['placements']=[dict(r) for r in c.execute('SELECT * FROM placements WHERE post_id=?',(ident,))]
    return p


@app.post('/api/process')
def process(body:QueueRequest):
    if body.ids:
        ids=[i for i in body.ids if get_post(i)]
    else:
        with db.connect() as c:
            ids=[r[0] for r in c.execute("SELECT id FROM posts WHERE entry IS NULL AND status!='failed' ORDER BY created,id LIMIT ?",(body.limit,))]
    count=sum(db.enqueue('process',i) for i in ids)
    db.put_setting('paused',False)
    return {'queued':count}


@app.post('/api/pause')
def pause():
    db.put_setting('paused',True)
    return {'message':'Paused after the current job. Queued work is saved.'}


@app.post('/api/resume')
def resume():
    db.put_setting('paused',False)
    return {'message':'Processing resumed.'}


@app.post('/api/posts/{ident}/rerun')
def rerun(ident:str):
    idle(); get_post(ident)
    db.update(ident,entry=None,status='extracted' if db.post(ident)['source'] else 'captured',error='',reviewed=0)
    with db.connect() as c:
        c.execute('DELETE FROM vectors WHERE post_id=?',(ident,))
        c.execute('DELETE FROM placements WHERE post_id=?',(ident,))
    db.enqueue('process',ident); db.put_setting('paused',False)
    return {'message':'Entry queued. Saved extraction will be reused.'}


@app.post('/api/posts/{ident}/review')
def review(ident:str):
    p=get_post(ident)
    if not p['entry']: raise ValueError('There is no entry to review yet.')
    db.update(ident,reviewed=not p['reviewed'])
    return {'reviewed':not p['reviewed']}


@app.post('/api/posts/{ident}/move')
def move(ident:str,body:MoveRequest):
    idle(); get_post(ident)
    valid={s['id'] for r in db.tree() for s in r['children']}
    ids=list(dict.fromkeys([body.primary_id]+body.extra_ids))
    if any(i not in valid for i in ids): raise ValueError('Choose a subcategory from the approved tree.')
    with db.connect() as c:
        c.execute('DELETE FROM placements WHERE post_id=?',(ident,))
        c.executemany('INSERT INTO placements VALUES(?,?,?)',[(ident,i,int(i==body.primary_id)) for i in ids])
    db.update(ident,status='categorised' if db.post(ident)['entry'] else 'captured')
    return {'message':'Category placement saved.'}


@app.post('/api/posts/{ident}/media')
def local_media(ident:str,files:list[UploadFile]=File(...)):
    idle(); p=get_post(ident)
    if p['kind']=='video' and len(files)!=1: raise ValueError('Attach one video file.')
    if not files or len(files)>100: raise ValueError('Attach between 1 and 100 files.')
    folder=db.home()/'incoming'/ident
    shutil.rmtree(folder,ignore_errors=True); folder.mkdir(parents=True)
    paths=[]
    try:
        for i,f in enumerate(files):
            suffix=Path(f.filename or '').suffix.lower()
            valid=('.jpg','.jpeg','.png','.webp') if p['kind']=='carousel' else ('.mp4','.mov','.mkv','.webm','.m4v')
            if suffix not in valid: raise ValueError('Unsupported file format for this post type.')
            dest=folder/f'{i:04d}{suffix}'; size=0
            with dest.open('wb') as out:
                while chunk:=f.file.read(1024*1024):
                    size+=len(chunk)
                    if size>1024*1024*1024: raise ValueError('Each file must be smaller than 1 GB.')
                    out.write(chunk)
            paths.append(str(dest))
        meta=dict(p['metadata'] or {}); meta['local_files']=paths
        db.update(ident,metadata=meta,source=None,entry=None,status='captured',error='',reviewed=0)
        with db.connect() as c:
            c.execute('DELETE FROM vectors WHERE post_id=?',(ident,)); c.execute('DELETE FROM placements WHERE post_id=?',(ident,))
    except Exception:
        shutil.rmtree(folder,ignore_errors=True); raise
    return {'message':f'{len(paths)} file(s) attached in the order selected. Click Process to extract them.'}


@app.post('/api/categories/propose')
def propose():
    db.enqueue('propose'); db.put_setting('paused',False)
    return {'message':'Category proposal queued. Review it before approval.'}


@app.post('/api/categories/approve')
def approve(body:Proposal):
    idle()
    if db.tree(): raise ValueError('A tree is already approved. Use Rename or Merge to preserve existing placements.')
    parent_names=set()
    for r in body.categories:
        r.name=r.name.strip()
        r.subcategories=[s.strip() for s in r.subcategories]
        if not r.name or r.name.casefold() in parent_names: raise ValueError('Category names must be unique and nonempty.')
        parent_names.add(r.name.casefold())
        if any(not s or len(s)>80 for s in r.subcategories) or len({s.casefold() for s in r.subcategories})!=len(r.subcategories):
            raise ValueError('Subcategory names must be nonempty and unique within their category.')
    with db.connect() as c:
        for r in body.categories:
            parent=c.execute('INSERT INTO categories(name) VALUES(?)',(r.name,)).lastrowid
            c.executemany('INSERT INTO categories(name,parent_id) VALUES(?,?)',[(s,parent) for s in r.subcategories])
        ids=[r[0] for r in c.execute('SELECT id FROM posts WHERE entry IS NOT NULL')]
    db.put_setting('proposal',None)
    for ident in ids: db.enqueue('place',ident)
    db.put_setting('paused',False)
    return {'message':'Tree approved. Existing entries are queued for placement.'}


class Rename(BaseModel):
    name:str=Field(min_length=1,max_length=80)


@app.post('/api/categories/{ident}/rename')
def rename(ident:int,body:Rename):
    idle()
    with db.connect() as c:
        row=c.execute('SELECT * FROM categories WHERE id=?',(ident,)).fetchone()
        if not row: raise HTTPException(404,'Category not found')
        name=body.name.strip()
        if not name: raise ValueError('Enter a name.')
        duplicates=c.execute('SELECT name FROM categories WHERE parent_id IS ? AND id!=?',(row['parent_id'],ident)).fetchall()
        if any(r[0].casefold()==name.casefold() for r in duplicates): raise ValueError('That name already exists. Use Merge instead.')
        c.execute('UPDATE categories SET name=? WHERE id=?',(name,ident))
    return {'message':'Category renamed.'}


class Merge(BaseModel):
    target_id:int


def merge_leaf(c,source,target):
    for p in c.execute('SELECT * FROM placements WHERE category_id=?',(source,)).fetchall():
        c.execute('''INSERT INTO placements VALUES(?,?,?) ON CONFLICT(post_id,category_id)
          DO UPDATE SET is_primary=MAX(is_primary,excluded.is_primary)''',(p['post_id'],target,p['is_primary']))
    c.execute('DELETE FROM categories WHERE id=?',(source,))


@app.post('/api/categories/{ident}/merge')
def merge(ident:int,body:Merge):
    idle()
    if ident==body.target_id: raise ValueError('Choose another category.')
    with db.connect() as c:
        a=c.execute('SELECT * FROM categories WHERE id=?',(ident,)).fetchone()
        b=c.execute('SELECT * FROM categories WHERE id=?',(body.target_id,)).fetchone()
        if not a or not b: raise ValueError('Choose existing categories.')
        if (a['parent_id'] is None)!=(b['parent_id'] is None): raise ValueError('Merge categories at the same level.')
        if a['parent_id'] is None:
            for s in c.execute('SELECT * FROM categories WHERE parent_id=?',(ident,)).fetchall():
                target=c.execute('SELECT id FROM categories WHERE parent_id=? AND name=?',(body.target_id,s['name'])).fetchone()
                if target: merge_leaf(c,s['id'],target[0])
                else: c.execute('UPDATE categories SET parent_id=? WHERE id=?',(body.target_id,s['id']))
            c.execute('DELETE FROM categories WHERE id=?',(ident,))
        else: merge_leaf(c,ident,body.target_id)
    return {'message':'Categories merged. All entries and placements were preserved.'}


@app.post('/api/download')
def download(body:QueueRequest):
    if not body.ids: raise ValueError('Tick at least one post to download.')
    count=sum(db.enqueue('download',i) for i in body.ids if get_post(i))
    db.put_setting('paused',False)
    return {'queued':count}


@app.post('/api/search/rebuild')
def rebuild():
    db.enqueue('index'); db.put_setting('paused',False)
    return {'message':'Local semantic index rebuild queued.'}


@app.post('/api/jobs/{ident}/retry')
def retry(ident:int):
    with db.connect() as c:
        row=c.execute("SELECT * FROM jobs WHERE id=? AND state='failed'",(ident,)).fetchone()
    if not row: raise ValueError('Failed job not found.')
    added=db.enqueue(row['kind'],row['post_id'])
    if added:
        with db.connect() as c: c.execute("UPDATE jobs SET state='retried' WHERE id=?",(ident,))
    db.put_setting('paused',False)
    return {'message':'Retry queued.'}


@app.get('/api/export')
def export():
    with db.connect() as c:
        posts=[db.unpack(r) for r in c.execute('SELECT * FROM posts ORDER BY created')]
        placements=[dict(r) for r in c.execute('SELECT * FROM placements')]
    for p in posts:
        p.get('metadata',{}).pop('local_files',None)
    return Response(json.dumps({'posts':posts,'categories':db.tree(),'placements':placements},ensure_ascii=False,indent=2),
        media_type='application/json',headers={'Content-Disposition':'attachment; filename="unscroll-library.json"'})


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')


@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html')
