import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from . import db


def command(args,timeout=600):
    try:
        r=subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
        return r.stdout
    except FileNotFoundError:
        raise ValueError(f'{args[0]} is missing. Run Setup.command to install the media tools.') from None
    except subprocess.CalledProcessError:
        raise ValueError(f'{args[0]} could not process this media. The post may be unavailable or the file unsupported.') from None


def ydl_options(folder):
    opts={'outtmpl':str(folder/'%(id)s.%(ext)s'),'format':'best[height<=720]/best',
          'noplaylist':True,'quiet':True,'no_warnings':True,'retries':2,'socket_timeout':30,
          'max_filesize':512*1024*1024,'sleep_interval':2,'max_sleep_interval':4,
          'restrictfilenames':True,'overwrites':True}
    # Explicit opt-in only; never read browser cookies by default.
    cookie=os.environ.get('UNSCROLL_COOKIES_FILE')
    if cookie: opts['cookiefile']=str(Path(cookie).expanduser())
    return opts


def safe_image_url(url):
    u=urlparse(url)
    host=u.hostname or ''
    allowed=('tiktokcdn.com','tiktokcdn-us.com','tiktokcdn-eu.com','byteoversea.com','ibytedtos.com','muscdn.com')
    if u.scheme!='https' or not any(host==s or host.endswith('.'+s) for s in allowed) or u.port not in (None,443):
        raise ValueError('Unrecognised TikTok image host. Attach the slide images locally instead.')
    return url


