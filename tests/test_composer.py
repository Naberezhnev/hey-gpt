import unittest
from hey_gpt.composer import composer_text

class ComposerTests(unittest.TestCase):
    def test_browser_hint_is_empty_only_when_send_is_absent(self):
        self.assertEqual(composer_text("Спросить ChatGPT\n", "Спросить ChatGPT", False), "")
        self.assertEqual(composer_text("Спросить ChatGPT\n", "Спросить ChatGPT", True), "Спросить ChatGPT\n")

    def test_arbitrary_draft_preserves_whitespace_and_unicode(self):
        for text in ("Привет 😀 {Enter}\n", "Спросить ChatGPT подробнее", "Ask anything"):
            self.assertEqual(composer_text(text, "Спросить ChatGPT", False), text)
