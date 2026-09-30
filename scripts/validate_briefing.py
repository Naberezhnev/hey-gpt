"""Generate a synthetic readout into WAV with real SAPI; no microphone or chat."""
import argparse
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hey_gpt.briefing import make_briefing
from hey_gpt.notifications import Notifications


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import comtypes.client
    create = comtypes.client.CreateObject
    streams = []
    finished = threading.Event()
    briefing = make_briefing("Голосовая сводка\nЧерновик письма подготовлен. Отправка ожидает твоего решения.\n"
        "Вопросы к тебе\n1. От кого отправить письмо?\nА. От меня.\nБ. От компании.\n2. Какой язык выбрать?\nА. Русский.\nБ. Английский.")
    def factory(name, *arguments, **kwargs):
        result = create(name, *arguments, **kwargs)
        if name == "SAPI.SpVoice":
            stream = create("SAPI.SpFileStream")
            stream.Open(str(args.output.resolve()), 3, False)
            result.AudioOutputStream = stream
            streams.append(stream)
        return result
    def activity(active):
        if not active:
            for stream in streams:
                stream.Close()
            streams.clear()
            finished.set()
    with patch("comtypes.client.CreateObject", side_effect=factory):
        notifications = Notifications(activity)
        try:
            notifications.speak(briefing.spoken)
            if not finished.wait(20):
                raise RuntimeError(notifications.error or "SAPI readout did not complete")
            if notifications.error:
                raise RuntimeError(notifications.error)
        finally:
            notifications.close()
    with wave.open(str(args.output), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if duration < 1:
            raise AssertionError("The readout contains no speech")
    print(f"PASS real SAPI summary + two questions; synthetic WAV {duration:.1f}s; no speaker/microphone used")


if __name__ == "__main__":
    main()
