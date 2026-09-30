"""Local phrase-only microphone worker. Emits events, never audio or transcripts."""
import argparse
from array import array
import json
import queue
import sys
import time

from .model_setup import model_path, valid_model

PHRASES = {"hi chat g p t": "WAKE", "hi chat gpt": "WAKE",
           "stop g p t": "STOP", "stop gpt": "STOP"}


def command_from_result(result):
    text = " ".join(result.get("text", "").lower().split())
    words = result.get("result", [])
    # [unk] can represent the dictated sentence before the final stop phrase.
    tokens = text.split()
    while tokens and tokens[0] == "[unk]":
        tokens.pop(0)
    phrase = " ".join(tokens)
    command = PHRASES.get(phrase)
    if command == "WAKE" and phrase != text:
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


def recognizer(model, rate):
    from vosk import KaldiRecognizer
    phrases = [phrase for phrase in PHRASES
               if all(model.vosk_model_find_word(word) >= 0 for word in phrase.split())]
    if not any(PHRASES[p] == "WAKE" for p in phrases) or not any(PHRASES[p] == "STOP" for p in phrases):
        raise RuntimeError("Модель не содержит слов для голосовых команд.")
    result = KaldiRecognizer(model, rate, json.dumps(phrases + ["[unk]"]))
    result.SetWords(True)
    return result


def run(device=None, probe_seconds=None):
    import sounddevice as sd
    from vosk import Model, SetLogLevel
    if not valid_model(model_path()):
        raise RuntimeError("Речевая модель не установлена. Нажми «Подготовить модель».")
    SetLogLevel(-1)
    model = Model(str(model_path()))
    info = sd.query_devices(device, "input")
    rate = int(info["default_samplerate"])
    rec = recognizer(model, rate)
    blocks = queue.Queue(maxsize=24)
    failure = queue.Queue(maxsize=1)

    def callback(data, frames, timing, status):
        try:
            if status:
                raise RuntimeError("Микрофон пропускает аудио. Закрой лишние приложения и повтори проверку.")
            blocks.put_nowait(bytes(data))
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
        while probe_seconds is None or time.monotonic() - started < probe_seconds:
            if not failure.empty():
                raise RuntimeError(failure.get_nowait())
            try:
                data = blocks.get(timeout=2)
            except queue.Empty:
                raise RuntimeError("От микрофона не поступает звук. Проверь подключение и доступ к микрофону.")
            level = min(100, int(max((abs(value) for value in array("h", data)), default=0) * 100 / 32768))
            peak = max(peak, level)
            if time.monotonic() - last_level >= 0.2:
                emit("level", value=level)
                last_level = time.monotonic()
            if rec.AcceptWaveform(data):
                command = command_from_result(json.loads(rec.Result()))
                if command:
                    emit("command", command=command)
        emit("probe_complete", peak=peak)
        if peak == 0:
            emit("warning", message="Звук не обнаружен. Произнеси фразу в режиме проверки; если индикатор не движется, выбери другой микрофон или проверь его громкость.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int)
    parser.add_argument("--probe", type=float, help="Check microphone for N seconds without desktop actions")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        run(args.device, args.probe)
    except Exception as error:
        emit("error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
