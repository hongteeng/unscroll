import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


def home():
    configured=os.environ.get('UNSCROLL_HOME') or os.environ.get('SIFT_HOME')
    legacy=Path('~/Library/Application Support/Sift').expanduser()
    current=Path('~/Library/Application Support/Unscroll').expanduser()
    p = Path(configured).expanduser() if configured else (legacy if legacy.exists() and not current.exists() else current)
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


@contextmanager
def connect():
    path=home()/'unscroll.sqlite3'
    legacy=home()/'sift.sqlite3'
    if legacy.exists() and not path.exists(): path=legacy
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS posts(
          id TEXT PRIMARY KEY, url TEXT NOT NULL, creator TEXT DEFAULT '',
          caption TEXT DEFAULT '', posted_date TEXT DEFAULT '', saved_date TEXT DEFAULT '',
          kind TEXT DEFAULT 'video', metadata TEXT DEFAULT '{}',
          source TEXT, entry TEXT, status TEXT DEFAULT 'captured',
          error TEXT DEFAULT '', download_path TEXT DEFAULT '', download_error TEXT DEFAULT '',
          reviewed INTEGER DEFAULT 0, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS categories(
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE);
        CREATE UNIQUE INDEX IF NOT EXISTS category_names ON categories(name, COALESCE(parent_id,0));
        CREATE TABLE IF NOT EXISTS placements(
          post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
          category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
          is_primary INTEGER DEFAULT 0, PRIMARY KEY(post_id,category_id));
        CREATE TABLE IF NOT EXISTS jobs(
          id INTEGER PRIMARY KEY, post_id TEXT REFERENCES posts(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, state TEXT DEFAULT 'queued', error TEXT DEFAULT '', created REAL NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(COALESCE(post_id,''),kind)
          WHERE state IN ('queued','running');
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS vectors(post_id TEXT PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
          content_hash TEXT NOT NULL, embedding TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY, purpose TEXT, input_tokens INTEGER,
          output_tokens INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS removed_imports(id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL);
        ''')
        c.execute("INSERT OR IGNORE INTO settings VALUES('token',?)", (json.dumps(secrets.token_urlsafe(32)),))
        c.execute("INSERT OR IGNORE INTO settings VALUES('paused','true')")


def setting(key, default=None):
    with connect() as c:
        r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(r[0]) if r else default


def put_setting(key, value):
    with connect() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))


def enqueue(kind, post_id=None):
    with connect() as c:
        cur = c.execute('INSERT OR IGNORE INTO jobs(post_id,kind,created) VALUES(?,?,?)',
                        (post_id, kind, time.time()))
        return cur.rowcount == 1


def post(post_id):
    with connect() as c:
        r = c.execute('SELECT * FROM posts WHERE id=?', (post_id,)).fetchone()
    return unpack(r) if r else None


def unpack(row):
    d = dict(row)
    for key in ('metadata', 'source', 'entry'):
        if key in d:
            d[key] = json.loads(d[key]) if d[key] else None
    return d


def update(post_id, **fields):
    allowed = {'creator','caption','posted_date','saved_date','kind','metadata','source','entry','status',
               'error','download_path','download_error','reviewed','url'}
    if not fields.keys() <= allowed:
        raise ValueError('Unknown post field')
    fields['updated'] = time.time()
    vals = [json.dumps(v, ensure_ascii=False) if k in ('metadata','source','entry') and v is not None else v
            for k,v in fields.items()]
    with connect() as c:
        c.execute('UPDATE posts SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', (*vals,post_id))


def tree():
    with connect() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM categories ORDER BY name')]
        counts = {r[0]:r[1] for r in c.execute('SELECT category_id,COUNT(*) FROM placements GROUP BY category_id')}
    return [dict(r, count=counts.get(r['id'],0), children=[dict(s,count=counts.get(s['id'],0))
            for s in rows if s['parent_id']==r['id']]) for r in rows if r['parent_id'] is None]


def ensure_category(name):
    """Id of the top-level category with this name (any case), creating it if needed. None if it has subcategories."""
    with connect() as c:
        row=c.execute('SELECT id FROM categories WHERE parent_id IS NULL AND name=? COLLATE NOCASE',(name,)).fetchone()
        if row:
            return None if c.execute('SELECT 1 FROM categories WHERE parent_id=?',(row['id'],)).fetchone() else row['id']
        return c.execute('INSERT INTO categories(name) VALUES(?)',(name,)).lastrowid
