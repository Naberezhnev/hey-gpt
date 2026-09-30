"""Platform-independent workflow. No microphone, network, or desktop access."""
from enum import Enum
import re
from .briefing import with_voice_instruction


class State(Enum):
    IDLE = "Ready for Hi ChatGPT"
    STARTING = "Waiting for recording to start"
    RECORDING = "Recording: say Stop GPT"
    TRANSCRIBING = "Waiting for transcription"
    REVIEW = "Text ready for review"
    SENDING = "Verifying message delivery"
    WAITING = "Waiting for the answer"
    ERROR = "Paused after an error"
    PAUSING = "Stopping dictation without sending"
    PAUSED = "Actions paused; listening for wake"


def strip_stop_command(text: str) -> str:
    """Remove only a trailing fixed stop phrase, never an internal quotation."""
    return re.sub(
        r"(?:^|\s+)(?:stop|стоп)\s+(?:[gг]\s*\.?\s*[pп]\s*\.?\s*[tт]\s*\.?|джи\s*пи\s*ти)[.!?,\s]*$",
        "", text, flags=re.IGNORECASE,
    ).rstrip()


class Controller:
    """Adapter operations must validate their target before each write."""

    def __init__(self, adapter, *, auto_send=False, clock, timeout=45, stable_for=1.5, voice_summary=False):
        self.adapter = adapter
        self.auto_send = auto_send
        self.voice_summary = voice_summary
        self.clock = clock
        self.timeout = timeout
        self.stable_for = stable_for
        self.state = State.IDLE
        self.error = ""
        self.last_text = None
        self.changed_at = 0.0
        self.started_at = 0.0
        self.completed = 0
        self.saw_busy = False
        self.response_baseline = 0
        self.sent_by_us = False
        self.owns_recording = False
        self.cancel_finish_sent = False
        self.cancel_wait_for_start = False

    def suspend(self):
        """Stop owned recording, keep its draft, never send during cancellation."""
        previous = self.state
        self.error = ""
        if previous is State.PAUSING:
            return
        if previous in (State.STARTING, State.RECORDING) or self.owns_recording:
            self.state = State.PAUSING
            self.cancel_wait_for_start = previous is State.STARTING
            self.cancel_finish_sent = False
            self.started_at = self.clock()
            try:
                self.adapter.prepare_target()
                self.tick()
            except Exception as exc:
                self.fail(exc)
        else:
            self.state = State.PAUSED

    def observe_current(self):
        """Notice a task already running when the assistant is enabled."""
        if self.state is not State.IDLE:
            return
        try:
            busy, responses = self.adapter.response_status()
            if busy:
                self.saw_busy, self.response_baseline = True, responses
                self.changed_at = 0
                self.started_at = self.clock()
                self.sent_by_us = False
                self.state = State.WAITING
        except Exception:
            # Passive observation must not interrupt work in another tab.
            pass

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
            if command == "PAUSE":
                self.suspend()
            elif command == "WAKE" and self.state in (State.IDLE, State.ERROR, State.REVIEW, State.PAUSED):
                self.adapter.prepare_target()
                if self.adapter.recording_visible():
                    raise RuntimeError("В чате уже идёт запись. Скажи Stop GPT, чтобы завершить её.")
                if self.adapter.read_text().strip():
                    raise RuntimeError("В поле уже есть черновик. Отправь или очисти его перед диктовкой.")
                self.owns_recording = True
                self.adapter.click("microphone")
                self.error = ""
                self.started_at = self.clock()
                self.state = State.STARTING
            elif command == "STOP" and self.state in (State.RECORDING, State.STARTING, State.ERROR):
                self.adapter.prepare_target()
                if not self.adapter.recording_visible():
                    if self.state is State.STARTING:
                        self.suspend()
                    elif self.state is State.ERROR:
                        self.state = State.PAUSED
                        self.error = ""
                    return
                self.adapter.click("finish")
                self.owns_recording = False
                self.error = ""
                self.started_at = self.clock()
                self.last_text = None
                self.state = State.TRANSCRIBING
        except Exception as exc:
            self.fail(exc)

    def tick(self):
        if self.state is State.PAUSING:
            try:
                recording = self.adapter.recording_visible()
                if recording:
                    if not self.cancel_finish_sent:
                        self.adapter.prepare_target()
                        self.adapter.click("finish")
                        self.cancel_finish_sent = True
                elif self.cancel_finish_sent or not self.cancel_wait_for_start or self.clock() - self.started_at >= 10:
                    self.state = State.PAUSED
                    self.owns_recording = False
                if recording and self.clock() - self.started_at >= 10:
                    raise RuntimeError("Не удалось остановить запись. Останови её в чате; отправка отменена.")
            except Exception as exc:
                self.fail(exc)
            return
        if self.state in (State.SENDING, State.WAITING):
            try:
                now = self.clock()
                busy, responses = self.adapter.response_status()
                self.saw_busy = self.saw_busy or busy
                if self.state is State.SENDING:
                    if not self.adapter.read_text().strip():
                        self.sent_by_us = True
                        self.state = State.WAITING
                        self.started_at = now
                    elif now - self.started_at >= 10:
                        raise RuntimeError("Отправка не подтверждена. Сообщение осталось в поле; повторной отправки не было.")
                elif not busy and (self.saw_busy or responses > self.response_baseline):
                    if not self.changed_at:
                        self.changed_at = now
                    elif now - self.changed_at >= self.stable_for:
                        self.completed += 1
                        self.state = State.IDLE
                else:
                    self.changed_at = 0
                if self.state is State.WAITING and now - self.started_at >= 600:
                    raise RuntimeError("Не удалось подтвердить завершение ответа за 10 минут. Проверь чат.")
            except Exception as exc:
                self.fail(exc)
            return
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
            if self.voice_summary:
                cleaned = with_voice_instruction(cleaned)
            if cleaned != text:
                self.adapter.prepare_target()
                self.adapter.replace_text(text, cleaned)
                if self.adapter.read_text() != cleaned:
                    raise RuntimeError("Не удалось проверить удаление Stop GPT. Исправь черновик вручную.")
            self.state = State.REVIEW
            if self.auto_send:
                self.adapter.prepare_target()
                # Re-check text and target immediately before the send click.
                if self.adapter.read_text() != cleaned:
                    raise RuntimeError("Текст изменился перед отправкой. Проверь его вручную.")
                self.saw_busy, self.response_baseline = self.adapter.response_status()
                self.adapter.click("send")
                self.started_at = self.clock()
                self.changed_at = 0
                self.state = State.SENDING
        except Exception as exc:
            self.fail(exc)
