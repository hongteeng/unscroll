"""Optional use of the person's own TikTok login, for posts TikTok shows only to a logged-in viewer.

Nothing here runs unless UNSCROLL_COOKIES_FROM_BROWSER is set (for example "chrome" or "chrome:Profile 2").
The guard rails, each deliberate:
  * off by default, and read only after a post has actually hit a login wall, never up front;
  * every cookie that is not for tiktok.com is thrown away the moment the browser's jar is read;
  * the TikTok cookies live in this process's memory only: never written to a file, the database or a log;
  * they are kept for a short time, so one Keychain prompt serves a whole run rather than one per post;
  * a failure to read them is remembered briefly, so a declined prompt is not asked again for every post;
  * errors raised from here carry fixed text, never anything the browser or the cookies contained."""
import os
import threading
import time

ENV='UNSCROLL_COOKIES_FROM_BROWSER'
LIFETIME=30*60      # how long read cookies are kept in memory
FAILURE_PAUSE=10*60  # how long a failed read is remembered before another attempt

_lock=threading.Lock()
_kept={'cookies':None,'until':0.0,'failed_until':0.0}


class CookieError(ValueError):
    """Reading the browser's cookies failed. The text is fixed and never includes browser or cookie contents."""


class _Silent:
    """yt-dlp's cookie reader logs paths and details; none of it is wanted in this app's output."""
    def debug(self,*a,**k): pass
    info=warning=error=stdout=stderr=debug


def enabled():
    return bool((os.environ.get(ENV) or '').strip())


def setting():
    """(browser, profile) from the environment, or raise CookieError if the value is not a supported browser."""
    from yt_dlp.cookies import SUPPORTED_BROWSERS
    raw=(os.environ.get(ENV) or '').strip()
    name,_,profile=raw.partition(':')
    name=name.strip().lower()
    if name not in SUPPORTED_BROWSERS:
        raise CookieError(f'{ENV} names a browser Unscroll cannot read. Use one of: {", ".join(sorted(SUPPORTED_BROWSERS))}.')
    return name,(profile.strip() or None)


def is_tiktok(domain):
    d=(domain or '').lstrip('.').lower()
    return d=='tiktok.com' or d.endswith('.tiktok.com')


def tiktok_only(jar):
    """Only the TikTok cookies from a jar, as a new list. The caller drops the full jar straight after."""
    return [c for c in jar if is_tiktok(c.domain)]


def _read():
    from yt_dlp.cookies import extract_cookies_from_browser
    name,profile=setting()
    try:
        jar=extract_cookies_from_browser(name,profile,logger=_Silent())
    except Exception:
        # The reason can name paths or Keychain details; the person only needs to know what to try.
        raise CookieError("Unscroll could not read your browser's cookies. If your Mac asked for access to the browser's Keychain item, allow it; "
                          'otherwise check that the browser name in '+ENV+' is installed and that you are signed in to TikTok in it.') from None
    kept=tiktok_only(jar)
    del jar   # the rest of the browser's cookies are not kept for a moment longer than this
    if not kept:
        raise CookieError('No TikTok cookies were found in that browser. Sign in to TikTok there, then retry.')
    return kept


def tiktok_cookies():
    """The TikTok cookies from the configured browser, read on first use and then held briefly in memory."""
    now=time.time()
    with _lock:
        if _kept['cookies'] is not None and now<_kept['until']: return _kept['cookies']
        if now<_kept['failed_until']:
            raise CookieError("Reading your browser's cookies failed a moment ago and is not being retried yet. Wait a few minutes, then retry.")
        try:
            cookies=_read()
        except CookieError:
            _kept['failed_until']=now+FAILURE_PAUSE
            raise
        _kept.update(cookies=cookies,until=now+LIFETIME,failed_until=0.0)
        return cookies


def forget():
    with _lock:
        _kept.update(cookies=None,until=0.0,failed_until=0.0)


def apply(ydl):
    """Give a yt-dlp instance the TikTok cookies. The instance sends them only to the hosts they belong to."""
    for cookie in tiktok_cookies(): ydl.cookiejar.set_cookie(cookie)
    return ydl
