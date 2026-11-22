import os
import tempfile
import unittest
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from unittest.mock import MagicMock, patch
from unscroll import cookies, media

SECRET='sessionid-private-value'


def cookie(domain,name='c',value='v'):
    return Cookie(0,name,value,None,False,domain,True,domain.startswith('.'),'/',True,True,None,False,None,None,{})


def browser_jar(*domains):
    jar=CookieJar()
    for d in domains: jar.set_cookie(cookie(d,'sessionid',SECRET))
    return jar


class Base(unittest.TestCase):
    def setUp(self):
        cookies.forget()
        self.env=patch.dict(os.environ,{cookies.ENV:'chrome','UNSCROLL_TESTING':'0'});self.env.start()
    def tearDown(self):
        self.env.stop();cookies.forget()


class Switch(unittest.TestCase):
    def test_it_is_off_unless_the_person_turns_it_on(self):
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop(cookies.ENV,None)
            self.assertFalse(cookies.enabled())
        with patch.dict(os.environ,{cookies.ENV:'  '}): self.assertFalse(cookies.enabled())
        with patch.dict(os.environ,{cookies.ENV:'chrome'}): self.assertTrue(cookies.enabled())

    def test_an_unsupported_browser_is_refused_with_the_valid_names(self):
        with patch.dict(os.environ,{cookies.ENV:'netscape'}):
            with self.assertRaisesRegex(cookies.CookieError,'chrome'): cookies.setting()

    def test_a_profile_can_be_named(self):
        with patch.dict(os.environ,{cookies.ENV:'Chrome:Profile 2'}):
            self.assertEqual(cookies.setting(),('chrome','Profile 2'))


class Scope(unittest.TestCase):
    def test_only_tiktok_domains_pass(self):
        for good in ('tiktok.com','.tiktok.com','www.tiktok.com','.WWW.TikTok.com'): self.assertTrue(cookies.is_tiktok(good),good)
        for bad in ('nottiktok.com','tiktok.com.evil.com','evil-tiktok.com','google.com','','accounts.google.com'): self.assertFalse(cookies.is_tiktok(bad),bad)

    def test_the_rest_of_the_browsers_cookies_are_dropped(self):
        jar=browser_jar('.tiktok.com','.google.com','mybank.com','www.tiktok.com','github.com')
        self.assertEqual(sorted(c.domain for c in cookies.tiktok_only(jar)),['.tiktok.com','www.tiktok.com'])


