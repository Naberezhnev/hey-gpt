"""Windows named-pipe service shared by MCP and lifecycle hooks.

No network listener, no transcript files, no shell execution of spoken text.
"""
import hashlib
import ctypes
import json
from multiprocessing.connection import Client, Listener
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

from .codex_session import VoiceSession, session_id

MAX_MESSAGE = 256 * 1024


def data_dir():
    return Path(os.environ.get("HEY_GPT_CODEX_DATA", str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "HeyGPT" / "codex")))


def pipe_address():
    digest = hashlib.sha256(str(data_dir().resolve()).encode()).hexdigest()[:24]
    return rf"\\.\pipe\HeyGPT-Codex-{digest}"


def auth_key():
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "ipc.key"
    try:
        with path.open("xb") as output:
            output.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    key = path.read_bytes()
    for _ in range(20):
        if key:
            break
        time.sleep(.05)
        key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("Повреждён локальный ключ Hey GPT. Не удалось подключиться.")
    return key


def executable_command(mode):
    if getattr(sys, "frozen", False):
        return [sys.executable, mode]
    return [sys.executable, str(Path(__file__).resolve().parent.parent / "codex_plugin.py"), mode]


def rpc(request, *, start=True, timeout=5):
    if sys.platform != "win32":
        raise RuntimeError("Hey GPT Codex работает только на локальном Windows-компьютере.")
    key = auth_key()
    deadline = time.monotonic() + timeout
    launched = False
    while True:
        try:
            with Client(pipe_address(), family="AF_PIPE", authkey=key) as connection:
                connection.send_bytes(json.dumps(request, ensure_ascii=False).encode("utf-8"))
                if not connection.poll(timeout):
                    raise TimeoutError("Служба Hey GPT не ответила.")
                result = json.loads(connection.recv_bytes(MAX_MESSAGE))
                if "error" in result and result.get("ok") is False:
                    raise RuntimeError(result["error"])
                return result
        except (FileNotFoundError, ConnectionRefusedError):
            if not start or time.monotonic() >= deadline:
                raise RuntimeError("Фоновая служба Hey GPT недоступна.")
            if not launched:
                subprocess.Popen(executable_command("service"), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
                launched = True
            time.sleep(.1)


class Service:
    def __init__(self):
        from .notifications import Notifications
        self.session = VoiceSession()
        self.audio = None
        self.closed = threading.Event()
        self.operations = threading.RLock()
        self.emergency = threading.Event()
        self.host_pid = None
        self.last_request = time.monotonic()
        self.notifier = Notifications(lambda active: self.audio.mute(active) if self.audio else None)
        self.config = {"enabled": False, "autostart": True, "summary": True,
                       "language": "ru", "voice_id": "", "session_id": None,
                       "wait_seconds": 3500}
        try:
            stored = json.loads((data_dir() / "preferences.json").read_text(encoding="utf-8"))
            for name in ("enabled", "autostart", "summary"):
                if type(stored.get(name)) is bool:
                    self.config[name] = stored[name]
            if stored.get("language") in ("ru", "en"):
                self.config["language"] = stored["language"]
            if isinstance(stored.get("voice_id"), str):
                self.config["voice_id"] = stored["voice_id"]
            if stored.get("session_id"):
                self.config["session_id"] = session_id(stored["session_id"])
        except (OSError, ValueError, TypeError):
            pass
        self.notifier.voice_id = self.config["voice_id"]

    def save(self):
        root = data_dir()
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / "preferences.tmp"
        temporary.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(root / "preferences.json")

    def start_audio(self):
        from .codex_audio import LocalAudio
        from .codex_win import emergency_pressed
        if self.audio:
            self.audio.stop()
        self.audio = LocalAudio(self.session, self.notifier, self.config["language"], emergency_pressed,
                                self.emergency.set)
        self.audio.start()

    def disable(self):
        self.session.disable()
        self.notifier.stop()
        if self.audio:
            self.audio.stop()
            self.audio = None

    def handle(self, request):
        with self.operations:
            return self._handle(request)

    def _handle(self, request):
        self.last_request = time.monotonic()
        action = request.get("action")
        if action == "status":
            value = self.session.snapshot()
            value.update({"microphone_ready": bool(self.session.enabled and self.audio and self.audio.ready.is_set()
                                                   and self.audio.thread.is_alive() and not self.audio.error),
                          "autostart": self.config["autostart"], "language": self.config["language"],
                          "speaking": self.notifier.speaking, "speech_error": self.notifier.error,
                          "voices": [{"id": v[0], "name": v[1]} for v in self.notifier.voices],
                          "version": "0.1.0-beta.3"})
            return value
        if action == "enable":
            target = session_id(request.get("session_id"))
            from .model_setup import model_path, valid_model
            if not all(valid_model(model_path(lang)) for lang in ("en", "ru")):
                raise RuntimeError("Модели не готовы. Вызови voice_prepare_models, затем voice_enable.")
            self.disable()
            self.config.update({"enabled": True, "session_id": target})
            self.session.enable(target, summary=self.config["summary"])
            self.save()
            self.start_audio()
            return self.handle({"action": "status"})
        if action == "disable":
            self.config["enabled"] = False
            self.disable()
            self.save()
            return self.session.snapshot()
        if action == "settings":
            changes = {}
            for name in ("autostart", "summary"):
                if name in request:
                    if type(request[name]) is not bool:
                        raise ValueError(name + " должен быть логическим значением")
                    changes[name] = request[name]
            if "language" in request:
                if request["language"] not in ("ru", "en"):
                    raise ValueError("Язык диктовки: ru или en")
                if self.session.enabled:
                    raise ValueError("Перед сменой языка выключи голосовой режим")
                changes["language"] = request["language"]
            if "voice_id" in request:
                value = request["voice_id"]
                if not isinstance(value, str) or len(value) > 2048:
                    raise ValueError("voice_id должен быть строкой из voice_status")
                if value and value not in [item[0] for item in self.notifier.voices]:
                    raise ValueError("Выбери установленный голос из voice_status")
                changes["voice_id"] = value
            self.config.update(changes)
            self.notifier.voice_id = self.config["voice_id"]
            self.session.summary = self.config["summary"]
            self.save()
            return self.handle({"action": "status"})
        if action == "repeat":
            if self.session.state == "recording":
                raise RuntimeError("Сначала закончи или отмени диктовку")
            if self.session.readout:
                self.notifier.speak(self.session.readout)
                return {"repeated": True}
            return {"repeated": False, "reason": "В памяти пока нет сводки"}
        if action == "hook":
            event = request.get("event", {})
            target = session_id(event.get("session_id"))
            name = event.get("hook_event_name")
            if self.config["session_id"] == target and type(event.get("host_pid")) is int:
                self.host_pid = event["host_pid"]
            if name == "SessionStart":
                if (not self.session.enabled and self.config["enabled"] and self.config["autostart"]
                        and self.config["session_id"] == target):
                    self.session.enable(target, summary=self.config["summary"])
                    self.start_audio()
                return {"hookSpecificOutput": {"hookEventName": name,
                         "additionalContext": self.session.context(target)}}
            if name == "UserPromptSubmit":
                self.session.begin_turn(target)
                return {"hookSpecificOutput": {"hookEventName": name,
                         "additionalContext": self.session.context(target)}}
            if name == "Stop":
                if not self.session.matches(target):
                    return {}
                value = self.session.finish(target, event.get("turn_id"), event.get("last_assistant_message"))
                if value:
                    self.notifier.speak(value)
                elif not self.session.summary:
                    self.notifier.tone("done")
                return {"listen": True, "wait_seconds": self.config["wait_seconds"]}
            if name == "Interrupt":
                self.session.interrupt(target)
                self.notifier.stop()
                return {}
            if name == "SessionEnd" and self.session.matches(target):
                self.disable()
                return {}
            return {}
        if action == "wait":
            revision = self.session.wait(request.get("session_id"), request.get("ticket"))
            return {"revision": revision}
        if action == "take":
            return self.session.take(request.get("session_id"), request.get("ticket"), request.get("revision"))
        if action == "release":
            self.session.release(request.get("ticket"))
            return {}
        if action == "shutdown":
            self.disable()
            self.closed.set()
            return {"stopped": True}
        raise ValueError("Неизвестное действие")

    def connection(self, connection):
        with connection:
            try:
                request = json.loads(connection.recv_bytes(MAX_MESSAGE))
                if not isinstance(request, dict):
                    raise ValueError("Ожидался JSON объект")
                result = self.handle(request)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            try:
                connection.send_bytes(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            except (OSError, EOFError):
                pass

    def run(self):
        def housekeeping():
            while True:
                time.sleep(.25)
                if self.closed.is_set():
                    self.notifier.close()
                    os._exit(0)
                self.session.expire_waiters()
                if self.emergency.is_set():
                    # The emergency hotkey persists OFF, even across application restart.
                    with self.operations:
                        self.config["enabled"] = False
                        self.save()
                        self.emergency.clear()
                if self.session.enabled and self.host_pid:
                    from .codex_win import process_alive
                    if not process_alive(self.host_pid):
                        with self.operations:
                            self.disable()
                if not self.session.enabled and time.monotonic() - self.last_request > 180:
                    self.notifier.close()
                    os._exit(0)
        threading.Thread(target=housekeeping, daemon=True).start()
        with Listener(pipe_address(), family="AF_PIPE", authkey=auth_key()) as listener:
            while not self.closed.is_set():
                connection = listener.accept()
                threading.Thread(target=self.connection, args=(connection,), daemon=True).start()


def run_service():
    """A named mutex prevents different Codex tasks from opening two microphones."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    name = "Local\\" + pipe_address().rsplit("\\", 1)[-1]
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if ctypes.get_last_error() == 183:
            return
        Service().run()
    finally:
        kernel.CloseHandle(handle)


def wait_for_voice(target, timeout=3500, cancelled=lambda: False):
    ticket = secrets.token_hex(16)
    revision = rpc({"action": "wait", "session_id": target, "ticket": ticket}).get("revision")
    if revision is None:
        return {"ended": True}
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline and not cancelled():
            result = rpc({"action": "take", "session_id": target, "ticket": ticket, "revision": revision}, start=False)
            if "message" in result or result.get("ended"):
                return result
            time.sleep(.15)
        return {"ended": True, "timeout": not cancelled()}
    finally:
        try:
            rpc({"action": "release", "ticket": ticket}, start=False)
        except RuntimeError:
            pass