def fetch_image(url,path):
    import httpx
    safe_image_url(url)
    # Redirects are checked at every hop; arbitrary local/network hosts are never followed.
    with httpx.Client(timeout=45,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.tiktok.com/'}) as client:
        for _ in range(5):
            safe_image_url(url)
            with client.stream('GET',url) as r:
                if r.is_redirect:
                    from urllib.parse import urljoin
                    url=urljoin(url,r.headers['location']); continue
                r.raise_for_status()
                if not r.headers.get('content-type','').startswith('image/'):
                    raise ValueError('Slide URL returned no image; recapture it or attach the image locally.')
                size=0
                with path.open('wb') as f:
                    for chunk in r.iter_bytes():
                        size+=len(chunk)
                        if size>30*1024*1024: raise ValueError('A slide exceeded the 30 MB limit.')
                        f.write(chunk)
                return
    raise ValueError('Too many slide redirects.')


def _slides_via_ytdlp(post):
    """TikTok serves photo posts only after a JS challenge. yt-dlp already solves it, so reuse its page fetch.
    Uses a private yt-dlp method, so any failure falls back to the plain page request."""
    try:
        from yt_dlp import YoutubeDL
        vid=post['id']
        url=f"https://www.tiktok.com/@{post.get('creator') or '_'}/video/{vid}"
        with YoutubeDL({'quiet':True,'no_warnings':True}) as y:
            data,_status=y.get_info_extractor('TikTok')._extract_web_data_and_status(url,vid,fatal=False)
        slides=[]
        for image in ((data or {}).get('imagePost') or {}).get('images',[]):
            ref=image.get('imageURL') or {}
            urls=ref.get('urlList') or ref.get('url_list') or []
            if urls: slides.append(urls[0])
        if slides and len(slides)<=100: return slides,(data.get('desc') or post['caption'])
    except Exception:
        pass
    return None


def carousel_details(post):
    import httpx
    found_slides=_slides_via_ytdlp(post)
    if found_slides: return found_slides[0],found_slides[1],True
    # Prefer first-party page hydration data, where all slides have an explicit order.
    r=httpx.get(post['url'],timeout=40,headers={'User-Agent':'Mozilla/5.0'},follow_redirects=False)
    if r.status_code!=200: raise ValueError('TikTok did not expose this carousel. Use the extension on the open post, or attach ordered slide files.')
    payloads=re.findall(r'<script[^>]+id=["\'](?:__UNIVERSAL_DATA_FOR_REHYDRATION__|SIGI_STATE)["\'][^>]*>(.*?)</script>',r.text,re.S)
    found=[]
    def walk(x):
        if isinstance(x,dict):
            if str(x.get('id',''))==post['id'] and isinstance(x.get('imagePost'),dict): found.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    for p in payloads:
        try: walk(json.loads(p))
        except json.JSONDecodeError: pass
    for item in found:
        slides=[]
        for image in item['imagePost'].get('images',[]):
            ref=image.get('imageURL',{})
            urls=ref.get('urlList') or ref.get('url_list') or []
            if urls: slides.append(urls[0])
        if slides:
            return slides, item.get('desc',post['caption']), True
    meta=post['metadata'] or {}
    if (isinstance(meta.get('slides'),list) and 0<len(meta['slides'])<=100
        and meta.get('slide_count')==len(meta['slides']) and meta.get('slides_complete') is True):
        return meta['slides'],post['caption'],True
    raise ValueError('All carousel slides could not be verified. Open the photo post and recapture it, or attach the complete ordered slide set.')


def acquire(post,folder):
    folder.mkdir(parents=True,exist_ok=True)
    local=(post['metadata'] or {}).get('local_files',[])
    if local:
        files=[Path(p) for p in local]
        if not all(p.is_file() for p in files):
            raise ValueError('Temporary local media was already removed. Attach it again, or retry fetching the original post.')
        for i,p in enumerate(files): shutil.copyfile(p,folder/f'{i:04d}{p.suffix.lower()}')
        return sorted(folder.iterdir()),post['caption'],{}
    if post['kind']=='carousel':
        urls,caption,complete=carousel_details(post)
        for i,url in enumerate(urls):
            fetch_image(url,folder/f'{i:04d}.jpg')
            time.sleep(.3)
        return sorted(folder.iterdir()),caption,{'slides_complete':complete,'slide_count':len(urls)}
    from yt_dlp import YoutubeDL
    try:
        with YoutubeDL(ydl_options(folder)) as y:
            info=y.extract_info(post['url'],download=True)
        files=[p for p in folder.iterdir() if p.suffix.lower() in ('.mp4','.webm','.mkv','.mov','.m4v')]
        if not files: raise ValueError('No complete video was downloaded.')
        return files,info.get('description') or post['caption'],{
            'creator':info.get('uploader') or post['creator'],'posted_date':info.get('upload_date') or post['posted_date']}
    except Exception as e:
        if isinstance(e,ValueError): raise
        raise ValueError('TikTok video capture failed. The post may require login, be unavailable, or need a newer yt-dlp. Attach a local copy or configure your own cookies file.') from None


def extract(post,folder):
    files,caption,details=acquire(post,folder)
    import pytesseract
    from PIL import Image, ImageOps
    segments=[]
    warnings=[]
    def ocr(path):
        with Image.open(path) as image:
            image=ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2200,2200))
            return pytesseract.image_to_string(image,lang='eng',config='--psm 11').strip()
    if post['kind']=='carousel':
        for i,path in enumerate(files):
            text=ocr(path)
            segments.append({'label':f'Slide {i+1}','text':text})
        warnings.append('Carousel audio is not transcribed; slide text and caption are extracted. OCR can misread stylised text.')
    else:
        media=files[0]
        info=json.loads(command(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(media)],60))
        duration=float(info.get('format',{}).get('duration',0))
        if duration>3600: raise ValueError('This prototype accepts videos up to 60 minutes. No partial extraction was saved.')
        if any(s.get('codec_type')=='audio' for s in info.get('streams',[])):
            from faster_whisper import WhisperModel
            import gc
            # Load one model per task, then release it before embeddings run.
            model=WhisperModel(os.environ.get('UNSCROLL_WHISPER_MODEL','base.en'),device='cpu',compute_type='int8',cpu_threads=2,num_workers=1)
            speech,_=model.transcribe(str(media),language='en',beam_size=3,vad_filter=True)
            for s in speech:
                if s.text.strip(): segments.append({'label':f'Speech {s.start:.1f}–{s.end:.1f}s','text':s.text.strip()})
            del model
            gc.collect()
        frames=folder/'frames'; frames.mkdir()
        command(['ffmpeg','-nostdin','-v','error','-i',str(media),'-vf','fps=1,scale=960:-2','-threads','2',str(frames/'%06d.jpg')],3600)
        previous=''
        for i,path in enumerate(sorted(frames.glob('*.jpg'))):
            text=ocr(path)
            if text and text!=previous: segments.append({'label':f'On screen ~{i}s','text':text})
            previous=text
        warnings.append('On-screen text is sampled once per second; brief overlays can be missed. Speech and OCR may contain errors.')
    source={'caption':caption,'segments':segments,'warnings':warnings,'extracted_at':time.time()}
    fields={'caption':caption,'source':source,'status':'extracted','error':''}
    for k in ('creator','posted_date'):
        if details.get(k): fields[k]=details[k]
    db.update(post['id'],**fields)
    return source


def cleanup(post,folder):
    shutil.rmtree(folder,ignore_errors=True)
    incoming=db.home()/'incoming'/post['id']
    shutil.rmtree(incoming,ignore_errors=True)
    meta=dict((db.post(post['id']) or post)['metadata'] or {})
    if 'local_files' in meta:
        del meta['local_files']
        db.update(post['id'],metadata=meta)


def download(post):
    target=Path(os.environ.get('UNSCROLL_DOWNLOAD_DIR',str(Path.home()/'Downloads'/'Unscroll'))).expanduser()/post['id']
    if (target/'.unscroll-complete').is_file():
        db.update(post['id'],download_path=str(target),download_error='')
        return
    staging=db.home()/'tmp'/('download-'+post['id'])
    try:
        files,_,_=acquire(post,staging)
        target.mkdir(parents=True,exist_ok=True)
        for p in files: shutil.copyfile(p,target/p.name)
        (target/'.unscroll-complete').write_text('Downloaded by explicit selection.\n')
        db.update(post['id'],download_path=str(target),download_error='')
    except Exception:
        shutil.rmtree(target,ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging,ignore_errors=True)
