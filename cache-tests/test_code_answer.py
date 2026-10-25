"""OCR scoring accepts presentation markup without accepting wrong answers."""
import unittest
from run_suite import normalize_code_answer

class CodeAnswerTests(unittest.TestCase):
    def test_plain_and_fenced_codes(self):
        for text in ('N1X-742', ' N1X-742. ', '```N1X-742```', '```\nN1X-742\n```'):
            self.assertEqual(normalize_code_answer(text), 'N1X-742')

    def test_wrong_or_extra_content_is_not_accepted(self):
        for text in ('N1X-743', '```N1X-743```', 'The code is N1X-742',
                     '```N1X-742``` extra', '```N1X-742'):
            self.assertNotEqual(normalize_code_answer(text), 'N1X-742')

if __name__ == '__main__':
    unittest.main()
