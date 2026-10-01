"""Real Vosk pipeline: synthetic wake -> RU dictation -> stop, no microphone."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hey_gpt.codex_audio import LocalAudio
from hey_gpt.codex_session import VoiceSession
from hey_gpt.speech import CommandDecoder


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-fixture", action="store_true")
    args = parser.parse_args()
    fixtures = ROOT / "tests/fixtures/speech"
    path = fixtures / "ru_dictation.wav"
    if args.generate_fixture or not path.is_file():
        script = ROOT / "artifacts/validation/synthesize_codex.ps1"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("param([string]$Path,[string]$Phrase)\n"
            "Add-Type -AssemblyName System.Speech\n"
            "$speech = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            "$speech.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,[System.Speech.Synthesis.VoiceAge]::NotSet,0,[System.Globalization.CultureInfo]::GetCultureInfo('ru-RU'))\n"
            "$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)\n"
            "$speech.SetOutputToWaveFile($Path,$format)\n$speech.Speak($Phrase)\n$speech.Dispose()\n", encoding="utf-8")
        subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Path", str(path),
                        "-Phrase", "Для разработчиков. Добавь ограничения."], check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    samples = []
    for file in (fixtures / "hi_short.wav", path, fixtures / "ru_stop.wav"):
        with wave.open(str(file), "rb") as source:
            assert source.getnchannels() == 1 and source.getsampwidth() == 2 and source.getframerate() == 16000
            while block := source.readframes(1600):
                samples.append(block)
        samples.extend([b"\0" * 3200] * 12)
    samples = samples + [b"\0" * 3200] * 15 + samples
    voice = VoiceSession()
    voice.enable("synthetic-voice")
    revision = voice.wait("synthetic-voice", "validation")
    notifications = Mock(speaking=False)
    audio = LocalAudio(voice, notifications)
    traces = []
    decode_original = CommandDecoder.decode
    def decode_trace(decoder, result):
        command = decode_original(decoder, result)
        if command:
            traces.append({"command": command, "elapsed": decoder.elapsed,
                           "age": decoder.last_command_age, "words": result.get("result")})
        return command
    class SyntheticStream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]
            self.stop = threading.Event()
        def feed(self):
            for block in samples:
                if self.stop.wait(.1):
                    return
                self.callback(block, len(block) // 2, None, None)
        def __enter__(self):
            self.thread = threading.Thread(target=self.feed, daemon=True)
            self.thread.start()
            return self
        def __exit__(self, *unused):
            self.stop.set()
            self.thread.join(timeout=1)
    with patch("sounddevice.query_devices", return_value={"default_samplerate": 16000}), patch("sounddevice.RawInputStream", SyntheticStream), patch.object(CommandDecoder, "decode", decode_trace):
        audio.start()
        try:
            assert audio.ready.wait(20), "Audio worker startup timed out"
            assert not audio.error, audio.error
            deadline = time.monotonic() + len(samples) / 10 + 5
            results = []
            while time.monotonic() < deadline:
                result = voice.take("synthetic-voice", "validation", revision)
                if "message" in result:
                    results.append(result)
                    assert voice.take("synthetic-voice", "validation", revision).get("ended")
                    if len(results) == 2:
                        break
                    voice.finish("synthetic-voice", "synthetic-turn-2", "Голосовая сводка\nПервый запрос выполнен.")
                    revision = voice.wait("synthetic-voice", "validation")
                if audio.error:
                    print(json.dumps({"synthetic_timing": traces}, ensure_ascii=False))
                    raise AssertionError(audio.error)
                time.sleep(.1)
            assert len(results) == 2, voice.snapshot()
            for result in results:
                text = result["message"]
                assert "разработчик" in text and "ограничен" in text, text
                assert "стоп" not in text and "hi" not in text, text
            assert results[0]["sequence"] == 1 and results[1]["sequence"] == 2
            print(json.dumps({"synthetic_voice_cycles": 2, "microphone_opened": False,
                              "message_delivered_once": True, "wake_and_stop_removed": True,
                              "dictation": text}, ensure_ascii=False))
        finally:
            audio.stop()


if __name__ == "__main__":
    main()
