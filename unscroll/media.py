import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from . import cookies, db


def command(args,timeout=600):
    try:
        r=subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=timeout)
        return r.stdout
    except FileNotFoundError:
        raise ValueError(f'{args[0]} is missing. Run Setup.command to install the media tools.') from None
    except subprocess.CalledProcessError:
        raise ValueError(f'{args[0]} could not process this media. The post may be unavailable or the file unsupported.') from None


_retry=threading.local()


def new_ydl(opts):
    """A yt-dlp instance. During the retry that follows a login wall it also carries the person's TikTok cookies."""
    from yt_dlp import YoutubeDL
    y=YoutubeDL(opts)
    if getattr(_retry,'with_cookies',False):
        try: cookies.apply(y)
        except cookies.CookieError as e: raise FetchError('cookies',str(e)) from None
    return y


def ydl_options(folder):
    opts={'outtmpl':str(folder/'%(id)s.%(ext)s'),'format':'best[height<=720][vcodec!=none]/best[vcodec!=none]/best',
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
        vid=post['id']
        url=f"https://www.tiktok.com/@{post.get('creator') or '_'}/video/{vid}"
        with new_ydl({'quiet':True,'no_warnings':True}) as y:
            data,_status=y.get_info_extractor('TikTok')._extract_web_data_and_status(url,vid,fatal=False)
        slides=[]
        for image in ((data or {}).get('imagePost') or {}).get('images',[]):
            ref=image.get('imageURL') or {}
            urls=ref.get('urlList') or ref.get('url_list') or []
            if urls: slides.append(urls[0])
        if slides and len(slides)<=100: return slides,(data.get('desc') or post['caption'])
    except Exception as e:
        if isinstance(e,FetchError): raise
        # A login wall is a real answer, not a reason to fall back: say so, so the post reports its true cause.
        if classify_fetch_error(str(e))=='login': raise FetchError('login') from None
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


FETCH_MESSAGES={
    'login':'TikTok only shows this video to logged-in viewers (it is marked as sensitive). Attach a copy of the video under Attach media on the post, set UNSCROLL_COOKIES_FROM_BROWSER (for example chrome) to use your own TikTok login, or set UNSCROLL_COOKIES_FILE to your own exported cookies, then process it again.',
    'login_cookies':"TikTok still refused this video with your browser's TikTok login. Check that you are signed in to TikTok in that browser and that your account may view sensitive posts, or attach a copy of the video under Attach media on the post.",
    'cookies':"Unscroll could not use your browser's TikTok login.",
    'unavailable':'TikTok says this video is unavailable. It may have been deleted or made private. Attach a copy of the video if you have one.',
    'rate_limited':'TikTok is limiting requests right now. Wait a few minutes, then process it again.',
    'other':'TikTok video capture failed for a reason Unscroll does not recognise. It may need a newer yt-dlp. Attach a local copy of the video, or try again later.'}


class FetchError(ValueError):
    """A failed TikTok fetch with a cause the UI can explain. `code` says whether trying again can help."""
    def __init__(self,code,message=None):
        self.code=code if code in FETCH_MESSAGES else 'other'
        super().__init__(message or FETCH_MESSAGES[self.code])


def classify_fetch_error(text):
    t=(text or '').lower()
    if 'log in' in t or 'login' in t or 'comfortable for some audiences' in t or 'sign in' in t: return 'login'
    if any(x in t for x in ('429','too many requests','rate limit','rate-limit')): return 'rate_limited'
    if any(x in t for x in ('unavailable','removed','deleted','private','not found','404','does not exist')): return 'unavailable'
    return 'other'


def guard_fetch(post):
    """Skip a request that is certain to fail: a login-gated post with no cookies and no attached copy."""
    meta=post.get('metadata') or {}
    if meta.get('fetch_blocked')=='login' and not meta.get('local_files') and not os.environ.get('UNSCROLL_COOKIES_FILE') and not cookies.enabled():
        raise FetchError('login')


def save_slides(urls,folder):
    """Download an ordered slide set into the working folder."""
    for i,url in enumerate(urls):
        fetch_image(url,folder/f'{i:04d}.jpg')
        time.sleep(.3)
    return sorted(folder.iterdir())


def offers_video(info):
    """Whether TikTok is actually serving a video track for this post."""
    return any(f.get('vcodec') not in (None,'none') for f in (info.get('formats') or []))


def audio_options(folder):
    """A post with no video track still has its audio, which carries the spoken content."""
    opts=ydl_options(folder)
    opts['format']='bestaudio/best'
    return opts


def video_url(post):
    """TikTok serves one id under both /photo/ and /video/, but yt-dlp only accepts /video/."""
    return re.sub(r'/photo/(\d+)',r'/video/\1',post['url'])


def fetch_video(post,folder):
    """Download the post's video, or its audio alone when TikTok serves a slideshow's music track."""
    url=video_url(post)
    with new_ydl({'quiet':True,'no_warnings':True}) as y:
        probe=y.extract_info(url,download=False)
    if not offers_video(probe):
        # TikTok serves a photo post as its music track alone. Saved as a video, it is really a slideshow:
        # take the slides when they can be read, and otherwise keep the audio rather than losing the post.
        found=_slides_via_ytdlp(post)
        if found:
            urls,caption=found
            return save_slides(urls,folder),caption,{'kind':'carousel','slides_complete':True,'slide_count':len(urls)}
        with new_ydl(audio_options(folder)) as y:
            info=y.extract_info(url,download=True)
        files=[p for p in folder.iterdir() if p.is_file()]
    else:
        with new_ydl(ydl_options(folder)) as y:
            info=y.extract_info(url,download=True)
        files=[p for p in folder.iterdir() if p.suffix.lower() in ('.mp4','.webm','.mkv','.mov','.m4v')]
    if not files: raise ValueError('No complete video was downloaded.')
    return files,info.get('description') or post['caption'],{
        'kind':'video','creator':info.get('uploader') or post['creator'],'posted_date':info.get('upload_date') or post['posted_date']}


def acquire(post,folder):
    folder.mkdir(parents=True,exist_ok=True)
    local=(post['metadata'] or {}).get('local_files',[])
    if local:
        files=[Path(p) for p in local]
        if not all(p.is_file() for p in files):
            raise ValueError('Temporary local media was already removed. Attach it again, or retry fetching the original post.')
        for i,p in enumerate(files): shutil.copyfile(p,folder/f'{i:04d}{p.suffix.lower()}')
        return sorted(folder.iterdir()),post['caption'],{}
    try:
        return acquire_remote(post,folder)
    except FetchError as e:
        if e.code!='login' or not cookies.enabled(): raise
    # A login wall, and the person has opted in to using their own TikTok login: try once more with it.
    for leftover in folder.iterdir():
        shutil.rmtree(leftover,ignore_errors=True) if leftover.is_dir() else leftover.unlink(missing_ok=True)
    _retry.with_cookies=True
    try:
        return acquire_remote(post,folder)
    except FetchError as e:
        if e.code=='login': raise FetchError('login_cookies') from None
        raise
    finally:
        _retry.with_cookies=False


def acquire_remote(post,folder):
    try:
        if post['kind']=='carousel':
            try:
                urls,caption,complete=carousel_details(post)
            except FetchError: raise
            except ValueError as no_slides:
                # Saved as a photo post, but TikTok exposes no slides for it. It may really be a video,
                # so try that before giving up; if it is not one either, report the original cause.
                try: return fetch_video(post,folder)
                except FetchError: raise
                except ValueError: raise no_slides from None
            return save_slides(urls,folder),caption,{'kind':'carousel','slides_complete':complete,'slide_count':len(urls)}
        return fetch_video(post,folder)
    except Exception as e:
        if isinstance(e,ValueError): raise
        raise FetchError(classify_fetch_error(str(e))) from e


def thumb_path(post_id):
    return db.home()/'thumbs'/f'{post_id}.jpg'


def save_thumb(post_id,image_path):
    from PIL import Image, ImageOps
    out=thumb_path(post_id); out.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(image_path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB'); im.thumbnail((540,720)); im.save(out,'JPEG',quality=82)


def thumb_from_files(post_id,files):
    """Small cover image for the library card: first slide, or a frame from the video."""
    images=[f for f in sorted(files) if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')]
    if images: return save_thumb(post_id,images[0])
    videos=[f for f in files if f.suffix.lower() in ('.mp4','.webm','.mkv','.mov','.m4v')]
    if not videos: return
    frame=videos[0].parent/'_thumb.jpg'
    for at in ('1','0'):
        try:
            command(['ffmpeg','-nostdin','-v','error','-y','-ss',at,'-i',str(videos[0]),'-frames:v','1',str(frame)],120)
            if frame.exists(): break
        except ValueError: continue
    if frame.exists():
        try: save_thumb(post_id,frame)
        finally: frame.unlink(missing_ok=True)


def extract(post,folder):
    files,caption,details=acquire(post,folder)
    # acquire may find that a post saved as a video is really a slideshow, and say so here.
    kind=details.get('kind') or post['kind']
    try: thumb_from_files(post['id'],files)
    except Exception: pass  # a missing cover never blocks extraction
    import pytesseract
    from PIL import Image, ImageOps
    segments=[]
    warnings=[]
    def ocr(path):
        with Image.open(path) as image:
            image=ImageOps.exif_transpose(image).convert('RGB')
            image.thumbnail((2200,2200))
            return pytesseract.image_to_string(image,lang='eng',config='--psm 11').strip()
    if kind=='carousel':
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
        if any(s.get('codec_type')=='video' for s in info.get('streams',[])):
            frames=folder/'frames'; frames.mkdir()
            command(['ffmpeg','-nostdin','-v','error','-i',str(media),'-vf','fps=1,scale=960:-2','-threads','2',str(frames/'%06d.jpg')],3600)
            previous=''
            for i,path in enumerate(sorted(frames.glob('*.jpg'))):
                text=ocr(path)
                if text and text!=previous: segments.append({'label':f'On screen ~{i}s','text':text})
                previous=text
            warnings.append('On-screen text is sampled once per second; brief overlays can be missed. Speech and OCR may contain errors.')
        else:
            warnings.append('TikTok served only this post\'s audio, so there is no on-screen text: the transcript and caption are everything that could be extracted.')
    source={'caption':caption,'segments':segments,'warnings':warnings,'extracted_at':time.time()}
    fields={'caption':caption,'source':source,'status':'extracted','error':''}
    if kind!=post['kind']: fields['kind']=kind  # a slideshow saved as a video is recorded as what it is
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
