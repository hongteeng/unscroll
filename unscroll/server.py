import re
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
from . import db, ingest, media, search
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
        jobs=[dict(r) for r in c.execute("SELECT j.*,p.caption FROM jobs j LEFT JOIN posts p ON p.id=j.post_id WHERE j.state IN ('queued','running','failed') ORDER BY CASE j.state WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, j.id LIMIT 100")]
        usage=dict(c.execute('SELECT COALESCE(SUM(input_tokens),0) input_tokens, COALESCE(SUM(output_tokens),0) output_tokens FROM usage').fetchone())
        job_counts={r[0]:r[1] for r in c.execute('SELECT state,COUNT(*) FROM jobs GROUP BY state')}
        creators=[r[0] for r in c.execute("SELECT DISTINCT creator FROM posts WHERE creator!='' ORDER BY creator")]
    return {'counts':counts,'job_counts':job_counts,'jobs':jobs,'paused':db.setting('paused',True),
            'tree':db.tree(),'proposal':db.setting('proposal'),'usage':usage,'creators':creators,
            'search_warning':db.setting('search_warning',''),'last_capture':db.setting('last_capture'),'guidance':db.setting('category_guidance',''),'chat':chat_view()}


_SMALL={'a','i','to','in','of','it','is','me','my','we','up','on','at','or','if','so','no','do','go','be','an','as','by','he','us','you','how','the','and','for','are','not','but'}


def _words(text):
    return re.findall(r"[a-z']+",text.lower())


def _sounds_like_music(speech):
    """Whisper turns songs into looping nonsense, so heavy word repetition means it is not a spoken hook."""
    w=[x for s in speech[:3] for x in _words(s['text'])]
    return len(w)>=12 and len(set(w))/len(w)<0.6


def _clean_word(tok):
    if re.fullmatch(r"[$]?\d[\d,.]*[%kKmM]?[.,!?]?",tok): return True
    bare=tok.rstrip('.,!?:;')
    if bare.isupper() and len(bare)>1: return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z'’]*",bare): return False
    return len(bare)>=3 or bare.lower() in _SMALL


def _readable_run(text):
    """Longest run of OCR tokens that read as words, trimmed to start at a capital or number."""
    best,cur=[],[]
    for tok in text.split()+[None]:
        if tok is not None and _clean_word(tok):
            cur.append(tok); continue
        while cur and not (cur[0][0].isupper() or cur[0][0].isdigit() or cur[0][0]=='$'): cur.pop(0)
        if len(cur)>len(best): best=cur
        cur=[]
    return ' '.join(best)


def _shorten(text):
    text=' '.join(text.split())
    return text if len(text)<=140 else text[:140].rsplit(' ',1)[0]+'…'


def hook_of(source):
    """Opening hook of a post. Spoken first line; if there is no speech, or it is background music,
    the clearest on-screen or slide text. Never the caption."""
    segs=[x for x in (source or {}).get('segments') or [] if (x.get('text') or '').strip()]
    speech=[x for x in segs if x['label'].startswith('Speech')]
    visual=[x for x in segs if not x['label'].startswith('Speech')][:4]
    if speech and not (_sounds_like_music(speech) and visual): return _shorten(speech[0]['text'])
    if not visual: return ''
    runs=[_readable_run(x['text']) for x in visual]
    best=max(runs,key=lambda r:len(r.split()))
    return _shorten(best if len(best.split())>=3 else visual[0]['text'])


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
        p['thumb']=media.thumb_path(p['id']).exists()
        p.pop('source',None)
        p.pop('metadata',None)
        p['placements']=links.get(p['id'],[])
    return {'posts':rows,'warning':warning}


@app.get('/api/posts/{ident}')
def detail(ident:str):
    p=get_post(ident)
    p['hook']=hook_of(p.get('source'))
    p['thumb']=media.thumb_path(p['id']).exists()
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


class MoveMany(BaseModel):
    ids:list[str]=Field(min_length=1,max_length=500)
    category_id:int|None=None
    name:str=Field(default='',max_length=80)


