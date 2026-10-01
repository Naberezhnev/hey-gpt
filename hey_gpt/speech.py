"""Local phrase-only microphone worker. Emits events, never audio or transcripts."""
import argparse
from array import array
import json
import queue
import sys
import time
import wave
import math
import threading

from .model_setup import model_path, valid_model

PHRASES = {"hi chat g p t": "WAKE", "hi chat gpt": "WAKE",
           "hi g p t": "WAKE", "hi gpt": "WAKE",
           "stop g p t": "STOP", "stop gpt": "STOP",
           "привет джи пи ти": "WAKE", "привет чат джи пи ти": "WAKE",
           "стоп джи пи ти": "STOP", "стоп г п т": "STOP",
           "pause g p t": "PAUSE", "pause gpt": "PAUSE",
           "пауза джи пи ти": "PAUSE", "пауза г п т": "PAUSE",
           "repeat": "REPEAT", "repeat g p t": "REPEAT", "repeat gpt": "REPEAT",
           "повтори": "REPEAT", "повтори джи пи ти": "REPEAT"}


def command_from_result(result):
    text = " ".join(result.get("text", "").lower().split())
    words = result.get("result", [])
    # [unk] can represent the dictated sentence before the final stop phrase.
    tokens = text.split()
    while tokens and tokens[0] == "[unk]":
        tokens.pop(0)
    phrase = " ".join(tokens)
    command = PHRASES.get(phrase)
    if command in ("WAKE", "REPEAT") and phrase != text:
        return None
    relevant = words[-len(tokens):] if tokens else []
    if (not command or len(relevant) != len(tokens)
            or any(word.get("word") != token for word, token in zip(relevant, tokens))
            or any(word.get("conf", 0) < 0.5 for word in relevant)
            or sum(word.get("conf", 0) for word in relevant) / len(relevant) < 0.8):
        return None
    return command


def emit(event, **values):
    print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


def recognizer(model, rate, language="en"):
    from vosk import KaldiRecognizer
    phrases = [phrase for phrase in PHRASES
               if (phrase[0].isascii() if language == "en" else not phrase[0].isascii())
               if all(model.vosk_model_find_word(word) >= 0 for word in phrase.split())]
    if not any(PHRASES[p] == "WAKE" for p in phrases) or not any(PHRASES[p] == "STOP" for p in phrases):
        raise RuntimeError("Модель не содержит слов для голосовых команд.")
    result = KaldiRecognizer(model, rate, json.dumps(phrases + ["[unk]"], ensure_ascii=False))
    result.SetWords(True)
    result.SetPartialWords(True)
    return result


class CommandDecoder:
    """Finalize confident complete phrases after a short actual silence."""
    def __init__(self, rec, rate):
        self.rec, self.rate = rec, rate
        self.elapsed = self.silence = 0
        self.last_command_age = None

    def reset(self):
        self.rec.Reset()
        # Vosk Reset keeps word timestamps relative to all accepted audio.
        self.silence = 0
        self.last_command_age = None

    def decode(self, result):
        command = command_from_result(result)
        self.last_command_age = None
        if command:
            tokens = result.get("text", "").split()
            while tokens and tokens[0] == "[unk]":
                tokens.pop(0)
            words = result.get("result", [])
            start = words[-len(tokens)].get("start") if tokens and len(words) >= len(tokens) else None
            if isinstance(start, (int, float)) and 0 <= start <= self.elapsed:
                self.last_command_age = self.elapsed - start
        return command

    def accept(self, data):
        duration = len(data) / (2 * self.rate)
        self.elapsed += duration
        samples = array("h", data)
        rms = math.sqrt(sum(value * value for value in samples) / max(1, len(samples)))
        self.silence = self.silence + duration if rms < 120 else 0
        if self.rec.AcceptWaveform(data):
            return self.decode(json.loads(self.rec.Result()))
        if self.silence < .35:
            return None
        partial = json.loads(self.rec.PartialResult())
        words = partial.get("partial_result", [])
        candidate = {"text": partial.get("partial", ""), "result": words}
        if (command_from_result(candidate) and words
                and self.elapsed - words[-1].get("end", self.elapsed) >= .4):
            # Final confidence remains authoritative; partial text alone can't click.
            command = self.decode(json.loads(self.rec.FinalResult()))
            self.rec.Reset()
            self.silence = 0
            return command
        return None


class MicrophoneGate:
    """Drop audio captured during narration, including queued speaker echoes."""
    def __init__(self):
        self._muted = False
        self._revision = 0
        self._lock = threading.Lock()

    def set_muted(self, value):
        with self._lock:
            self._muted = value
            self._revision += 1

    def snapshot(self):
        with self._lock:
            return self._muted, self._revision

    def accepts(self, captured):
        current = self.snapshot()
        return not current[0] and not captured[0] and captured[1] == current[1]


