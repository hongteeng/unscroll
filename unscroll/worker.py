import shutil
import threading
import time
from . import ai, db, media, search


class Worker:
    def __init__(self):
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)

    def start(self):
        with db.connect() as c:
            c.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        # A crash may leave partial media. Only committed source text is reused.
        shutil.rmtree(db.home()/'tmp',ignore_errors=True)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            if db.setting('paused',True):
                self.stop.wait(.5); continue
            with db.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                row=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
                if row: c.execute("UPDATE jobs SET state='running' WHERE id=?",(row['id'],))
            if not row:
                self.stop.wait(.5); continue
            job=dict(row)
            stage={'place':'placing an entry','download':'downloading media','propose':'proposing categories','refine':'reviewing how your saves are filed','index':'building local search'}.get(job['kind'],'loading the post')
            try:
                p=db.post(job['post_id']) if job['post_id'] else None
                if job['kind']=='process':
                    if not p['source']:
                        stage='extracting media (TikTok fetch, speech recognition or OCR)'
                        folder=db.home()/'tmp'/p['id']
                        try: media.extract(p,folder)
                        finally: media.cleanup(p,folder)
                        p=db.post(p['id'])
                    if not p['entry']:
                        stage='writing the entry with Claude'
                        entry=ai.write(p['source'])
                        db.update(p['id'],entry=entry,status='written',error='',reviewed=0)
                        p=db.post(p['id'])
                    if db.tree() and p['status']!='categorised': ai.place(p)
                    try:
                        search.index(db.post(p['id']))
                    except Exception:
                        db.put_setting('search_warning','Some entries are not indexed. Check your internet connection for the first model download, then use Rebuild search.')
                elif job['kind']=='place': ai.place(p)
                elif job['kind']=='download': media.download(p)
                elif job['kind']=='propose': ai.propose()
                elif job['kind']=='refine': ai.refine()
                elif job['kind']=='index':
                    with db.connect() as c:
                        ids=[r[0] for r in c.execute('SELECT id FROM posts WHERE entry IS NOT NULL')]
                    for ident in ids:
                        if self.stop.is_set(): raise ValueError('Index rebuild interrupted; retry to resume.')
                        search.index(db.post(ident))
                    db.put_setting('search_warning','')
                else: raise ValueError('Unknown job type')
                with db.connect() as c: c.execute("UPDATE jobs SET state='done',error='' WHERE id=?",(job['id'],))
                if p and job['kind'] in ('process','place'): db.update(p['id'],error='')
            except Exception as e:
                # Do not store response bodies or arbitrary third-party errors (may include signed media URLs).
                import httpx
                if isinstance(e,httpx.TimeoutException):
                    message=f'Connection timed out while {stage}. Check your connection and retry. Media extraction may need access to TikTok or speech-model downloads.'
                elif isinstance(e,httpx.RequestError):
                    message=f'Network connection failed while {stage}. Check your connection and retry.'
                else:
                    message=str(e) if isinstance(e,ValueError) else f'{type(e).__name__} while {stage}. Retry this post or check the local dependencies.'
                with db.connect() as c: c.execute("UPDATE jobs SET state='failed',error=? WHERE id=?",(message,job['id']))
                if job['post_id']:
                    if job['kind']=='download': db.update(job['post_id'],download_error=message)
                    else: db.update(job['post_id'],status='failed',error=message)
            self.stop.wait(2)  # One job at a time, with a small gap between posts.

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
