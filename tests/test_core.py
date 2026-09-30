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
        self.busy = False
        self.responses = 0
        self.sent_text = None
        self.accept_send = True

    def prepare_target(self):
        self.check()

    def response_status(self):
        self.check()
        return self.busy, self.responses

    def check(self):
        if not self.focused:
            raise RuntimeError("wrong window")
    def read_text(self):
        self.check()
        return self.text
    def click(self, role):
        self.check()
        self.clicks.append(role)
        if role == "send" and self.accept_send:
            self.sent_text, self.text = self.text, ""
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
        self.assertEqual(self.desktop.sent_text, "Add a red background.")
        self.assertEqual(self.desktop.clicks, ["microphone", "finish", "send"])
        self.assertEqual(self.controller.state, State.SENDING)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.WAITING)
        self.assertEqual(self.desktop.clicks.count("send"), 1)

    def test_response_ready_requires_new_evidence_and_settles(self):
        self.transcribing()
        self.desktop.responses = 5
        self.desktop.text = "Hello"
        self.settle()
        self.controller.tick()
        self.clock.advance(3)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.WAITING)
        self.assertEqual(self.controller.completed, 0)
        self.desktop.busy = True
        self.controller.tick()
        self.desktop.busy = False
        self.controller.tick()
        self.clock.advance(2)
        self.controller.tick()
        self.assertEqual(self.controller.completed, 1)
        self.assertEqual(self.controller.state, State.IDLE)

    def test_fast_response_without_seen_busy_is_detected(self):
        self.transcribing()
        self.desktop.text = "Hello"
        self.settle()
        self.desktop.responses = 1
        self.controller.tick()
        self.controller.tick()
        self.clock.advance(2)
        self.controller.tick()
        self.assertEqual(self.controller.completed, 1)

    def test_send_failure_never_retries_or_announces_completion(self):
        self.transcribing()
        self.desktop.accept_send = False
        self.desktop.text = "Keep me"
        self.settle()
        self.clock.advance(11)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.ERROR)
        self.assertEqual(self.desktop.text, "Keep me")
        self.assertEqual(self.desktop.clicks.count("send"), 1)
        self.assertEqual(self.controller.completed, 0)

    def test_wake_recovers_after_transient_error(self):
        self.desktop.focused = False
        self.controller.command("WAKE")
        self.assertEqual(self.controller.state, State.ERROR)
        self.desktop.focused = True
        self.controller.command("WAKE")
        self.assertEqual(self.controller.state, State.STARTING)
        self.assertEqual(self.desktop.clicks, ["microphone"])

    def test_stop_recovers_an_existing_recording_after_error(self):
        self.controller.fail(RuntimeError("temporary"))
        self.desktop.recording = True
        self.controller.command("STOP")
        self.assertEqual(self.controller.state, State.TRANSCRIBING)
        self.assertEqual(self.desktop.clicks, ["finish"])

    def test_pause_during_transcription_never_sends(self):
        self.transcribing()
        self.desktop.text = "Keep this draft Stop GPT"
        self.controller.command("PAUSE")
        self.settle()
        self.assertEqual(self.controller.state, State.PAUSED)
        self.assertEqual(self.desktop.text, "Keep this draft Stop GPT")
        self.assertNotIn("send", self.desktop.clicks)

    def test_pause_finishes_recording_but_keeps_draft_for_review(self):
        self.recording()
        self.controller.command("PAUSE")
        self.assertEqual(self.desktop.clicks, ["microphone", "finish"])
        self.desktop.recording = False
        self.desktop.text = "Keep my words"
        self.settle()
        self.assertEqual(self.controller.state, State.PAUSED)
        self.assertNotIn("send", self.desktop.clicks)

    def test_stop_during_delayed_start_cancels_late_recording(self):
        self.controller.command("WAKE")
        self.controller.command("STOP")
        self.assertEqual(self.controller.state, State.PAUSING)
        self.clock.advance(1)
        self.desktop.recording = True
        self.controller.tick()
        self.controller.command("PAUSE")
        self.controller.tick()
        self.assertEqual(self.desktop.clicks, ["microphone", "finish"])
        self.desktop.recording = False
        self.desktop.text = "Late draft"
        self.settle()
        self.assertEqual(self.controller.state, State.PAUSED)
        self.assertNotIn("send", self.desktop.clicks)

    def test_cancelled_start_that_never_appears_stays_paused(self):
        self.controller.command("WAKE")
        self.controller.command("PAUSE")
        self.clock.advance(11)
        self.controller.tick()
        self.assertEqual(self.controller.state, State.PAUSED)
        self.assertEqual(self.desktop.clicks, ["microphone"])

    def test_wake_resumes_paused_actions_only_with_empty_field(self):
        self.controller.command("PAUSE")
        self.controller.command("WAKE")
        self.assertEqual(self.controller.state, State.STARTING)
        self.assertEqual(self.desktop.clicks, ["microphone"])

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
