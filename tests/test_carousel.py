import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from unscroll import media

POST={'id':'123','url':'https://www.tiktok.com/@a/photo/123','creator':'a','caption':'cap','metadata':{}}


class Carousel(unittest.TestCase):
    def test_slides_come_from_the_solved_challenge_page_first(self):
        with patch('unscroll.media._slides_via_ytdlp',return_value=(['https://p16.tiktokcdn.com/1','https://p16.tiktokcdn.com/2'],'desc')),\
             patch('httpx.get',side_effect=AssertionError('plain request should not be needed')):
            slides,caption,complete=media.carousel_details(POST)
        self.assertEqual(len(slides),2)
        self.assertEqual(caption,'desc')
        self.assertTrue(complete)

    def test_ytdlp_failure_returns_none_so_the_old_path_still_runs(self):
        with patch('yt_dlp.YoutubeDL',side_effect=RuntimeError('boom')):
            self.assertIsNone(media._slides_via_ytdlp(POST))



SAVED_AS_VIDEO={'id':'123','kind':'video','url':'https://www.tiktok.com/@/video/123',
                'creator':'','caption':'cap','posted_date':'','metadata':{}}


def probe(formats):
    """A yt-dlp stand-in whose extract_info reports the given formats and downloads nothing."""
    def make(*a,**k):
        ctx=MagicMock()
        ctx.__enter__.return_value.extract_info.return_value={'formats':formats,'description':'desc'}
        return ctx
    return make


class PhotoPostSavedAsVideo(unittest.TestCase):
    """TikTok serves a slideshow as its music track alone, so a post saved as a video has no video stream."""

    def test_a_music_only_post_is_taken_as_a_slideshow(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('yt_dlp.YoutubeDL',side_effect=probe([{'vcodec':'none','acodec':'mp4a'}])), \
             patch('unscroll.media._slides_via_ytdlp',return_value=(['https://p16.tiktokcdn.com/1'],'slides desc')), \
             patch('unscroll.media.fetch_image',side_effect=lambda u,p:p.write_bytes(b'img')), \
             patch('unscroll.media.time.sleep'):
            files,caption,details=media.acquire(SAVED_AS_VIDEO,Path(d))
        self.assertEqual(details['kind'],'carousel')
        self.assertEqual(len(files),1)
        self.assertEqual(caption,'slides desc')

    def test_a_real_video_is_still_downloaded_as_one(self):
        with tempfile.TemporaryDirectory() as d:
            def make(*a,**k):
                ctx=MagicMock()
                def grab(url,download=False):
                    if download: (Path(d)/'123.mp4').write_bytes(b'v')
                    return {'formats':[{'vcodec':'h264','height':720}],'description':'desc'}
                ctx.__enter__.return_value.extract_info.side_effect=grab
                return ctx
            with patch('yt_dlp.YoutubeDL',side_effect=make), \
                 patch('unscroll.media._slides_via_ytdlp',side_effect=AssertionError('slides should not be needed')):
                files,caption,details=media.acquire(SAVED_AS_VIDEO,Path(d))
        self.assertEqual(details['kind'],'video')
        self.assertEqual([f.suffix for f in files],['.mp4'])

    def test_a_music_only_post_with_no_readable_slides_keeps_its_audio(self):
        with tempfile.TemporaryDirectory() as d:
            def make(*a,**k):
                ctx=MagicMock()
                def grab(url,download=False):
                    if download: (Path(d)/'123.m4a').write_bytes(b'a')
                    return {'formats':[{'vcodec':'none','acodec':'mp4a'}],'description':'desc'}
                ctx.__enter__.return_value.extract_info.side_effect=grab
                return ctx
            with patch('yt_dlp.YoutubeDL',side_effect=make), \
                 patch('unscroll.media._slides_via_ytdlp',return_value=None):
                files,caption,details=media.acquire(SAVED_AS_VIDEO,Path(d))
        self.assertEqual([f.suffix for f in files],['.m4a'])
        self.assertEqual(details['kind'],'video')



class LoginWalledPhotoPost(unittest.TestCase):
    def test_a_login_wall_is_reported_as_one_rather_than_as_missing_slides(self):
        wall=RuntimeError('ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access.')
        with patch('yt_dlp.YoutubeDL',side_effect=wall), \
             patch('httpx.get',side_effect=AssertionError('the plain page should not be tried')):
            with self.assertRaises(media.FetchError) as ctx: media.carousel_details(POST)
        self.assertEqual(ctx.exception.code,'login')



class CarouselThatIsReallyAVideo(unittest.TestCase):
    """A post saved as a photo post but served as a video should still be read, not reported as missing slides."""

    def test_it_falls_back_to_the_video_path(self):
        with tempfile.TemporaryDirectory() as d:
            def make(*a,**k):
                ctx=MagicMock()
                def grab(url,download=False):
                    if download: (Path(d)/'123.mp4').write_bytes(b'v')
                    return {'formats':[{'vcodec':'h264','height':720}],'description':'desc'}
                ctx.__enter__.return_value.extract_info.side_effect=grab
                return ctx
            with patch('unscroll.media.carousel_details',side_effect=ValueError('All carousel slides could not be verified.')), \
                 patch('yt_dlp.YoutubeDL',side_effect=make):
                files,caption,details=media.acquire({**POST,'kind':'carousel','posted_date':''},Path(d))
        self.assertEqual(details['kind'],'video')
        self.assertEqual([f.suffix for f in files],['.mp4'])

    def test_a_post_that_is_neither_keeps_the_original_slide_error(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('unscroll.media.carousel_details',side_effect=ValueError('All carousel slides could not be verified.')), \
             patch('unscroll.media.fetch_video',side_effect=ValueError('No complete video was downloaded.')):
            with self.assertRaisesRegex(ValueError,'All carousel slides'):
                media.acquire({**POST,'kind':'carousel'},Path(d))

    def test_a_login_wall_on_the_video_fallback_is_reported_as_one(self):
        with tempfile.TemporaryDirectory() as d, \
             patch('unscroll.media.carousel_details',side_effect=ValueError('All carousel slides could not be verified.')), \
             patch('unscroll.media.fetch_video',side_effect=media.FetchError('login')):
            with self.assertRaises(media.FetchError) as ctx:
                media.acquire({**POST,'kind':'carousel'},Path(d))
        self.assertEqual(ctx.exception.code,'login')



class PhotoUrlNormalised(unittest.TestCase):
    def test_a_photo_url_is_asked_for_as_a_video_url(self):
        self.assertEqual(media.video_url({'url':'https://www.tiktok.com/@a/photo/123'}),
                         'https://www.tiktok.com/@a/video/123')
        self.assertEqual(media.video_url({'url':'https://www.tiktok.com/@a/video/123'}),
                         'https://www.tiktok.com/@a/video/123')


if __name__=='__main__': unittest.main()
