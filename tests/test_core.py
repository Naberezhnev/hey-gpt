import unittest
from hey_gpt.core import Controller, State, strip_stop_command


class Clock:
    now = 0.0
    def __call__(self):
        return self.now
    def advance(self, seconds):
        self.now += seconds


class FakeDesktop:
    def __init__(self):
        self.text = ""
        self.recording = False
        self.enabled = True
        self.focused = True
        self.clicks = []
        self.writable = True

    def check(self):
        if not self.focused:
            raise RuntimeError("wrong window")
    def read_text(self):
        self.check()
        return self.text
    def click(self, role):
        self.check()
        self.clicks.append(role)
    def recording_visible(self):
        self.check()
        return self.recording
    def send_enabled(self):
        self.check()
        return self.enabled
    def replace_text(self, expected, replacement):
        self.check()
        if not self.writable:
            raise RuntimeError("read-only editor")
        if self.text != expected:
            raise RuntimeError("changed text")
        self.text = replacement


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.desktop = FakeDesktop()
        self.clock = Clock()
        self.controller = Controller(self.desktop, auto_send=True, clock=self.clock)

    def recording(self):
        self.controller.command("WAKE")
        self.desktop.recording = True
        self.controller.tick()
        self.assertEqual(self.controller.state, State.RECORDING)

    def transcribing(self):
        self.recording()
        self.controller.command("STOP")
        self.desktop.recording = False

    def settle(self):
        self.controller.tick()
        self.clock.advance(2)
        self.controller.tick()

    def test_full_cycle_removes_stop_then_sends_once(self):
        self.transcribing()
        self.desktop.text = "Add a red background. Stop GPT."
        self.settle()
        self.assertEqual(self.desktop.text, "Add a red background.")
        self.assertEqual(self.desktop.clicks, ["microphone", "finish", "send"])
        self.assertEqual(self.controller.state, State.IDLE)
        self.controller.tick()
        self.assertEqual(self.desktop.clicks.count("send"), 1)

    def test_waits_for_actual_recording(self):
        self.controller.command("WAKE")
        self.assertEqual(self.controller.state, State.STARTING)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.STARTING)
        self.clock.advance(11)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.ERROR)

    def test_ignores_duplicate_wake_and_stop(self):
        self.recording()
        self.controller.command("WAKE")
        self.controller.command("STOP")
        self.controller.command("STOP")
        self.assertEqual(self.desktop.clicks, ["microphone", "finish"])

    def test_stop_without_recording_does_nothing(self):
        self.controller.command("STOP")
        self.assertEqual(self.desktop.clicks, [])

    def test_existing_draft_is_never_overwritten(self):
        self.desktop.text = "Keep this draft"
        self.controller.command("WAKE")
        self.assertEqual(self.desktop.clicks, [])
        self.assertEqual(self.controller.state, State.ERROR)

    def test_focus_change_before_stop_prevents_click(self):
        self.recording()
        self.desktop.focused = False
        self.controller.command("STOP")
        self.assertEqual(self.desktop.clicks, ["microphone"])
        self.assertEqual(self.controller.state, State.ERROR)

    def test_focus_change_before_send_prevents_click(self):
        self.transcribing()
        self.desktop.text = "Hello"
        self.controller.tick()
        self.desktop.focused = False
        self.clock.advance(2)
        self.controller.tick()
        self.assertNotIn("send", self.desktop.clicks)

    def test_transcription_is_not_sent_while_recording_visible(self):
        self.transcribing()
        self.desktop.recording = True
        self.desktop.text = "Partial message"
        self.settle()
        self.assertNotIn("send", self.desktop.clicks)

    def test_disabled_send_does_not_send(self):
        self.transcribing()
        self.desktop.enabled = False
        self.desktop.text = "Hello"
        self.settle()
        self.assertNotIn("send", self.desktop.clicks)

    def test_changing_transcript_restarts_settle_timer(self):
        self.transcribing()
        self.desktop.text = "First part"
        self.controller.tick()
        self.clock.advance(1)
        self.desktop.text = "First part, second part"
        self.controller.tick()
        self.clock.advance(1)
        self.controller.tick()
        self.assertNotIn("send", self.desktop.clicks)
        self.clock.advance(1)
        self.controller.tick()
        self.assertIn("send", self.desktop.clicks)

    def test_transcription_timeout(self):
        self.transcribing()
        self.clock.advance(46)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.ERROR)
        self.assertNotIn("send", self.desktop.clicks)

    def test_read_only_editor_leaves_message_for_manual_review(self):
        self.transcribing()
        self.desktop.text = "Hello Stop GPT"
        self.desktop.writable = False
        self.settle()
        self.assertEqual(self.desktop.text, "Hello Stop GPT")
        self.assertNotIn("send", self.desktop.clicks)

    def test_empty_message_after_cleanup_is_not_sent(self):
        self.transcribing()
        self.desktop.text = "Stop GPT"
        self.settle()
        self.assertEqual(self.controller.state, State.ERROR)
        self.assertNotIn("send", self.desktop.clicks)

    def test_review_mode_does_not_send(self):
        self.controller.auto_send = False
        self.transcribing()
        self.desktop.text = "Hello"
        self.settle()
        self.assertEqual(self.controller.state, State.REVIEW)
        self.assertNotIn("send", self.desktop.clicks)

    def test_reset_after_error(self):
        self.desktop.text = "Draft"
        self.controller.command("WAKE")
        self.controller.reset()
        self.assertEqual(self.controller.state, State.IDLE)
        self.assertEqual(self.desktop.text, "Draft")


class CleanupTests(unittest.TestCase):
    def test_fixed_stop_spellings(self):
        for suffix in ("Stop GPT.", "stop G P T!", "STOP G.P.T.", "стоп GPT", "стоп джи пи ти."):
            with self.subTest(suffix=suffix):
                self.assertEqual(strip_stop_command("Hello " + suffix), "Hello")

    def test_internal_phrase_is_preserved(self):
        text = 'Explain how "Stop GPT" works in this program.'
        self.assertEqual(strip_stop_command(text), text)

    def test_similar_words_are_preserved(self):
        self.assertEqual(strip_stop_command("Please stop GPT training"), "Please stop GPT training")
        self.assertEqual(strip_stop_command("nonstop GPT"), "nonstop GPT")


if __name__ == "__main__":
    unittest.main()
