# Windows validation — 0.4.0 beta

1 October 2026, Windows 11 x64, Python 3.12.7.

| Check | Result |
|---|---|
| Workflow, cancellation, commands, settings, model extraction, adapter and GUI | 86 tests passed |
| English/Russian Vosk models and grammar | Passed |
| Synthetic wake (Hi ChatGPT, Hi GPT, Russian), stop and pause phrases | Passed |
| Ordinary English/Russian sentences, Stop GPT followed by more words | No command emitted |
| English Repeat and Russian Повтори synthetic recordings | Passed |
| Two simulated conversation cycles | Passed: question readout → dictated answer → next summary; two sends, no duplicate |
| Real ChatGPT window: latest reply accessibility read | Passed, 453 characters; no message saved or sent |
| Nested speaker headings, flattened message tree, user copy buttons | Regression checks passed; user content excluded |
| Real SAPI summary and two questions | Passed, synthetic WAV; no speaker or microphone used |
| Cancellable voice and literal XML-like text | Passed; speech purged, queued content discarded |
| Audio captured before/during narration | Dropped; decoder reset before commands resume |
| Browser tab vs page tab regression | Passed: document tabs excluded; selected browser tab isn't selected again |
| Late recording after cancellation | Passed: stopped without sending; repeated pause doesn't duplicate clicks |
| Pause during transcription | Passed: draft unchanged, no send |
| Start confirmation audio | Passed: short tone; voice method not called |
| Source GUI + child microphone worker smoke test | Passed |
| Packaged HeyGPT.exe + packaged child worker smoke test | Passed; exit 0; ui_ready and microphone_worker_ready true |
| Installed SAPI voice in source and packaged app | speech_voice_ready true |
| Packaged child worker: English/Russian repeat | Both synthetic WAVs emitted REPEAT; exit 0 |
| Default notification mode in packaged build | tones |
| Native UI Automation libraries in packaged build | Present |
| Real ChatGPT/Yandex dictation start and finish | Confirmed in previous session |
| User's spoken command recognition and program operation | User confirmed; reported tab, voice and delay issues |
| Full live voice briefing → user answer → next briefing | Device trial still required |
| Ten clean live cycles, distance/noise measurements, other browsers/Codex | Not yet established |

The Windows archive contains the executable, the child executable, dependencies and license texts. Speech models are downloaded separately once. No installed Python is used by the frozen smoke test.

Mock/regression checks and synthetic recognition are distinguished from real service validation. The local HTML fixture is an imitation and has not been presented as a live ChatGPT result. Model decoding warnings about word alignment were observed during synthetic finalization; all twelve expected command/negative outcomes passed.

The source and frozen smoke reports are local artifacts and contain no recorded audio or message text. The synthetic WAV fixtures are generated Windows speech, not microphone recordings.
