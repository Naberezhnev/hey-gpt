"""Local wake words and free-form Vosk dictation for the Codex plugin."""
import json
import queue
import threading

from .model_setup import model_path, valid_model
from .speech import CommandDecoder, MicrophoneGate, recognizer


def before_stop(words, stop_start):
    """Keep dictated words before the independently recognized stop audio."""
    if stop_start is None or stop_start < 0:
        raise ValueError("Не удалось отделить завершающую команду от диктовки. Отправка отменена.")
    kept = [word for word in words if isinstance(word.get("end"), (int, float))
            and word["end"] <= stop_start + .05]
    return " ".join(word.get("word", "") for word in kept), [word.get("conf", 0) for word in kept]


class LocalAudio:
    def __init__(self, session, notifications, language="ru", emergency=lambda: False, on_emergency=lambda: None):
        self.session, self.notifications = session, notifications
        self.language, self.emergency = language, emergency
        self.on_emergency = on_emergency
        self.gate = MicrophoneGate()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.thread = None
        self.error = ""

    def mute(self, active):
        self.gate.set_muted(active)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.ready.clear()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.gate.set_muted(True)
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise RuntimeError("Речевой процесс ещё завершает загрузку. Повтори отключение через несколько секунд.")

    def run(self):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            if not all(valid_model(model_path(lang)) for lang in ("en", "ru")):
                raise RuntimeError("Сначала подготовь речевые модели: voice_prepare_models.")
            models = {lang: Model(str(model_path(lang))) for lang in ("en", "ru")}
            info = sd.query_devices(None, "input")
            rate = int(info["default_samplerate"])
            decoders = [CommandDecoder(recognizer(models[lang], rate, lang), rate) for lang in models]
            dictation = KaldiRecognizer(models[self.language], rate)
            dictation.SetWords(True)
            blocks = queue.Queue(maxsize=30)
            overflow = threading.Event()
            def callback(data, frames, timing, status):
                try:
                    if status:
                        overflow.set()
                    blocks.put_nowait((bytes(data), self.gate.snapshot()))
                except queue.Full:
                    overflow.set()
            revision = self.gate.snapshot()[1]
            dictated_words = []
            dictation_elapsed = 0
            last_command, last_at = None, 0
            recording_revision = None
            if self.stop_event.is_set():
                return
            with sd.RawInputStream(samplerate=rate, blocksize=max(800, rate // 10),
                                   dtype="int16", channels=1, callback=callback):
                self.gate.set_muted(self.notifications.speaking)
                self.ready.set()
                last_audio = self.session.clock()
                while not self.stop_event.is_set():
                    if self.emergency():
                        self.session.disable()
                        self.notifications.stop()
                        self.on_emergency()
                        break
                    if overflow.is_set():
                        raise RuntimeError("Потеря аудио микрофона. Диктовка отменена без отправки.")
                    try:
                        data, captured = blocks.get(timeout=.15)
                    except queue.Empty:
                        if self.session.clock() - last_audio > 3:
                            raise RuntimeError("От микрофона не поступает звук. Проверь его подключение.")
                        continue
                    last_audio = self.session.clock()
                    state = self.session.snapshot()["state"]
                    current_revision = self.gate.snapshot()[1]
                    if current_revision != revision or (state != "recording" and recording_revision is not None):
                        for decoder in decoders:
                            decoder.reset()
                        dictation.Reset()
                        dictated_words = []
                        recording_revision = None
                        revision = current_revision
                    if not self.gate.accepts(captured):
                        continue
                    if self.session.recording_expired():
                        continue
                    if state == "recording":
                        recording_revision = revision
                        dictation_elapsed += len(data) / (2 * rate)
                        if dictation.AcceptWaveform(data):
                            part = json.loads(dictation.Result())
                            dictated_words.extend(part.get("result", []))
                    for decoder in decoders:
                        command = decoder.accept(data)
                        now = self.session.clock()
                        if not command or (last_command == command and now - last_at < 2):
                            continue
                        if not self.gate.accepts(captured):
                            continue
                        last_command, last_at = command, now
                        if command == "WAKE" and self.session.wake():
                            dictation.Reset()
                            dictated_words = []
                            # Discard the wake phrase, including the other language decoder.
                            for item in decoders:
                                item.reset()
                            self.notifications.tone("ready")
                            break
                        if command == "STOP" and self.session.snapshot()["state"] == "recording":
                            part = json.loads(dictation.FinalResult())
                            dictated_words.extend(part.get("result", []))
                            age = decoder.last_command_age
                            text, scores = before_stop(dictated_words, dictation_elapsed - age if age is not None else None)
                            confidence = sum(scores) / len(scores) if scores else 0
                            accepted = self.session.complete_dictation(text, confidence, stop_removed=True)
                            dictation.Reset()
                            dictated_words = []
                            self.notifications.tone("done" if accepted else "notice")
                            break
                        if command == "PAUSE":
                            self.session.pause()
                            self.notifications.stop()
                            dictation.Reset()
                            dictated_words = []
                            self.notifications.tone("pause")
                            break
                        if command == "REPEAT" and self.session.readout and state != "recording":
                            self.notifications.speak(self.session.readout)
                            break
        except Exception as exc:
            self.error = str(exc)
            self.session.fail(exc)
            self.ready.set()
