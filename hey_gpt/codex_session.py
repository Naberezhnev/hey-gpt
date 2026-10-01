"""Voice continuation state for one explicitly selected Codex task.

No OS, microphone or network dependencies. Text and readouts live only in RAM.
"""
from collections import deque
from dataclasses import dataclass
import re
import threading
import time

from .briefing import VOICE_INSTRUCTION, make_briefing
from .core import strip_stop_command


def session_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Нужен session_id текущей задачи из обработчика SessionStart.")
    return value


@dataclass(frozen=True)
class DictatedMessage:
    sequence: int
    text: str


class VoiceSession:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.RLock()
        self.target = None
        self.enabled = False
        self.summary = True
        self.state = "disabled"
        self.error = ""
        self.readout = ""
        self.revision = 0
        self.sequence = 0
        self.recording_at = 0
        self.waiters = set()
        self.waiter_touched = {}
        self.messages = deque(maxlen=1)
        self.completed_turns = deque(maxlen=64)

    def enable(self, target, *, summary=True):
        target = session_id(target)
        with self.lock:
            self._clear()
            self.target, self.enabled, self.summary = target, True, summary
            self.readout, self.error = "", ""
            self.completed_turns.clear()
            self.state = "standby"

    def _clear(self):
        self.revision += 1
        self.messages.clear()
        self.waiters.clear()
        self.waiter_touched.clear()

    def disable(self):
        with self.lock:
            self._clear()
            self.enabled = False
            self.state = "disabled"
            self.readout = ""

    def matches(self, target):
        return self.enabled and self.target == target

    def begin_turn(self, target):
        with self.lock:
            if not self.matches(target):
                return False
            self._clear()
            self.state = "working"
            return True

    def interrupt(self, target):
        with self.lock:
            if self.matches(target):
                self._clear()
                self.state = "standby"

    def finish(self, target, turn, response):
        with self.lock:
            if not self.matches(target):
                return None
            # Stop continuations may retain the same Codex turn_id. A new
            # delivered human message advances revision and needs a new readout.
            completion = (turn, self.revision)
            if turn and completion in self.completed_turns:
                return None
            if turn:
                self.completed_turns.append(completion)
            self.state = "standby"
            self.messages.clear()
            self.readout = ""
            if not response or not response.strip():
                self.error = "Текст ответа недоступен. Результат не озвучен."
                return None
            self.error = ""
            if self.summary:
                self.readout = make_briefing(response).spoken
            return self.readout

    def wait(self, target, ticket):
        with self.lock:
            if not self.matches(target) or self.state == "working":
                return None
            self.waiters.add(ticket)
            self.waiter_touched[ticket] = self.clock()
            return self.revision

    def release(self, ticket):
        with self.lock:
            self.waiters.discard(ticket)
            self.waiter_touched.pop(ticket, None)
            if not self.waiters and self.state == "recording":
                self.revision += 1
                self.state = "standby"
                self.messages.clear()

    def take(self, target, ticket, revision):
        with self.lock:
            if (not self.matches(target) or revision != self.revision or ticket not in self.waiters):
                return {"ended": True}
            if self.state == "error":
                return {"ended": True, "error": self.error}
            self.waiter_touched[ticket] = self.clock()
            if self.messages:
                message = self.messages.popleft()
                # Consume once before returning. A lost IPC response is never resent.
                self.waiters.clear()
                self.waiter_touched.clear()
                self.state = "working"
                self.revision += 1
                return {"message": message.text, "sequence": message.sequence}
            return {"waiting": True, "state": self.state}

    def wake(self):
        with self.lock:
            if not self.enabled or self.state not in ("standby", "paused", "error"):
                return False
            if not self.waiters:
                self.error = "Нет активного ожидания голоса. Запусти голосовой режим в выбранной задаче."
                return False
            self.error = ""
            self.state = "recording"
            self.recording_at = self.clock()
            return True

    def pause(self):
        with self.lock:
            self.messages.clear()
            if self.enabled:
                self.state = "paused"

    def expire_waiters(self):
        with self.lock:
            for ticket, touched in list(self.waiter_touched.items()):
                if self.clock() - touched > 10:
                    self.release(ticket)

    def complete_dictation(self, text, confidence=1.0, *, stop_removed=False):
        with self.lock:
            if self.state != "recording" or not self.enabled or not self.waiters:
                return False
            text = text.strip()
            if not stop_removed:
                text = strip_stop_command(text).strip()
                text = re.sub(r"(?:^|\s)стоп\s+джипити[.!?,\s]*$", "", text, flags=re.I).strip()
            self.state = "standby"
            if not text or len(text) > 8000 or confidence < .65:
                self.error = "Диктовка пустая, слишком длинная или распознана неуверенно. Сообщение не отправлено."
                return False
            self.sequence += 1
            self.messages.append(DictatedMessage(self.sequence, text))
            return True

    def recording_expired(self):
        with self.lock:
            if self.state == "recording" and self.clock() - self.recording_at > 120:
                self.pause()
                self.error = "Диктовка превысила две минуты и отменена без отправки."
                return True
            return False

    def fail(self, error):
        with self.lock:
            self.messages.clear()
            self.state = "error" if self.enabled else "disabled"
            self.error = str(error)

    def snapshot(self):
        with self.lock:
            return {"enabled": self.enabled, "session_id": self.target,
                    "state": self.state, "waiting_for_voice": bool(self.waiters),
                    "summary": self.summary, "error": self.error}

    def context(self, target):
        value = f"Hey GPT: session_id текущей задачи: {target}. "
        if self.matches(target):
            value += "Голосовой режим привязан к этой задаче. "
            if self.summary:
                value += VOICE_INSTRUCTION
        else:
            value += "Микрофон включается только явным вызовом voice_enable для этой задачи."
        return value
