import unittest
from unscroll.server import hook_of


def seg(label,text): return {'label':label,'text':text}


class Hook(unittest.TestCase):
    def test_spoken_first_line_wins_over_overlay(self):
        src={'segments':[seg('Speech 0.0–3.0s','It is not about weak products.'),seg('On screen ~0s','IT’S NOT ABOUT')]}
        self.assertEqual(hook_of(src),'It is not about weak products.')

    def test_music_lyrics_fall_back_to_on_screen_text(self):
        src={'segments':[seg('Speech 1.7–4.1s','Smoke doggy doggy, dog, get back to drink, its nothing'),
            seg('Speech 4.1–6.2s','Its like pissing like that and like pissing up'),
            seg('Speech 6.2–8.3s','Its like that and like pissing like that and up'),
            seg('On screen ~0s','Rr, oa Lou 3 VUIT, a It took me 15 months to make $1 million dollars, and I’m going p to show')]}
        self.assertEqual(hook_of(src),'It took me 15 months to make $1 million dollars, and I’m going')

    def test_music_with_no_on_screen_text_keeps_the_speech(self):
        src={'segments':[seg('Speech 0.0–3.0s','la la la la la la la la la la la la la la')]}
        self.assertEqual(hook_of(src),'la la la la la la la la la la la la la la')

    def test_no_speech_uses_on_screen_text(self):
        self.assertEqual(hook_of({'segments':[seg('On screen ~1s','How to build a personal brand')]}),'How to build a personal brand')

    def test_carousel_uses_first_slide(self):
        self.assertEqual(hook_of({'segments':[seg('Slide 1','Five habits that changed my money')]}),'Five habits that changed my money')

    def test_caption_is_never_used(self):
        self.assertEqual(hook_of({'caption':'my caption','segments':[]}),'')
        self.assertEqual(hook_of(None),'')

    def test_long_hook_is_shortened_on_a_word_boundary(self):
        out=hook_of({'segments':[seg('Speech 0.0–9.0s',' '.join(['word%d'%i for i in range(60)]))]})
        self.assertTrue(out.endswith('…') and len(out)<=141)


if __name__=='__main__': unittest.main()
