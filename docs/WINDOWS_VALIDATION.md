# Windows validation — 0.3.1 beta

30 September 2026, Windows 11 x64, Python 3.12.7.

| Check | Result |
|---|---|
| Workflow, cancellation, commands, settings, model extraction, adapter and GUI | 54 tests passed |
| English/Russian Vosk models and grammar | Passed |
| Synthetic wake (Hi ChatGPT, Hi GPT, Russian), stop and pause phrases | Passed |
| Ordinary English/Russian sentences, Stop GPT followed by more words | No command emitted |
| Browser tab vs page tab regression | Passed: document tabs excluded; selected browser tab isn't selected again |
| Late recording after cancellation | Passed: stopped without sending; repeated pause doesn't duplicate clicks |
| Pause during transcription | Passed: draft unchanged, no send |
| Start confirmation audio | Passed: short tone; voice method not called |
| Source GUI + child microphone worker smoke test | Passed |
| Packaged HeyGPT.exe + packaged child worker smoke test | Passed; exit 0; ui_ready and microphone_worker_ready true |
| Default notification mode in packaged build | tones |
| Native UI Automation libraries in packaged build | Present |
| Real ChatGPT/Yandex dictation start and finish | Confirmed in previous session |
| User's spoken command recognition and program operation | User confirmed; reported tab, voice and delay issues |
| Live repeat of corrected tab binding and complete sends in 0.3.1 | Device trial still required |
| Ten clean live cycles, distance/noise measurements, other browsers/Codex | Not yet established |

The Windows archive contains the executable, the child executable, dependencies and license texts. Speech models are downloaded separately once. No installed Python is used by the frozen smoke test.

Mock/regression checks and synthetic recognition are distinguished from real service validation. The local HTML fixture is an imitation and has not been presented as a live ChatGPT result. Model decoding warnings about word alignment were observed during synthetic finalization; all ten expected command/negative outcomes passed.

The source and frozen smoke reports are local artifacts and contain no recorded audio or message text. The synthetic WAV fixtures are generated Windows speech, not microphone recordings.
