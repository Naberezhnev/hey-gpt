import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "win32", "Windows speech")
class NotificationTests(unittest.TestCase):
    def test_cancel_purges_voice_and_does_not_play_queued_text(self):
        from hey_gpt.notifications import Notifications
        started = threading.Event()
        voice = Mock()
        token = Mock(Id="ru")
        token.GetDescription.return_value = "Russian voice"
        token.GetAttribute.return_value = "419"
        voice.GetVoices.return_value = [token]
        voice.Voice = token
        voice.Speak.side_effect = lambda text, flags: started.set() if text else None
        voice.WaitUntilDone.side_effect = lambda timeout: (time.sleep(.025) or False)
        activity = Mock()
        with patch("comtypes.client.CreateObject", return_value=voice):
            notifications = Notifications(activity)
            try:
                notifications.speak("<voice>Обычный текст, не XML</voice>")
                self.assertTrue(started.wait(2))
                notifications.say("Этот текст должен быть отменён")
                self.assertTrue(notifications.stop())
                self.assertFalse(notifications.speaking)
                self.assertEqual(voice.Speak.call_args_list[0].args[1], 17)
                voice.Speak.assert_any_call("", 18)
                self.assertFalse(any("должен быть отменён" in call.args[0] for call in voice.Speak.call_args_list))
                activity.assert_any_call(True)
                activity.assert_any_call(False)
            finally:
                notifications.close()

    def test_explicit_readout_uses_speech_with_status_tones_disabled(self):
        from hey_gpt.notifications import Notifications
        done = threading.Event()
        voice = Mock()
        token = Mock(Id="default")
        token.GetDescription.return_value = "Voice"
        token.GetAttribute.return_value = "409"
        voice.GetVoices.return_value = [token]
        voice.Voice = token
        voice.WaitUntilDone.return_value = True
        with patch("comtypes.client.CreateObject", return_value=voice):
            notifications = Notifications(lambda active: done.set() if not active else None)
            try:
                notifications.enabled = False
                notifications.mode = "tones"
                notifications.speak("Вопрос: какой язык выбрать?")
                self.assertTrue(done.wait(2))
                voice.Speak.assert_called_once_with("Вопрос: какой язык выбрать?", 17)
            finally:
                notifications.close()
