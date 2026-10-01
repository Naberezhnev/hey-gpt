import json
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import Mock, patch

from hey_gpt.codex_session import VoiceSession, session_id
from hey_gpt.codex_mcp import MCPServer, TOOLS
import codex_plugin
from hey_gpt.codex_audio import before_stop


class VoiceSessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.voice = VoiceSession(lambda: self.now)
        self.voice.enable("task-A")

    def waiting(self):
        return self.voice.wait("task-A", "ticket")

    def test_two_complete_cycles_stay_in_one_task_and_consume_once(self):
        self.voice.begin_turn("task-A")
        spoken = self.voice.finish("task-A", "turn-1", "## Голосовая сводка\nПодготовлен план.\n## Вопросы к тебе\n1. Кто аудитория?\nа) Пользователи\nб) Разработчики")
        self.assertIn("Кто аудитория?", spoken)
        self.assertIn("Разработчики", spoken)
        revision = self.waiting()
        self.assertTrue(self.voice.wake())
        self.assertTrue(self.voice.complete_dictation("Для разработчиков стоп джи пи ти", .9))
        result = self.voice.take("task-A", "ticket", revision)
        self.assertEqual(result["message"], "Для разработчиков")
        self.assertEqual(result["sequence"], 1)
        self.assertTrue(self.voice.take("task-A", "ticket", revision)["ended"])
        self.voice.finish("task-A", "turn-2", "## Голосовая сводка\nПлан уточнён для разработчиков.")
        self.assertEqual(self.voice.target, "task-A")
        revision = self.waiting()
        self.voice.wake()
        self.voice.complete_dictation("Добавь риски stop g p t")
        self.assertEqual(self.voice.take("task-A", "ticket", revision)["message"], "Добавь риски")

    def test_other_task_neither_reads_nor_receives_voice(self):
        self.assertIsNone(self.voice.finish("task-B", "turn", "Чужой ответ"))
        self.assertIsNone(self.voice.wait("task-B", "other"))
        self.assertFalse(self.voice.begin_turn("task-B"))
        self.assertEqual(self.voice.readout, "")
        self.assertEqual(self.voice.target, "task-A")

    def test_no_waiter_cannot_start_unsendable_recording(self):
        self.assertFalse(self.voice.wake())
        self.assertEqual(self.voice.state, "standby")
        self.assertFalse(self.voice.complete_dictation("Сделай задачу"))

    def test_pause_discards_dictation_but_allows_later_wake(self):
        revision = self.waiting()
        self.voice.wake()
        self.voice.pause()
        self.assertFalse(self.voice.complete_dictation("Не отправлять"))
        self.assertNotIn("message", self.voice.take("task-A", "ticket", revision))
        self.assertTrue(self.voice.wake())

    def test_new_typed_prompt_invalidates_pending_voice(self):
        revision = self.waiting()
        self.voice.wake()
        self.voice.complete_dictation("Старая реплика")
        self.voice.begin_turn("task-A")
        self.assertTrue(self.voice.take("task-A", "ticket", revision)["ended"])
        self.assertFalse(self.voice.wake())

    def test_switching_tasks_discards_readout_and_message(self):
        self.voice.finish("task-A", "turn", "Старый ответ")
        revision = self.waiting()
        self.voice.wake()
        self.voice.complete_dictation("Старый запрос")
        self.voice.enable("task-B")
        self.assertTrue(self.voice.take("task-A", "ticket", revision)["ended"])
        self.assertEqual(self.voice.readout, "")

    def test_disable_cancels_without_delivery_and_clears_memory(self):
        self.voice.finish("task-A", "turn", "Ответ")
        revision = self.waiting()
        self.voice.wake()
        self.voice.disable()
        self.assertFalse(self.voice.complete_dictation("Не отправлять"))
        self.assertTrue(self.voice.take("task-A", "ticket", revision)["ended"])
        self.assertEqual(self.voice.readout, "")

    def test_low_confidence_empty_long_and_stop_only_never_send(self):
        for text, confidence in (("Текст", .1), ("", 1), ("x" * 8001, 1), ("stop gpt", 1)):
            revision = self.waiting()
            self.voice.wake()
            self.assertFalse(self.voice.complete_dictation(text, confidence))
            self.assertNotIn("message", self.voice.take("task-A", "ticket", revision))
            self.voice.release("ticket")

    def test_recording_timeout_and_dead_hook_release_discard_audio(self):
        self.waiting()
        self.voice.wake()
        self.now = 121
        self.assertTrue(self.voice.recording_expired())
        self.assertFalse(self.voice.complete_dictation("Не отправлять"))
        self.voice.expire_waiters()
        self.assertFalse(self.voice.waiters)
        self.assertFalse(self.voice.wake())

    def test_duplicate_completion_does_not_repeat_speech(self):
        self.assertTrue(self.voice.finish("task-A", "turn", "Ответ"))
        self.assertIsNone(self.voice.finish("task-A", "turn", "Ответ"))

    def test_missing_answer_clears_old_success(self):
        self.voice.finish("task-A", "turn-1", "Готово")
        self.assertIsNone(self.voice.finish("task-A", "turn-2", ""))
        self.assertEqual(self.voice.readout, "")
        self.assertIn("недоступен", self.voice.error)

    def test_audio_failure_ends_wait_without_continuation(self):
        revision = self.waiting()
        self.voice.fail("Микрофон отключён")
        result = self.voice.take("task-A", "ticket", revision)
        self.assertTrue(result["ended"])
        self.assertIn("Микрофон", result["error"])
        self.assertNotIn("message", result)

    def test_summary_off_still_allows_dictation(self):
        self.voice.summary = False
        self.assertEqual(self.voice.finish("task-A", "turn", "Ответ"), "")
        self.waiting()
        self.assertTrue(self.voice.wake())

    def test_invalid_session_ids_rejected(self):
        for value in (None, "", "x y", "../other", "a" * 129, 123):
            with self.assertRaises(ValueError):
                session_id(value)

    def test_audio_cleaned_message_preserves_quoted_stop_at_end(self):
        revision = self.waiting()
        self.voice.wake()
        self.voice.complete_dictation("объясни команду стоп джи пи ти", stop_removed=True)
        self.assertEqual(self.voice.take("task-A", "ticket", revision)["message"], "объясни команду стоп джи пи ти")


