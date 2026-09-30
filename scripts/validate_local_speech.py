"""Recognize synthetic Windows speech; never record a person's microphone."""
import json
import argparse
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hey_gpt.model_setup import model_path, valid_model
from hey_gpt.speech import CommandDecoder, command_from_result, recognizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate-fixtures", action="store_true", help="Save synthetic speech fixtures for CI without Windows voice dependencies")
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "speech"
    from vosk import Model, SetLogLevel
    if not valid_model(model_path()):
        raise RuntimeError("Prepare the model first")
    SetLogLevel(-1)
    models = [(Model(str(model_path())), "en"), (Model(str(model_path("ru"))), "ru")]
    samples = [("hi", "Hi chat G P T", "WAKE", "en-US"),
               ("hi_short", "Hi G P T", "WAKE", "en-US"),
               ("stop", "Stop G P T", "STOP", "en-US"),
               ("ru_hi", "Привет джи пи ти", "WAKE", "ru-RU"),
               ("ru_stop", "Стоп джи пи ти", "STOP", "ru-RU"),
               ("pause", "Pause G P T", "PAUSE", "en-US"),
               ("ru_pause", "Пауза джи пи ти", "PAUSE", "ru-RU"),
               ("repeat", "Repeat", "REPEAT", "en-US"),
               ("ru_repeat", "Повтори", "REPEAT", "ru-RU"),
               ("stop_continued", "Stop G P T training is the subject of the article", None, "en-US"),
               ("ordinary", "The weather is pleasant and the blue sky is clear", None, "en-US"),
               ("ru_ordinary", "Сегодня хорошая погода и голубое небо", None, "ru-RU")]
    with tempfile.TemporaryDirectory(prefix="hey-gpt-speech-test-") as folder:
        for name, phrase, expected, culture in samples:
            path = Path(folder) / (name + ".wav")
            # Strings are arguments, never interpolated into PowerShell code.
            script = Path(folder) / "synthesize.ps1"
            script.write_text("param([string]$Path,[string]$Phrase,[string]$Culture)\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,"
                "[System.Speech.Synthesis.VoiceAge]::NotSet,0,[System.Globalization.CultureInfo]::GetCultureInfo($Culture))\n"
                "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
                "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)\n"
                "$s.SetOutputToWaveFile($Path,$f)\n$s.Speak($Phrase)\n$s.Dispose()\n", encoding="utf-8")
            fixture = fixtures / (name + ".wav")
            if fixture.is_file() and not args.generate_fixtures:
                path = fixture
            else:
                subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script),
                                "-Path", str(path), "-Phrase", phrase, "-Culture", culture], check=True)
                if args.generate_fixtures:
                    fixtures.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, fixture)
            with wave.open(str(path), "rb") as audio:
                recs = [recognizer(model, audio.getframerate(), language) for model, language in models]
                decoders = [CommandDecoder(rec, audio.getframerate()) for rec in recs]
                commands = []
                while data := audio.readframes(1600):
                    for decoder in decoders:
                        commands.append(decoder.accept(data))
                for _ in range(10):
                    for decoder in decoders:
                        commands.append(decoder.accept(b"\0" * 3200))
                for rec in recs:
                    commands.append(command_from_result(json.loads(rec.FinalResult())))
            commands = list(dict.fromkeys(command for command in commands if command))
            if commands != ([expected] if expected else []):
                raise AssertionError(f"{name}: expected {expected}, got {commands}")
            print(f"PASS synthetic sample: {name}")


if __name__ == "__main__":
    main()
