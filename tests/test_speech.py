import unittest
from unittest.mock import Mock
from hey_gpt.speech import CommandDecoder, command_from_result
import json


def result(text, confidence=1):
    return {"text": text, "result": [{"word": word, "conf": confidence} for word in text.split()]}


class SpeechCommandTests(unittest.TestCase):
    def test_exact_wake_and_stop(self):
        self.assertEqual(command_from_result(result("hi chat g p t")), "WAKE")
        self.assertEqual(command_from_result(result("stop g p t")), "STOP")
        self.assertEqual(command_from_result(result("hi g p t")), "WAKE")
        self.assertEqual(command_from_result(result("привет джи пи ти")), "WAKE")
        self.assertEqual(command_from_result(result("стоп джи пи ти")), "STOP")
        self.assertEqual(command_from_result(result("pause g p t")), "PAUSE")
        self.assertEqual(command_from_result(result("пауза джи пи ти")), "PAUSE")

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

    def test_fast_decoder_does_not_finalize_while_audio_continues(self):
        rec = Mock()
        rec.AcceptWaveform.return_value = False
        decoder = CommandDecoder(rec, 16000)
        decoder.accept(b"\xff\x7f" * 16000)
        rec.FinalResult.assert_not_called()
        rec.PartialResult.assert_not_called()

    def test_fast_decoder_rechecks_final_confidence(self):
        rec = Mock()
        rec.AcceptWaveform.return_value = False
        payload = result("hi g p t")
        payload["result"][-1]["end"] = .1
        rec.PartialResult.return_value = json.dumps({"partial": payload["text"], "partial_result": payload["result"]})
        rec.FinalResult.return_value = json.dumps(result("hi g p t", .4))
        decoder = CommandDecoder(rec, 16000)
        self.assertIsNone(decoder.accept(b"\0" * 32000))
        rec.FinalResult.assert_called_once()
        rec.Reset.assert_called_once()