class HookTests(unittest.TestCase):
    def test_stop_continues_only_actual_voice_message(self):
        event = {"session_id": "task-A", "hook_event_name": "Stop"}
        with patch("codex_plugin.rpc", return_value={"listen": True, "wait_seconds": 30}), patch("codex_plugin.wait_for_voice", return_value={"message": "Добавь проверку", "sequence": 1}):
            self.assertEqual(codex_plugin.hook(event), {"decision": "block", "reason": "Добавь проверку"})

    def test_silence_cancel_and_error_never_fabricate_prompt(self):
        event = {"session_id": "task-A", "hook_event_name": "Stop"}
        for result in ({"ended": True}, {"timeout": True}, {"ended": True, "error": "Микрофон"}):
            with patch("codex_plugin.rpc", return_value={"listen": True}), patch("codex_plugin.wait_for_voice", return_value=result):
                self.assertNotIn("decision", codex_plugin.hook(event))


class DictationBoundaryTests(unittest.TestCase):
    def test_stop_audio_is_excluded_even_when_its_text_is_wrong(self):
        words = [{"word": "добавь", "end": 1.0, "conf": .9}, {"word": "ограничения", "end": 1.7, "conf": .9},
                 {"word": "стоп", "end": 2.5, "conf": .9}, {"word": "джипи", "end": 3.0, "conf": .8},
                 {"word": "ты", "end": 3.5, "conf": .6}]
        text, scores = before_stop(words, 2.0)
        self.assertEqual(text, "добавь ограничения")
        self.assertEqual(scores, [.9, .9])

    def test_internal_quoted_stop_is_preserved_before_actual_boundary(self):
        words = [{"word": "объясни", "end": .5}, {"word": "стоп", "end": 1.0}, {"word": "сигнал", "end": 1.5},
                 {"word": "стоп", "end": 2.6}]
        self.assertEqual(before_stop(words, 2.2)[0], "объясни стоп сигнал")

    def test_missing_boundary_never_sends_uncleaned_text(self):
        with self.assertRaises(ValueError):
            before_stop([{"word": "стоп", "end": 2}], None)


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.output = []
        self.call = Mock(return_value={"enabled": False})
        self.server = MCPServer(self.output.append, call=self.call)

    def request(self, method, params=None, identity=1):
        self.server.dispatch({"id": identity, "method": method, "params": params or {}})

    def wait_result(self):
        deadline = time.monotonic() + 2
        while not self.output and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(self.output)
        return self.output[-1]["result"]

    def test_discovery_and_initialize_do_not_open_microphone(self):
        self.request("initialize", {"protocolVersion": "2025-03-26"})
        self.assertEqual(self.output[-1]["result"]["protocolVersion"], "2025-03-26")
        self.request("tools/list")
        self.assertEqual(len(self.output[-1]["result"]["tools"]), 7)
        self.call.assert_not_called()

    def test_status_cannot_enable(self):
        self.request("tools/call", {"name": "voice_status"})
        self.assertFalse(self.wait_result()["isError"])
        self.call.assert_called_once_with({"action": "status"})

    def test_unknown_arguments_and_missing_target_fail_closed(self):
        for args in ({}, {"session_id": "task-A", "shell": "bad"}):
            self.output.clear()
            self.request("tools/call", {"name": "voice_enable", "arguments": args})
            self.assertTrue(self.wait_result()["isError"])
        self.call.assert_not_called()

    def test_cancel_stops_wait_without_reply(self):
        started = threading.Event()
        done = threading.Event()
        def waiting(target, timeout, cancelled):
            started.set()
            while not cancelled():
                time.sleep(.01)
            done.set()
            return {"ended": True}
        self.server.wait = waiting
        self.request("tools/call", {"name": "voice_wait", "arguments": {"session_id": "task-A", "seconds": 10}}, identity=22)
        self.assertTrue(started.wait(1))
        self.server.dispatch({"method": "notifications/cancelled", "params": {"requestId": 22}})
        self.assertTrue(done.wait(1))
        time.sleep(.02)
        self.assertEqual(self.output, [])


class PackageTests(unittest.TestCase):
    def test_manifests_are_synchronized_and_all_hooks_point_to_runtime(self):
        root = Path(__file__).resolve().parents[1] / "plugins/hey-gpt-codex"
        portable = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        legacy = json.loads((root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        for field in ("name", "version"):
            self.assertEqual(portable[field], legacy[field])
        self.assertLessEqual(len(portable["extensions"]["com.openai"]["interface"]["shortDescription"]), 30)
        hooks = json.loads((root / "hooks/hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "Stop", "Interrupt", "SessionEnd"})
        for groups in hooks.values():
            for handler in groups[0]["hooks"]:
                self.assertIn("HeyGPTCodex.exe", handler["commandWindows"])
                self.assertNotIn("dangerously", handler["commandWindows"])
        self.assertEqual(hooks["Stop"][0]["hooks"][0]["timeout"], 3600)
        portable_mcp = json.loads((root / "mcp.json").read_text(encoding="utf-8"))
        # Native Codex rejects placeholders in portable executable paths.
        self.assertEqual(portable_mcp["mcpServers"]["hey-gpt"]["command"], "./runtime/HeyGPTCodex/HeyGPTCodex.exe")


if __name__ == "__main__":
    unittest.main()
