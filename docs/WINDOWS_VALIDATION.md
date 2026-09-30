# First Windows validation

Status: **local startup and compilation checks passed on September 30, 2026; live dictation pending**.

Python 3.12.7 on Windows: all 18 controller tests passed, Tkinter and the UI Automation adapter initialized, and the application window opened. The local System.Speech installed-recognizer list was empty, so recognition and live dictation could not yet be validated.

Record the OS version, Python version, browser/app version, UI language, microphone, and installed speech recognizer. Do not include private prompt content in public reports.

| Check | Expected result | Current result |
|---|---|---|
| `scripts/validate_speech.ps1` | Embedded C# compiles | Passed locally |
| Application startup | Setup window opens | Passed locally |
| Installed recognizer | English System.Speech engine available | Blocked: no installed recognizers on the test computer |
| Enable listening | READY with an installed English recognizer | Pending |
| Control calibration | Four unique, accessible controls in one window | Pending |
| Hi ChatGPT | Mic invoked once; signal after recording starts | Pending |
| Shared microphone | Stop GPT recognized while browser records | Pending |
| Stop GPT | Recording finishes once | Pending |
| Transcription | Helper waits until text stabilizes and Send is enabled | Pending |
| Stop phrase cleanup | Removed and verified, or draft left for correction | Pending |
| Auto-send | Correct draft sent once in the bound chat | Pending |
| Wrong active window/tab | Workflow pauses without sending | Pending |
| Existing draft | Dictation does not overwrite it | Pending |
| Pause / Ctrl+Alt+P | Helper releases its recognition process | Pending |
| Speaker playback / room noise | False activations measured | Pending |

Suggested first exercise: dictate a harmless sentence into a new test chat, inspect it in review mode, then enable automatic sending for ten repetitions. Stop at the first unexpected click or transcription error and document the failed prerequisite.
