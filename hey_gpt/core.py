"""Platform-independent workflow. No microphone, network, or desktop access."""
from enum import Enum
import re


class State(Enum):
    IDLE = "Ready for Hi ChatGPT"
    STARTING = "Waiting for recording to start"
    RECORDING = "Recording: say Stop GPT"
    TRANSCRIBING = "Waiting for transcription"
    REVIEW = "Text ready for review"
    ERROR = "Paused after an error"


def strip_stop_command(text: str) -> str:
    """Remove only a trailing fixed stop phrase, never an internal quotation."""
    return re.sub(
        r"(?:^|\s+)(?:stop|стоп)\s+(?:[gг]\s*\.?\s*[pп]\s*\.?\s*[tт]\s*\.?|джи\s*пи\s*ти)[.!?,\s]*$",
        "", text, flags=re.IGNORECASE,
    ).rstrip()


class Controller:
    """Adapter operations must validate their target before each write."""

    def __init__(self, adapter, *, auto_send=False, clock, timeout=45, stable_for=1.5):
        self.adapter = adapter
        self.auto_send = auto_send
        self.clock = clock
        self.timeout = timeout
        self.stable_for = stable_for
        self.state = State.IDLE
        self.error = ""
        self.last_text = None
        self.changed_at = 0.0
        self.started_at = 0.0

    def fail(self, exc):
        self.error = str(exc)
        self.state = State.ERROR

    def reset(self):
        """Resets the controller only; does not silently click an active recording."""
        self.state = State.IDLE
        self.error = ""
        self.last_text = None

    def command(self, command):
        try:
            if command == "WAKE" and self.state is State.IDLE:
                if self.adapter.read_text().strip():
                    raise RuntimeError("В поле уже есть черновик. Отправь или очисти его перед диктовкой.")
                self.adapter.click("microphone")
                self.started_at = self.clock()
                self.state = State.STARTING
            elif command == "STOP" and self.state is State.RECORDING:
                self.adapter.click("finish")
                self.started_at = self.clock()
                self.last_text = None
                self.state = State.TRANSCRIBING
        except Exception as exc:
            self.fail(exc)

    def tick(self):
        if self.state is State.STARTING:
            try:
                if self.adapter.recording_visible():
                    self.state = State.RECORDING
                elif self.clock() - self.started_at >= 10:
                    raise RuntimeError("Запись не началась за 10 секунд. Проверь кнопку диктовки.")
            except Exception as exc:
                self.fail(exc)
            return
        if self.state is not State.TRANSCRIBING:
            return
        try:
            now = self.clock()
            if now - self.started_at >= self.timeout:
                raise RuntimeError(f"Расшифровка не готова за {self.timeout:g} секунд. Проверь результат в чате.")
            # The finish button must disappear before text can be treated as final.
            if self.adapter.recording_visible():
                return
            text = self.adapter.read_text()
            if not text.strip() or not self.adapter.send_enabled():
                return
            if text != self.last_text:
                self.last_text = text
                self.changed_at = now
                return
            if now - self.changed_at < self.stable_for:
                return
            cleaned = strip_stop_command(text)
            if not cleaned.strip():
                raise RuntimeError("После удаления Stop GPT сообщение пустое.")
            if cleaned != text:
                self.adapter.replace_text(text, cleaned)
                if self.adapter.read_text() != cleaned:
                    raise RuntimeError("Не удалось проверить удаление Stop GPT. Исправь черновик вручную.")
            self.state = State.REVIEW
            if self.auto_send:
                # Re-check text and target immediately before the send click.
                if self.adapter.read_text() != cleaned:
                    raise RuntimeError("Текст изменился перед отправкой. Проверь его вручную.")
                self.adapter.click("send")
                self.state = State.IDLE
        except Exception as exc:
            self.fail(exc)
