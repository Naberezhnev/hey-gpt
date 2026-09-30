import unittest
from hey_gpt.speech import command_from_result


def result(text, confidence=1):
    return {"text": text, "result": [{"word": word, "conf": confidence} for word in text.split()]}


class SpeechCommandTests(unittest.TestCase):
    def test_exact_wake_and_stop(self):
        self.assertEqual(command_from_result(result("hi chat g p t")), "WAKE")
        self.assertEqual(command_from_result(result("stop g p t")), "STOP")

    def test_dictated_words_before_stop(self):
        self.assertEqual(command_from_result(result("[unk] [unk] stop g p t")), "STOP")

    def test_unknown_prefix_cannot_wake(self):
        self.assertIsNone(command_from_result(result("[unk] hi chat g p t")))

    def test_unrelated_or_incomplete_speech(self):
        for text in ("[unk]", "hi chat", "stop", "hello there", "please stop g p t", "stop g p t training"):
            self.assertIsNone(command_from_result(result(text)), text)

    def test_low_confidence_and_missing_words(self):
        self.assertIsNone(command_from_result(result("stop g p t", 0.6)))
        self.assertIsNone(command_from_result({"text": "hi chat g p t"}))
        payload = result("hi chat g p t")
        payload["result"][-1]["conf"] = 0.1
        self.assertIsNone(command_from_result(payload))

    def test_mismatched_tokens_cannot_trigger(self):
        payload = result("stop g p t")
        payload["result"][-1]["word"] = "tea"
        self.assertIsNone(command_from_result(payload))
