"""Build a repeatable, synthetic English/Russian workflow command track."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import wave

def make_track(output, language="en"):
    phrases = ("Hi chat G P T", "Stop G P T") if language == "en" else ("Привет джи пи ти", "Стоп джи пи ти")
    culture = "en-US" if language == "en" else "ru-RU"
    with tempfile.TemporaryDirectory(prefix="hey-gpt-synthetic-") as folder:
        script = Path(folder) / "speak.ps1"
        script.write_text("param([string]$Path,[string]$Phrase,[string]$Culture)\n"
            "Add-Type -AssemblyName System.Speech\n"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            "$s.SelectVoiceByHints([System.Speech.Synthesis.VoiceGender]::NotSet,"
            "[System.Speech.Synthesis.VoiceAge]::NotSet,0,[System.Globalization.CultureInfo]::GetCultureInfo($Culture))\n"
            "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
            "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)\n"
            "$s.SetOutputToWaveFile($Path,$f)\n$s.Speak($Phrase)\n$s.Dispose()\n", encoding="utf-8")
        audio = b"\0" * 32000
        for index, phrase in enumerate(phrases):
            path = Path(folder) / f"{index}.wav"
            subprocess.run(["powershell.exe", "-NoProfile", "-File", str(script), "-Path", str(path),
                "-Phrase", phrase, "-Culture", culture], check=True)
            with wave.open(str(path), "rb") as source:
                audio += source.readframes(source.getnframes())
            audio += b"\0" * (32000 * (6 if index == 0 else 3))
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as result:
            result.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            result.writeframes(audio)
    return output

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--language", choices=("en", "ru"), default="en")
    args = parser.parse_args()
    print(make_track(args.output, args.language))