class Reading(Base):
    def test_a_test_run_never_touches_a_real_browser(self):
        with patch.dict(os.environ,{'UNSCROLL_TESTING':'1'}), \
             patch('yt_dlp.cookies.extract_cookies_from_browser',side_effect=AssertionError('real browser read')) as read:
            with self.assertRaisesRegex(cookies.CookieError,'tests run'): cookies.tiktok_cookies()
        read.assert_not_called()

    def test_only_tiktok_cookies_are_kept(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com','.google.com')):
            kept=cookies.tiktok_cookies()
        self.assertEqual([c.domain for c in kept],['.tiktok.com'])

    def test_one_read_serves_many_posts(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com')) as read:
            cookies.tiktok_cookies();cookies.tiktok_cookies();cookies.tiktok_cookies()
        self.assertEqual(read.call_count,1)

    def test_cookies_are_not_kept_forever(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com')) as read:
            cookies.tiktok_cookies()
            with patch('unscroll.cookies.time.time',return_value=10**10): cookies.tiktok_cookies()
        self.assertEqual(read.call_count,2)

    def test_cookies_are_deleted_from_memory_when_their_time_is_up(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com')), \
             patch('unscroll.cookies.threading.Timer') as timer:
            cookies.tiktok_cookies()
        until,=timer.call_args.kwargs['args']
        self.assertTrue(timer.return_value.daemon)
        timer.return_value.start.assert_called_once()
        self.assertIsNotNone(cookies._kept['cookies'])
        cookies._expire(until)
        self.assertIsNone(cookies._kept['cookies'])

    def test_an_old_timer_does_not_delete_a_newer_read(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com')), \
             patch('unscroll.cookies.threading.Timer'):
            cookies.tiktok_cookies()
        cookies._expire(12345.0)   # a timer from an earlier read
        self.assertIsNotNone(cookies._kept['cookies'])

    def test_a_failed_read_is_not_asked_again_for_every_post(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',side_effect=PermissionError('/Users/x/Library/Cookies '+SECRET)) as read:
            for _ in range(3):
                with self.assertRaises(cookies.CookieError): cookies.tiktok_cookies()
        self.assertEqual(read.call_count,1)

    def test_errors_never_carry_what_the_browser_or_cookies_contained(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',side_effect=PermissionError('/Users/x/Library/Cookies '+SECRET)):
            with self.assertRaises(cookies.CookieError) as ctx: cookies.tiktok_cookies()
        self.assertNotIn(SECRET,str(ctx.exception))
        self.assertNotIn('/Users',str(ctx.exception))
        self.assertIsNone(ctx.exception.__cause__)
        self.assertTrue(ctx.exception.__suppress_context__)

    def test_a_browser_with_no_tiktok_login_says_so(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.google.com')):
            with self.assertRaisesRegex(cookies.CookieError,'Sign in to TikTok'): cookies.tiktok_cookies()

    def test_nothing_is_written_to_disk(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ,{'UNSCROLL_HOME':d}), \
             patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com')):
            before=set(Path(d).rglob('*'))
            cookies.tiktok_cookies()
            self.assertEqual(set(Path(d).rglob('*')),before)

    def test_apply_gives_the_downloader_only_tiktok_cookies(self):
        ydl=MagicMock();ydl.cookiejar=CookieJar()
        with patch('yt_dlp.cookies.extract_cookies_from_browser',return_value=browser_jar('.tiktok.com','.google.com')):
            cookies.apply(ydl)
        self.assertEqual([c.domain for c in ydl.cookiejar],['.tiktok.com'])


POST={'id':'1','kind':'video','url':'https://www.tiktok.com/@a/video/1','creator':'a','caption':'','posted_date':'','metadata':{}}
GOOD=(['f'],'cap',{})


class RetryAfterALoginWall(Base):
    def run_acquire(self,remote):
        with tempfile.TemporaryDirectory() as d, patch('unscroll.media.acquire_remote',side_effect=remote) as r:
            try: return media.acquire(POST,Path(d)),r
            except Exception as e: return e,r

    def test_cookies_are_not_read_when_nothing_hit_a_login_wall(self):
        with patch('unscroll.cookies.tiktok_cookies',side_effect=AssertionError('must not be read')):
            out,r=self.run_acquire([GOOD])
        self.assertEqual(out,GOOD);self.assertEqual(r.call_count,1)

    def test_a_login_wall_is_retried_once_with_the_cookies_on(self):
        seen=[]
        def remote(post,folder):
            seen.append(getattr(media._retry,'with_cookies',False))
            if len(seen)==1: raise media.FetchError('login')
            return GOOD
        out,r=self.run_acquire(remote)
        self.assertEqual(out,GOOD);self.assertEqual(seen,[False,True])
        self.assertFalse(media._retry.with_cookies)   # switched off again afterwards

    def test_the_switch_is_off_again_even_when_the_retry_fails(self):
        def remote(post,folder): raise media.FetchError('login')
        self.run_acquire(remote)
        self.assertFalse(media._retry.with_cookies)

    def test_still_refused_with_the_login_says_so(self):
        def remote(post,folder): raise media.FetchError('login')
        out,r=self.run_acquire(remote)
        self.assertEqual(out.code,'login_cookies');self.assertEqual(r.call_count,2)

    def test_without_the_setting_there_is_no_retry(self):
        os.environ.pop(cookies.ENV)
        def remote(post,folder): raise media.FetchError('login')
        out,r=self.run_acquire(remote)
        self.assertEqual(out.code,'login');self.assertEqual(r.call_count,1)

    def test_other_failures_are_not_retried_with_cookies(self):
        def remote(post,folder): raise media.FetchError('unavailable')
        out,r=self.run_acquire(remote)
        self.assertEqual(out.code,'unavailable');self.assertEqual(r.call_count,1)

    def test_a_cookie_read_failure_is_reported_as_such(self):
        with patch('yt_dlp.cookies.extract_cookies_from_browser',side_effect=PermissionError(SECRET)):
            with tempfile.TemporaryDirectory() as d, \
                 patch('unscroll.media.carousel_details',side_effect=AssertionError),\
                 patch('yt_dlp.YoutubeDL',return_value=MagicMock()) as y:
                y.return_value.__enter__.return_value.extract_info.side_effect=Exception('ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access.')
                with self.assertRaises(media.FetchError) as ctx: media.acquire(POST,Path(d))
        self.assertEqual(ctx.exception.code,'cookies')
        self.assertNotIn(SECRET,str(ctx.exception))

    def test_a_blocked_post_is_tried_again_once_cookies_are_enabled(self):
        blocked={'metadata':{'fetch_blocked':'login'}}
        os.environ.pop('UNSCROLL_COOKIES_FILE',None)
        media.guard_fetch(blocked)   # enabled: no longer skipped
        os.environ.pop(cookies.ENV)
        with self.assertRaises(media.FetchError): media.guard_fetch(blocked)


if __name__=='__main__': unittest.main()