@app.post('/api/posts/move-many')
def move_many(body:MoveMany):
    """The user's own move: put the selected cards in one category. No AI involved, so no extra approval step."""
    with db.connect() as c:
        if body.category_id is not None:
            valid={s['id'] for r in db.tree() for s in r['children']}|{r['id'] for r in db.tree() if not r['children']}
            if body.category_id not in valid: raise ValueError('Choose a category from your list.')
            cat=body.category_id
        else:
            name=body.name.strip()
            if not name: raise ValueError('Choose a category, or type a name for a new one.')
            cat=db.ensure_category(name)
            if not cat: raise ValueError(f'{name} has subcategories. Choose one of them instead.')
        label=c.execute('SELECT name FROM categories WHERE id=?',(cat,)).fetchone()['name']
        running={r[0] for r in c.execute("SELECT post_id FROM jobs WHERE state='running' AND post_id IS NOT NULL")}
        moved=skipped=0
        for pid in dict.fromkeys(body.ids):
            row=c.execute('SELECT entry IS NOT NULL AS has_entry FROM posts WHERE id=?',(pid,)).fetchone()
            if not row or pid in running: skipped+=1; continue
            c.execute('DELETE FROM placements WHERE post_id=?',(pid,))
            c.execute('INSERT INTO placements VALUES(?,?,1)',(pid,cat))
            if row['has_entry']: c.execute("UPDATE posts SET status='categorised' WHERE id=?",(pid,))
            moved+=1
    msg=f"Moved {moved} card{'s' if moved!=1 else ''} to {label}."
    if skipped: msg+=f" {skipped} could not move because it is being processed right now."
    return {'message':msg,'moved':moved}


@app.post('/api/posts/{ident}/move')
def move(ident:str,body:MoveRequest):
    idle(); get_post(ident)
    valid={s['id'] for r in db.tree() for s in r['children']}|{r['id'] for r in db.tree() if not r['children']}
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


class Guidance(BaseModel):
    guidance:str=Field(default='',max_length=2000)


@app.post('/api/categories/propose')
def propose(body:Guidance=Guidance()):
    db.put_setting('category_guidance',body.guidance.strip())
    db.enqueue('propose'); db.put_setting('paused',False)
    return {'message':'Category proposal queued. Review it before approval.'}


def _filing():
    """Titles and current primary category (or None) for every written entry."""
    with db.connect() as c:
        names={r['id']:r['name'] for r in c.execute('SELECT id,name FROM categories')}
        primary={r['post_id']:names.get(r['category_id']) for r in c.execute('SELECT * FROM placements WHERE is_primary=1')}
        titles={r['id']:json.loads(r['entry'])['title'] for r in c.execute('SELECT id,entry FROM posts WHERE entry IS NOT NULL')}
    return titles,primary


def chat_view():
    """The saved conversation plus a readable preview of the changes waiting for approval.
    Videos already filed somewhere else are marked with where they are now: those need explicit approval."""
    pending=db.setting('chat_pending') or []
    titles,primary=_filing()
    out=[]
    for ch in pending:
        if ch['kind']=='move':
            items=[{'id':i,'title':titles[i],'from':primary.get(i)} for i in ch['entry_ids'] if i in titles and (primary.get(i) or '').casefold()!=ch['name'].casefold()]
            label=f"Move {len(items)} save{'s' if len(items)!=1 else ''} to “{ch['name']}”"
        elif ch['kind']=='merge':
            items=[{'id':i,'title':t,'from':primary.get(i)} for i,t in titles.items() if (primary.get(i) or '').casefold()==ch['source'].casefold()]
            label=f"Merge “{ch['source']}” into “{ch['name']}”"
        elif ch['kind']=='rename': items=[]; label=f"Rename “{ch['source']}” to “{ch['name']}”"
        else: items=[]; label=f"Delete “{ch['source']}” if it is empty"
        out.append({'label':label,'to':ch['name'],'items':items})
    return {'history':db.setting('chat_history',[]) or [],'pending':out}


class ChatMessage(BaseModel):
    message:str=Field(min_length=1,max_length=2000)


@app.post('/api/categories/chat')
def chat_turn(body:ChatMessage):
    from . import ai
    ai.chat(body.message.strip())
    return chat_view()


@app.post('/api/categories/chat/discard')
def chat_discard():
    db.put_setting('chat_pending',[])
    return chat_view()


class ApplyChat(BaseModel):
    approved:list[str]=Field(default_factory=list,max_length=1000)


