# Fixed local command grammar. This script does not upload or retain audio.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @'
using System;
using System.Globalization;
using System.Speech.Recognition;
using System.Threading;

public static class HeyGptSpeech {
    public static void Run() {
        RecognizerInfo selected = null;
        foreach (RecognizerInfo info in SpeechRecognitionEngine.InstalledRecognizers()) {
            if (info.Culture.TwoLetterISOLanguageName == "en") {
                selected = info;
                break;
            }
        }
        if (selected == null) {
            Console.WriteLine("ERROR Install an English Windows speech recognition language first.");
            Console.Out.Flush();
            return;
        }
        using (SpeechRecognitionEngine engine = new SpeechRecognitionEngine(selected)) {
            Choices phrases = new Choices(new string[] {
                "hi chat GPT", "hi chat G P T", "stop GPT", "stop G P T"
            });
            GrammarBuilder builder = new GrammarBuilder();
            builder.Culture = selected.Culture;
            builder.Append(phrases);
            engine.LoadGrammar(new Grammar(builder));
            engine.SpeechRecognized += delegate(object sender, SpeechRecognizedEventArgs e) {
                if (e.Result.Confidence < 0.80f) return;
                string text = e.Result.Text.ToLowerInvariant();
                Console.WriteLine(text.StartsWith("hi ") ? "WAKE" : "STOP");
                Console.Out.Flush();
            };
            engine.SetInputToDefaultAudioDevice();
            engine.RecognizeAsync(RecognizeMode.Multiple);
            Console.WriteLine("READY");
            Console.Out.Flush();
            Thread.Sleep(Timeout.Infinite);
        }
    }
}
'@
try { [HeyGptSpeech]::Run() }
catch { Write-Output ('ERROR ' + $_.Exception.Message); exit 1 }
