import sys
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(sys.platform == "win32", "Windows UI adapter")
class WindowsAdapterTests(unittest.TestCase):
    def test_page_tab_is_never_bound_as_browser_tab(self):
        from hey_gpt import windows
        adapter = windows.WindowsAdapter()
        page_tab = Mock(ControlTypeName="TabItemControl")
        page_tab.GetParentControl.return_value = Mock(ControlTypeName="DocumentControl")
        browser_tab = Mock(ControlTypeName="TabItemControl")
        browser_tab.GetParentControl.return_value = Mock(ControlTypeName="WindowControl")
        page_tab.GetSelectionItemPattern.return_value.IsSelected = True
        browser_tab.GetSelectionItemPattern.return_value.IsSelected = True
        browser_tab.GetRuntimeId.return_value = [4, 5]
        with patch.object(windows, "title", return_value="ChatGPT browser"), patch.object(adapter, "controls", return_value=[page_tab, browser_tab]):
            adapter.bind_window(123)
        self.assertIs(adapter.tab, browser_tab)
        self.assertEqual(adapter.tab_id, [4, 5])

    def test_preparing_selected_tab_does_not_select_again(self):
        from hey_gpt import windows
        adapter = windows.WindowsAdapter()
        adapter.hwnd = 123
        adapter.tab = Mock()
        adapter.tab_id = [4, 5]
        adapter.tab.GetRuntimeId.return_value = [4, 5]
        selection = adapter.tab.GetSelectionItemPattern.return_value
        selection.IsSelected = True
        native = Mock()
        native.IsWindow.return_value = True
        native.IsIconic.return_value = False
        native.GetForegroundWindow.return_value = 123
        with patch.object(windows, "user32", native), patch.object(adapter, "validate"):
            adapter.prepare_target()
        selection.Select.assert_not_called()

    def test_preparing_restores_bound_tab_without_opening_a_tab(self):
        from hey_gpt import windows
        adapter = windows.WindowsAdapter()
        adapter.hwnd = 123
        adapter.tab = Mock()
        adapter.tab_id = [4, 5]
        adapter.tab.GetRuntimeId.return_value = [4, 5]
        selection = adapter.tab.GetSelectionItemPattern.return_value
        selection.IsSelected = False
        native = Mock()
        native.IsWindow.return_value = True
        native.IsIconic.return_value = False
        native.GetForegroundWindow.return_value = 123
        with patch.object(windows, "user32", native), patch.object(adapter, "validate"), patch.object(windows.time, "sleep"):
            adapter.prepare_target()
        selection.Select.assert_called_once()
    def test_stable_id_survives_accessible_name_change(self):
        from hey_gpt.windows import Selector
        selected = Selector("ButtonControl", "Send", "send-button")
        control = Mock(ControlTypeName="ButtonControl", Name="Send message", AutomationId="send-button")
        self.assertTrue(selected.matches(control))
        control.AutomationId = "different"
        self.assertFalse(selected.matches(control))

    def test_failed_calibration_restores_previous_selector(self):
        from hey_gpt import windows
        adapter = windows.WindowsAdapter()
        adapter.hwnd = 123
        adapter.window_title = "ChatGPT test"
        previous = windows.Selector("ButtonControl", "Old send", "old")
        adapter.selectors["send"] = previous
        control = Mock(ControlTypeName="ButtonControl", Name="New send", AutomationId="new")
        native = Mock()
        native.GetCursorPos.return_value = True
        native.GetAncestor.return_value = 123
        with patch.object(windows, "user32", native), patch.object(windows, "title", return_value="ChatGPT test"), \
                patch.object(windows.auto, "ControlFromPoint", return_value=control), \
                patch.object(adapter, "find", side_effect=RuntimeError("ambiguous")):
            with self.assertRaises(RuntimeError):
                adapter.capture_at_cursor("send")
        self.assertIs(adapter.selectors["send"], previous)

    def test_rebinding_another_window_clears_old_controls(self):
        from hey_gpt import windows
        adapter = windows.WindowsAdapter()
        adapter.hwnd = 123
        adapter.selectors["send"] = windows.Selector("ButtonControl", "Send", "send")
        native = Mock()
        native.GetCursorPos.return_value = True
        native.GetAncestor.return_value = 456
        with patch.object(windows, "user32", native), patch.object(windows, "title", return_value="Codex test"), patch.object(adapter, "controls", return_value=[]):
            adapter.capture_at_cursor("window")
        self.assertEqual(adapter.hwnd, 456)
        self.assertEqual(adapter.selectors, {})


@unittest.skipUnless(sys.platform == "win32", "Windows setup window")
class ApplicationTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from hey_gpt.app import Application
        self.root = tk.Tk()
        self.root.withdraw()
        with patch.object(Application, "refresh_devices"), patch("hey_gpt.app.Notifications"):
            self.app = Application(self.root)
        self.app.emergency_pressed = lambda: False
        self.child = Mock()
        self.child.poll.return_value = None

    def tearDown(self):
        self.app.close()

    def test_test_mode_never_operates_the_chat(self):
        self.app.process = self.child
        self.app.mode = "test"
        self.app.controller = Mock()
        self.app.events.put((self.child, {"event": "ready"}))
        self.app.events.put((self.child, {"event": "command", "command": "WAKE"}))
        self.app.events.put((self.child, {"event": "command", "command": "STOP"}))
        self.app.pump()
        self.app.controller.command.assert_not_called()
        self.app.controller.tick.assert_not_called()
        self.assertIn("Stop GPT", self.app.command_status.get())

    def test_old_worker_events_are_ignored_after_pause(self):
        self.app.process = self.child
        self.app.mode = "workflow"
        self.app.pause()
        self.app.controller = Mock()
        self.app.events.put((self.child, {"event": "ready"}))
        self.app.events.put((self.child, {"event": "command", "command": "WAKE"}))
        self.app.pump()
        self.assertFalse(self.app.ready)
        self.app.controller.command.assert_not_called()
        self.child.terminate.assert_called_once()

    def test_audio_error_stops_worker_and_remains_visible(self):
        self.app.process = self.child
        self.app.mode = "workflow"
        self.app.ready = True
        self.app.events.put((self.child, {"event": "error", "message": "Microphone disconnected"}))
        self.app.pump()
        self.assertIsNone(self.app.process)
        self.assertFalse(self.app.ready)
        self.assertIn("Microphone disconnected", self.app.status.get())

    def test_recording_ready_uses_tone_even_in_voice_mode(self):
        from hey_gpt.core import State
        self.app.controller.state = State.RECORDING
        self.app.show_state()
        self.app.notifications.tone.assert_called_once_with("ready")
        self.app.notifications.say.assert_not_called()

    def test_voice_pause_keeps_worker_for_wake_command(self):
        from hey_gpt.core import State
        self.app.process = self.child
        self.app.mode = "workflow"
        self.app.ready = True
        self.app.events.put((self.child, {"event": "command", "command": "PAUSE"}))
        self.app.pump()
        self.assertEqual(self.app.controller.state, State.PAUSED)
        self.assertIs(self.app.process, self.child)
        self.child.terminate.assert_not_called()