@app.post('/api/categories/chat/apply')
def chat_apply(body:ApplyChat=ApplyChat()):
    """Apply the pending changes. A video that already has a category only moves if the user approved it by id."""
    idle()
    approved=set(body.approved)
    titles,primary=_filing()
    changes=db.setting('chat_pending') or []
    moved=[];filed=[];held=[];notes=[]
    with db.connect() as c:
        def root(name): return c.execute('SELECT id FROM categories WHERE parent_id IS NULL AND name=? COLLATE NOCASE',(name,)).fetchone()
        def leaf(name):
            row=root(name)
            if row and c.execute('SELECT 1 FROM categories WHERE parent_id=?',(row['id'],)).fetchone(): return None
            return row['id'] if row else c.execute('INSERT INTO categories(name) VALUES(?)',(name,)).lastrowid
        def put(pid,cat):
            c.execute('DELETE FROM placements WHERE post_id=?',(pid,))
            c.execute('INSERT INTO placements VALUES(?,?,1)',(pid,cat))
            c.execute("UPDATE posts SET status='categorised' WHERE id=?",(pid,))
        for ch in changes:
            kind=ch['kind']
            if kind=='move':
                cat=leaf(ch['name'])
                if not cat: notes.append(f"{ch['name']} has subcategories, so nothing was moved there."); continue
                for pid in ch['entry_ids']:
                    if pid not in titles: continue
                    before=primary.get(pid)
                    if (before or '').casefold()==ch['name'].casefold(): continue
                    if before and pid not in approved: held.append((titles[pid],before)); continue
                    put(pid,cat)
                    (moved if before else filed).append((titles[pid],before,ch['name']))
            elif kind=='rename':
                row=root(ch['source'])
                if not row: continue
                other=root(ch['name'])
                if other and other['id']!=row['id']: kind='merge'
                else: c.execute('UPDATE categories SET name=? WHERE id=?',(ch['name'],row['id'])); notes.append(f"Renamed {ch['source']} to {ch['name']}.")
            if kind=='merge':
                a,b=root(ch['source']),leaf(ch['name'])
                if not a or not b or a['id']==b: continue
                members=[pid for pid,cat in primary.items() if (cat or '').casefold()==ch['source'].casefold()]
                if any(pid not in approved for pid in members):
                    held.extend((titles[pid],ch['source']) for pid in members if pid in titles and pid not in approved)
                    notes.append(f"Merge of {ch['source']} into {ch['name']} was not done because not every video in it was approved."); continue
                c.execute('UPDATE OR IGNORE placements SET category_id=? WHERE category_id=?',(b,a['id']))
                c.execute('DELETE FROM categories WHERE id=?',(a['id'],))
                moved.extend((titles[pid],ch['source'],ch['name']) for pid in members if pid in titles)
            elif kind=='delete':
                a=root(ch['source'])
                if a and not c.execute('SELECT 1 FROM placements WHERE category_id=?',(a['id'],)).fetchone() and not c.execute('SELECT 1 FROM categories WHERE parent_id=?',(a['id'],)).fetchone():
                    c.execute('DELETE FROM categories WHERE id=?',(a['id'],)); notes.append(f"Deleted the empty category {ch['source']}.")
                elif a: notes.append(f"{ch['source']} still has saves, so it was kept.")
    lines=['Done. Here is exactly what changed.']
    if moved:
        lines.append(f"Moved to a different category ({len(moved)}):")
        lines+=[f"• {t} — {b} → {a}" for t,b,a in moved]
    if filed:
        lines.append(f"Filed (they had no category) ({len(filed)}):")
        lines+=[f"• {t} → {a}" for t,_,a in filed[:12]]
        if len(filed)>12: lines.append(f"…and {len(filed)-12} more.")
    if held:
        lines.append(f"Left where they were, not approved ({len(held)}):")
        lines+=[f"• {t} — stays in {b}" for t,b in held[:20]]
        if len(held)>20: lines.append(f"…and {len(held)-20} more.")
    lines+=notes
    if not (moved or filed or held or notes): lines.append('Nothing needed changing.')
    db.put_setting('chat_pending',[])
    history=db.setting('chat_history',[]) or []
    history.append({'role':'assistant','text':'\n'.join(lines)})
    db.put_setting('chat_history',history[-30:])
    return chat_view()


@app.post('/api/categories/approve')
def approve(body:Proposal):
    idle()
    if db.tree(): raise ValueError('A tree is already approved. Use Rename or Merge to preserve existing placements.')
    parent_names=set()
    for r in body.categories:
        r.name=r.name.strip()
        r.subcategories=[s.strip() for s in r.subcategories if s.strip()]
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


@app.get('/thumb/{ident}')
def thumb(ident:str):
    if not ident.isdigit(): raise HTTPException(404)
    path=media.thumb_path(ident)
    if not path.is_file(): raise HTTPException(404)
    return FileResponse(path,media_type='image/jpeg')


app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')


@app.get('/')
def index():
    return FileResponse(ROOT/'static'/'index.html')
