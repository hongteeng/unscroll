import hashlib
import json
import re
import time
from urllib.parse import urlparse, unquote
from . import db

URL_RE = re.compile(r'https?://(?:[\w-]+\.)?tiktok\.com/[^\s<>"\\]+', re.I)


def canonical(url):
    u = urlparse(url.strip().rstrip('.,;)'))
    if u.scheme != 'https' or not (u.hostname == 'tiktok.com' or (u.hostname or '').endswith('.tiktok.com')):
        raise ValueError('Only HTTPS TikTok links are accepted')
    if u.port not in (None,443) or u.username or u.password:
        raise ValueError('Invalid TikTok link')
    match = re.search(r'/(video|photo)/(\d+)',u.path)
    if not match:
        raise ValueError('Use a full TikTok /@creator/video/ID or /photo/ID link; short links must be opened first')
    kind, ident = match.groups()
    creator = re.search(r'/@([^/]+)/',u.path)
    # The numeric ID, rather than creator or tracking parameters, is the unique key.
    return ident, f'https://www.tiktok.com{u.path.rstrip("/")}', 'carousel' if kind=='photo' else 'video', unquote(creator[1]) if creator else ''


def add(records):
    added = enriched = 0
    errors = []
    for item in records:
        try:
            ident,url,kind,creator = canonical(item['url'])
            old = db.post(ident)
            meta = dict(old['metadata'] or {}) if old else {}
            # These are references, never media bytes or login cookies.
            for key in ('slides','slide_count','slides_complete','collections','hashtags','thumbnail','capture_warning'):
                if key in item:
                    meta[key] = item[key]
            if old:
                fields = {'metadata':meta}
                for key in ('caption','creator','posted_date','saved_date'):
                    if item.get(key): fields[key]=str(item[key])
                if len(fields)>1 or meta!=old['metadata']:
                    db.update(ident,**fields)
                    enriched += 1
                continue
            now = time.time()
            with db.connect() as c:
                c.execute('''INSERT INTO posts(id,url,creator,caption,posted_date,saved_date,kind,metadata,created,updated)
                  VALUES(?,?,?,?,?,?,?,?,?,?)''', (ident,url,item.get('creator') or creator,item.get('caption',''),
                  item.get('posted_date',''),item.get('saved_date',''),kind,json.dumps(meta),now,now))
            added += 1
        except (ValueError,KeyError,TypeError) as e:
            errors.append(str(e))
    return {'added':added,'enriched':enriched,'skipped':len(records)-added-enriched,'errors':errors[:30]}


def parse_export(text):
    try:
        data=json.loads(text)
    except json.JSONDecodeError:
        # TikTok's text export or a pasted list. Date belongs to the save event.
        result=[]
        for chunk in re.split(r'(?=Date\s*:)',text,flags=re.I):
            date=re.search(r'Date\s*:\s*([^\n\r]+)',chunk,re.I)
            result.extend({'url':m.group(), 'saved_date':date[1].strip() if date else ''} for m in URL_RE.finditer(chunk))
        if not result: raise ValueError('No full TikTok post links found. Extract Favorite Videos.txt or .json from the export ZIP first.')
        return result
    if isinstance(data,list):
        scope=data
    else:
        matches=[]
        def walk(node):
            if isinstance(node,dict):
                for key,value in node.items():
                    norm=re.sub(r'[^a-z]','',key.lower())
                    if norm in ('favoritevideos','favouritevideos','favoritevideolist','favouritevideolist','posts'):
                        matches.append(value)
                    else: walk(value)
            elif isinstance(node,list):
                for x in node: walk(x)
        walk(data)
        if not matches:
            raise ValueError('No Favorite Videos section found. This importer deliberately excludes watch history and likes.')
        scope=matches
    records=[]
    def collect(node):
        if isinstance(node,dict):
            url=node.get('url') or node.get('Link') or node.get('link') or node.get('URL')
            if isinstance(url,str):
                records.append({**node,'url':url,'saved_date':node.get('saved_date') or node.get('Date','')})
            else:
                for value in node.values(): collect(value)
        elif isinstance(node,list):
            for v in node: collect(v)
        elif isinstance(node,str):
            records.extend({'url':m.group()} for m in URL_RE.finditer(node))
    collect(scope)
    return records
