import unittest
from unittest.mock import patch
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


if __name__=='__main__': unittest.main()
