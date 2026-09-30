# Windows validation

September 30, 2026: Windows 11 x64, Python 3.12.7, Hey GPT 0.2 alpha.

| Check | Result |
|---|---|
| Controller, command parsing, settings, archive handling, adapter and GUI tests | 35 passed locally |
| Local English Vosk model load and command grammar | Passed |
| Synthetic Hi ChatGPT / Stop GPT samples | Both recognized |
| Synthetic ordinary sentence | No command emitted |
| Tkinter setup window and Windows UI Automation initialization | Passed |
| Default microphone stream at 44.1 kHz | Opened and released successfully |
| Audible signal in the brief microphone probe | No signal detected; repeat while speaking |
| Legacy C# System.Speech compilation | Passed; legacy engine not used by v0.2 UI |
| Actual spoken commands, accents, room noise, distance | Pending user trial |
| Calibration in the actual ChatGPT/Codex interface | Pending user trial |
| Helper/browser simultaneous microphone access | Pending user trial |
| Dictation → finish → transcript cleanup → optional send | Pending user trial |
| Ten consecutive correct live cycles | Pending user trial |

Passing synthetic and mock checks does not establish end-to-end compatibility. Start with the phrase-check mode and review mode; follow [START_HERE_RU.md](../START_HERE_RU.md). Do not include private prompt content in public test reports.