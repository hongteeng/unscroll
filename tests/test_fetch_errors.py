import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from unscroll import media

LOGIN='ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access.'


class FetchErrors(unittest.TestCase):
    def test_login_wall_is_recognised(self):
        self.assertEqual(media.classify_fetch_error(LOGIN),'login')
    def test_other_causes(self):
        self.assertEqual(media.classify_fetch_error('Video unavailable. This video has been removed'),'unavailable')
        self.assertEqual(media.classify_fetch_error('HTTP Error 429: Too Many Requests'),'rate_limited')
        self.assertEqual(media.classify_fetch_error('something odd'),'other')
    def test_acquire_reports_the_real_cause(self):
        post={'kind':'video','url':'https://www.tiktok.com/@a/video/1','caption':'','creator':'','posted_date':'','metadata':{}}
        ydl=MagicMock(); ydl.return_value.__enter__.return_value.extract_info.side_effect=Exception(LOGIN)
        with tempfile.TemporaryDirectory() as d, patch('yt_dlp.YoutubeDL',ydl):
            with self.assertRaises(media.FetchError) as ctx: media.acquire(post,Path(d))
        self.assertEqual(ctx.exception.code,'login')
        self.assertIn('logged-in',str(ctx.exception))
    def test_guard_skips_a_request_that_cannot_succeed(self):
        blocked={'metadata':{'fetch_blocked':'login'}}
        with patch.dict(os.environ,{},clear=False):
            os.environ.pop('UNSCROLL_COOKIES_FILE',None)
            with self.assertRaises(media.FetchError): media.guard_fetch(blocked)
            media.guard_fetch({'metadata':{'fetch_blocked':'login','local_files':['/x.mp4']}})  # attached copy: allowed
            media.guard_fetch({'metadata':{}})  # never failed: allowed
        with patch.dict(os.environ,{'UNSCROLL_COOKIES_FILE':'/c.txt'}):
            media.guard_fetch(blocked)  # cookies configured: try again


if __name__=='__main__': unittest.main()