def run(device=None, probe_seconds=None):
    import sounddevice as sd
    from vosk import Model, SetLogLevel
    if not valid_model(model_path()):
        raise RuntimeError("Речевая модель не установлена. Нажми «Подготовить модель».")
    SetLogLevel(-1)
    model = Model(str(model_path()))
    info = sd.query_devices(device, "input")
    rate = int(info["default_samplerate"])
    recs = [recognizer(model, rate)]
    if valid_model(model_path("ru")):
        recs.append(recognizer(Model(str(model_path("ru"))), rate, "ru"))
    decoders = [CommandDecoder(rec, rate) for rec in recs]
    gate = MicrophoneGate()
    def listen_controls():
        for line in sys.stdin:
            try:
                value = json.loads(line)
                if value.get("mute") is True:
                    gate.set_muted(True)
                elif value.get("mute") is False:
                    gate.set_muted(False)
            except (ValueError, AttributeError):
                pass
    threading.Thread(target=listen_controls, daemon=True).start()
    blocks = queue.Queue(maxsize=24)
    failure = queue.Queue(maxsize=1)

    def callback(data, frames, timing, status):
        try:
            if status:
                raise RuntimeError("Микрофон пропускает аудио. Закрой лишние приложения и повтори проверку.")
            blocks.put_nowait((bytes(data), gate.snapshot()))
        except (queue.Full, RuntimeError) as exc:
            try:
                failure.put_nowait(str(exc) or "Распознавание не успевает за микрофоном.")
            except queue.Full:
                pass

    with sd.RawInputStream(samplerate=rate, blocksize=max(800, rate // 10),
                           device=device, dtype="int16", channels=1, callback=callback):
        emit("ready", device=info["name"], rate=rate)
        started = time.monotonic()
        last_level = 0
        peak = 0
        last_command = None
        last_command_at = 0
        revision = gate.snapshot()[1]
        while probe_seconds is None or time.monotonic() - started < probe_seconds:
            if not failure.empty():
                raise RuntimeError(failure.get_nowait())
            try:
                data, captured = blocks.get(timeout=2)
            except queue.Empty:
                raise RuntimeError("От микрофона не поступает звук. Проверь подключение и доступ к микрофону.")
            level = min(100, int(max((abs(value) for value in array("h", data)), default=0) * 100 / 32768))
            peak = max(peak, level)
            if time.monotonic() - last_level >= 0.2:
                emit("level", value=level)
                last_level = time.monotonic()
            current_revision = gate.snapshot()[1]
            if revision != current_revision:
                for decoder in decoders:
                    decoder.reset()
                revision = current_revision
                last_command = None
            if not gate.accepts(captured):
                continue
            for decoder in decoders:
                command = decoder.accept(data)
                now = time.monotonic()
                if command and gate.accepts(captured) and (command != last_command or now - last_command_at > 2):
                    emit("command", command=command)
                    last_command, last_command_at = command, now
        emit("probe_complete", peak=peak)
        if peak == 0:
            emit("warning", message="Звук не обнаружен. Произнеси фразу в режиме проверки; если индикатор не движется, выбери другой микрофон или проверь его громкость.")


def replay(path, keep_alive=False):
    """Opt-in developer test: synthetic PCM replaces the microphone input."""
    from vosk import Model, SetLogLevel
    SetLogLevel(-1)
    with wave.open(str(path), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getcomptype() != "NONE":
            raise ValueError("Replay requires mono PCM16 WAV")
        rate = source.getframerate()
        recs = [recognizer(Model(str(model_path(lang))), rate, lang) for lang in ("en", "ru")]
        decoders = [CommandDecoder(rec, rate) for rec in recs]
        emit("ready", device="Синтетическая речь · микрофон не используется", rate=rate)
        started = time.monotonic()
        frames = 0
        last_command, last_at = None, 0
        while data := source.readframes(rate // 10):
            frames += len(data) // 2
            time.sleep(max(0, started + frames / rate - time.monotonic()))
            for decoder in decoders:
                command = decoder.accept(data)
                now = time.monotonic()
                if command and (command != last_command or now - last_at > 2):
                    emit("command", command=command)
                    last_command, last_at = command, now
        for rec in recs:
            command = command_from_result(json.loads(rec.FinalResult()))
            if command and (command != last_command or time.monotonic() - last_at > 2):
                emit("command", command=command)
                last_command, last_at = command, time.monotonic()
    emit("replay_complete")
    while keep_alive:
        time.sleep(.5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int)
    parser.add_argument("--probe", type=float, help="Check microphone for N seconds without desktop actions")
    parser.add_argument("--wav", help="Developer test: replay synthetic mono PCM16 commands in real time")
    parser.add_argument("--keep-alive", action="store_true", help="Keep replay worker alive until GUI closes it")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        replay(args.wav, args.keep_alive) if args.wav else run(args.device, args.probe)
    except Exception as error:
        emit("error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
