"""Recognize synthetic Windows speech; never record a person's microphone."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hey_gpt.model_setup import model_path, valid_model
from hey_gpt.speech import command_from_result, recognizer


def main():
    from vosk import Model, SetLogLevel
    if not valid_model(model_path()):
        raise RuntimeError("Prepare the model first")
    SetLogLevel(-1)
    model = Model(str(model_path()))
    samples = [("hi", "Hi chat G P T", "WAKE"), ("stop", "Stop G P T", "STOP"),
               ("ordinary", "The weather is pleasant and the blue sky is clear", None)]
    with tempfile.TemporaryDirectory(prefix="hey-gpt-speech-test-") as folder:
        for name, phrase, expected in samples:
            path = Path(folder) / (name + ".wav")
            # Strings are arguments, never interpolated into PowerShell code.
            script = Path(folder) / "synthesize.ps1"
            script.write_text("param([string]$Path,[string]$Phrase)\n"
                "Add-Type -AssemblyName System.Speech\n"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
                "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,"
                "[System.Speech.Synthesis.VoiceAge]::NotSet,0,[System.Globalization.CultureInfo]::GetCultureInfo('en-US'))\n"
                "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
                "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)\n"
                "$s.SetOutputToWaveFile($Path,$f)\n$s.Speak($Phrase)\n$s.Dispose()\n", encoding="utf-8")
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                            "-Path", str(path), "-Phrase", phrase], check=True)
            with wave.open(str(path), "rb") as audio:
                rec = recognizer(model, audio.getframerate())
                commands = []
                while data := audio.readframes(4000):
                    if rec.AcceptWaveform(data):
                        commands.append(command_from_result(json.loads(rec.Result())))
                commands.append(command_from_result(json.loads(rec.FinalResult())))
            commands = [command for command in commands if command]
            if commands != ([expected] if expected else []):
                raise AssertionError(f"{name}: expected {expected}, got {commands}")
            print(f"PASS synthetic sample: {name}")


if __name__ == "__main__":
    main()
